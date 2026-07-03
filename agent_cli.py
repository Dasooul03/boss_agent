from __future__ import annotations

import argparse
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import Config
from agent_service import agent_contract, print_json


OLD_SERVICE_HINT = (
    "当前端口上的 Job Seeker 服务不支持 /agent 接口，可能是旧进程仍在运行。"
    "请先退出旧的 python main.py 窗口，然后重新启动 python main.py serve 或 start_job_seeker.bat。"
)


AGENT_COMMANDS = [
    "health",
    "status",
    "doctor",
    "diagnose",
    "configure",
    "start",
    "pause",
    "stop",
    "logs",
    "history",
    "actions",
    "wait",
]


def api_base_url() -> str:
    return f"http://{Config.server_host}:{Config.server_port}"


def request_api_json(method: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 5.0) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(api_base_url() + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="ignore")
        return json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        if exc.code == 404 and path.startswith("/agent/"):
            raise RuntimeError(OLD_SERVICE_HINT) from exc
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"无法连接 Job Seeker API: {exc}") from exc


def parse_value(value: str) -> Any:
    text = value.strip()
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def parse_config_updates(items: list[str], tags: str = "", config_json: str = "") -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if config_json:
        parsed = json.loads(config_json)
        if not isinstance(parsed, dict):
            raise ValueError("--config-json 必须是 JSON object")
        updates.update(parsed)
    for item in items:
        if "=" not in item:
            raise ValueError(f"--set 需要 key=value 格式: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"--set key 不能为空: {item}")
        updates[key] = parse_value(value)
    if tags:
        updates["tags"] = tags
    return updates


def run_agent_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python main.py agent")
    parser.add_argument("command", choices=AGENT_COMMANDS)
    parser.add_argument("--json", action="store_true", help="输出 JSON，agent 模式默认总是 JSON")
    parser.add_argument("--until", choices=["paused", "stopped", "running", "ready", "script_online"], default="script_online")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--level", default="")
    parser.add_argument("--source", default="")
    parser.add_argument("--type", dest="event_type", default="")
    parser.add_argument("--set", dest="config_items", action="append", default=[], help="agent configure 的 key=value")
    parser.add_argument("--tags", default="", help="agent configure 的岗位标签，支持逗号或换行分隔")
    parser.add_argument("--config-json", default="", help="agent configure 的 JSON object")
    args = parser.parse_args(argv)
    Config.load()
    try:
        if args.command == "health":
            health_data = request_api_json("GET", "/health")
            try:
                status_data = request_api_json("GET", "/agent/status")
                status_data["data"]["health"] = health_data
                print_json(status_data)
            except RuntimeError:
                print_json(agent_contract({"health": health_data}))
            return 0
        if args.command in {"doctor", "diagnose"}:
            payload = request_api_json("GET", "/agent/diagnose")
            print_json(payload)
            return 0 if payload.get("ok", False) else 1
        if args.command == "status":
            payload = request_api_json("GET", "/agent/status")
            print_json(payload)
            return 0 if payload.get("ok", False) else 1
        if args.command == "configure":
            updates = parse_config_updates(args.config_items, args.tags, args.config_json)
            payload = request_api_json("POST", "/agent/configure", updates)
            print_json(payload)
            return 0 if payload.get("ok", False) else 2
        if args.command in {"start", "pause", "stop"}:
            payload = request_api_json("POST", f"/agent/{args.command}")
            print_json(payload)
            return 0 if payload.get("ok", False) else 1
        if args.command == "logs":
            params: dict[str, Any] = {"limit": args.limit}
            if args.level:
                params["level"] = args.level
            if args.source:
                params["source"] = args.source
            if args.event_type:
                params["type"] = args.event_type
            print_json(request_api_json("GET", "/agent/logs?" + urlencode(params)))
            return 0
        if args.command == "history":
            print_json(request_api_json("GET", f"/agent/history?{urlencode({'limit': args.limit})}"))
            return 0
        if args.command == "actions":
            print_json(request_api_json("GET", "/agent/actions"))
            return 0
        if args.command == "wait":
            deadline = time.monotonic() + max(0.0, args.timeout)
            last_status: dict[str, Any] = {}
            while time.monotonic() <= deadline:
                try:
                    last_status = request_api_json("GET", "/agent/status", timeout=3.0)
                except RuntimeError as exc:
                    last_status = {"backend": {"last_error": str(exc)}}
                data = last_status.get("data") if isinstance(last_status.get("data"), dict) else last_status
                backend = data.get("backend") or {}
                script = last_status.get("script") or data.get("script") or {}
                if (
                    (args.until in {"paused", "stopped", "running"} and backend.get("control") == args.until)
                    or (args.until == "script_online" and script.get("connected"))
                    or (args.until == "ready" and last_status.get("ready"))
                ):
                    print_json(last_status if "ok" in last_status else agent_contract(last_status))
                    return 0
                time.sleep(1)
            print_json(agent_contract(last_status, ok=False, error=f"等待超时: {args.until}"))
            return 3
    except (RuntimeError, ValueError) as exc:
        print_json(agent_contract(ok=False, error=str(exc)))
        return 1
    return 2
