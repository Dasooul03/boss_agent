from __future__ import annotations

import sys
import threading
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from agent_cli import request_api_json
from agent_service import agent_contract
from config import Config


def _call(method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 5.0) -> dict[str, Any]:
    try:
        return request_api_json(method, path, payload, timeout=timeout)
    except Exception as exc:
        return agent_contract(ok=False, error=str(exc))


def _api_url(path: str) -> str:
    return f"http://{Config.server_host}:{Config.server_port}{path}"


def _api_has_agent_contract() -> bool:
    try:
        with urlopen(_api_url("/agent/diagnose"), timeout=1.5) as response:
            return 200 <= response.status < 300
    except (OSError, TimeoutError, URLError):
        return False


def _start_embedded_api(app: Any) -> None:
    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 Python 依赖 uvicorn，请先运行: pip install -r requirements.txt") from exc

    config = uvicorn.Config(
        app,
        host=Config.server_host,
        port=int(Config.server_port),
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if _api_has_agent_contract():
            return
        time.sleep(0.2)
    raise RuntimeError(f"内嵌 API 未能在 10 秒内启动: {_api_url('/agent/diagnose')}")


def run_mcp_server(app: Any | None = None) -> int:
    try:
        from mcp.server.fastmcp import FastMCP
    except ModuleNotFoundError:
        print(
            "缺少 MCP 依赖，请先安装 requirements.txt 中的 mcp 包，或继续使用 python main.py agent ...",
            file=sys.stderr,
        )
        return 2

    Config.load()
    if not _api_has_agent_contract():
        if app is None:
            print("MCP 启动失败：本地 API 未运行，且没有可内嵌启动的 app。", file=sys.stderr)
            return 1
        try:
            _start_embedded_api(app)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    mcp = FastMCP("jobseeker")

    @mcp.tool()
    def jobseeker_status() -> dict[str, Any]:
        """Return the current Job Seeker agent status envelope."""
        return _call("GET", "/agent/status")

    @mcp.tool()
    def jobseeker_diagnose() -> dict[str, Any]:
        """Return readiness, recent errors, and the suggested next command."""
        return _call("GET", "/agent/diagnose")

    @mcp.tool()
    def jobseeker_configure(updates: dict[str, Any] | None = None) -> dict[str, Any]:
        """Update allowed non-secret runtime/model settings through the agent whitelist."""
        return _call("POST", "/agent/configure", updates or {})

    @mcp.tool()
    def jobseeker_start() -> dict[str, Any]:
        """Start automation if the saved configuration is ready."""
        return _call("POST", "/agent/start")

    @mcp.tool()
    def jobseeker_pause() -> dict[str, Any]:
        """Pause automation."""
        return _call("POST", "/agent/pause")

    @mcp.tool()
    def jobseeker_stop() -> dict[str, Any]:
        """Stop automation."""
        return _call("POST", "/agent/stop")

    @mcp.tool()
    def jobseeker_wait(until: str = "script_online", timeout: float = 30.0) -> dict[str, Any]:
        """Poll agent status until ready/script/control condition is reached or timeout expires."""
        import time

        deadline = time.monotonic() + max(0.0, timeout)
        last_status: dict[str, Any] = {}
        while time.monotonic() <= deadline:
            last_status = _call("GET", "/agent/status", timeout=3.0)
            data = last_status.get("data") if isinstance(last_status.get("data"), dict) else {}
            backend = data.get("backend") if isinstance(data.get("backend"), dict) else {}
            script = last_status.get("script") if isinstance(last_status.get("script"), dict) else {}
            if (
                until == "ready" and last_status.get("ready")
                or until == "script_online" and script.get("connected")
                or until in {"paused", "stopped", "running"} and backend.get("control") == until
            ):
                return last_status
            time.sleep(1)
        return agent_contract(last_status, ok=False, error=f"等待超时: {until}")

    @mcp.tool()
    def jobseeker_logs(limit: int = 100, level: str = "", source: str = "", event_type: str = "") -> dict[str, Any]:
        """Return recent logs filtered by level, source, or event type."""
        from urllib.parse import urlencode

        params: dict[str, Any] = {"limit": limit}
        if level:
            params["level"] = level
        if source:
            params["source"] = source
        if event_type:
            params["type"] = event_type
        return _call("GET", "/agent/logs?" + urlencode(params))

    @mcp.tool()
    def jobseeker_history(limit: int = 100, offset: int = 0) -> dict[str, Any]:
        """Return recent job/action history."""
        from urllib.parse import urlencode

        return _call("GET", "/agent/history?" + urlencode({"limit": limit, "offset": offset}))

    mcp.run()
    return 0
