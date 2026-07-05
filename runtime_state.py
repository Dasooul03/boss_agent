from __future__ import annotations

import json
import uuid
from collections import deque
from datetime import datetime, timezone
from queue import Queue
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import Config
from tools import now_iso


SCRIPT_STALE_SECONDS = 15


def _seconds_since(iso_time: str) -> int | None:
    try:
        return max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(iso_time)).total_seconds()))
    except (TypeError, ValueError):
        return None


class RuntimeState:
    def __init__(self) -> None:
        self.started_at = now_iso()
        self.run_id = self._new_run_id()
        self.current_task = "idle"
        self.control = "paused"
        self.last_error = ""
        self.script = {
            "connected": False,
            "page": "unknown",
            "status": "offline",
            "current_action": "",
            "last_seen": "",
            "stale": False,
            "heartbeat_age_seconds": None,
            "detail": {},
        }
        self.model_warmup = {
            "status": "unknown",
            "provider": "",
            "model": "",
            "last_checked": "",
            "latency_seconds": None,
            "error": "",
        }
        self.autorun = {
            "blocked": False,
            "reason": "",
            "next_action": "",
            "updated_at": "",
        }
        self.logs: deque[dict[str, Any]] = deque(maxlen=300)
        self.events: deque[dict[str, Any]] = deque(maxlen=500)
        self._subscribers: list[Queue] = []

    def _new_run_id(self) -> str:
        return f"run-{uuid.uuid4().hex[:12]}"

    def log(self, message: str, level: str = "info", source: str = "backend") -> dict[str, Any]:
        return self.emit("log", message, source=source, level=level)

    def emit(
        self,
        event_type: str,
        message: str,
        source: str = "backend",
        level: str = "info",
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = {
            "time": now_iso(),
            "run_id": self.run_id,
            "level": level,
            "source": source,
            "type": event_type,
            "message": message,
            "detail": detail or {},
        }
        self.logs.appendleft(item)
        self.events.appendleft(item)
        if level == "error":
            self.last_error = message
        for subscriber in list(self._subscribers):
            try:
                subscriber.put_nowait(item)
            except Exception:
                self._subscribers.remove(subscriber)
        try:
            import database

            database.create_event(item)
        except Exception:
            pass
        return item

    def subscribe(self) -> Queue:
        queue: Queue = Queue()
        self._subscribers.append(queue)
        return queue

    def set_task(self, task: str) -> None:
        self.current_task = task

    def update_script(self, page: str, status: str, current_action: str = "", detail: dict[str, Any] | None = None) -> None:
        previous = dict(self.script)
        detail = dict(detail or {})
        detail.setdefault("backendRunId", self.run_id)
        self.script = {
            "connected": True,
            "page": page,
            "status": status,
            "current_action": current_action,
            "last_seen": now_iso(),
            "stale": False,
            "heartbeat_age_seconds": 0,
            "detail": detail,
        }
        if (
            previous.get("page") != page
            or previous.get("status") != status
            or previous.get("current_action") != current_action
        ):
            self.emit(
                "script_status",
                f"脚本状态: {page} / {status} / {current_action or '空闲'}",
                source="script",
                detail=self.script,
            )

    def script_snapshot(self) -> dict[str, Any]:
        script = dict(self.script)
        script["detail"] = dict(script.get("detail") or {})
        last_seen = script.get("last_seen")
        script["stale"] = False
        if not last_seen:
            script["heartbeat_age_seconds"] = None
            return script
        age_seconds = _seconds_since(last_seen)
        if age_seconds is None:
            script["heartbeat_age_seconds"] = None
            return script
        script["heartbeat_age_seconds"] = age_seconds
        if script.get("connected") and age_seconds > SCRIPT_STALE_SECONDS:
            script["connected"] = False
            script["stale"] = True
            script["status"] = "stale"
            script["current_action"] = f"脚本心跳超过 {age_seconds} 秒未更新"
        return script

    def set_control(self, command: str, *, new_run: bool = False) -> None:
        if command == "pause":
            self.control = "paused"
            self.current_task = "paused"
        elif command == "resume":
            if new_run or self.control == "stopped" or not self.run_id:
                self.run_id = self._new_run_id()
            self.clear_autorun_blocked()
            self.control = "running"
            self.current_task = "idle"
        elif command == "stop":
            self.control = "stopped"
            self.current_task = "stopped"
        self.log(f"控制命令: {command}", source="control")

    def set_autorun_blocked(self, reason: str, next_action: str = "") -> None:
        self.autorun = {
            "blocked": True,
            "reason": reason,
            "next_action": next_action,
            "updated_at": now_iso(),
        }

    def clear_autorun_blocked(self) -> None:
        self.autorun = {
            "blocked": False,
            "reason": "",
            "next_action": "",
            "updated_at": now_iso(),
        }

    def control_payload(self) -> dict[str, Any]:
        should_start = self.control == "running"
        return {
            "control": self.control,
            "run_id": self.run_id,
            "current_task": self.current_task,
            "script": self.script_snapshot(),
            "should_start": should_start,
            "should_pause": self.control == "paused",
            "should_stop": self.control == "stopped",
            "message": {
                "running": "CLI 已允许脚本开始或继续执行",
                "paused": "CLI 已暂停脚本执行",
                "stopped": "CLI 已停止脚本执行",
            }.get(self.control, "未知控制状态"),
        }

    def update_model_warmup(
        self,
        status: str,
        *,
        provider: str = "",
        model: str = "",
        latency_seconds: float | None = None,
        error: str = "",
    ) -> None:
        self.model_warmup = {
            "status": status,
            "provider": provider,
            "model": model,
            "last_checked": now_iso(),
            "latency_seconds": latency_seconds,
            "error": error,
        }

    def ollama_status(self) -> dict[str, Any]:
        if Config.model_provider == "openai":
            return self.external_model_status()
        url = Config.ollama_host.rstrip("/") + "/api/tags"
        try:
            with urlopen(url, timeout=1.5) as response:
                data = response.read().decode("utf-8", errors="ignore")
            payload = json.loads(data)
            models = [
                item.get("name") or item.get("model")
                for item in payload.get("models", [])
                if isinstance(item, dict)
            ]
            return {
                "available": True,
                "provider": Config.model_provider,
                "host": Config.ollama_host,
                "model": Config.think_model,
                "models": models,
                "model_available": Config.think_model in models,
                "raw": data[:500],
            }
        except (json.JSONDecodeError, URLError, TimeoutError, OSError) as exc:
            return {
                "available": False,
                "provider": Config.model_provider,
                "host": Config.ollama_host,
                "model": Config.think_model,
                "error": str(exc),
            }

    def external_model_status(self) -> dict[str, Any]:
        result = {
            "available": False,
            "provider": Config.model_provider,
            "api_base": Config.openai_api_base,
            "api_key_configured": bool(str(Config.openai_api_key).strip()),
            "model": Config.think_model,
        }
        if not result["api_key_configured"]:
            result["error"] = "OpenAI API Key 未配置"
            return result
        url = Config.openai_api_base.rstrip("/") + "/models"
        request = Request(
            url,
            headers={"Authorization": f"Bearer {Config.openai_api_key}"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=3) as response:
                data = response.read().decode("utf-8", errors="ignore")
            result.update({"available": True, "raw": data[:500]})
            return result
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            result["error"] = f"HTTP {exc.code} {body[:300]}"
            return result
        except (URLError, TimeoutError, OSError) as exc:
            result["error"] = str(exc)
            return result

    def as_dict(self, resume_status: dict[str, Any], cache_status: dict[str, Any]) -> dict[str, Any]:
        model_thinking_disabled = bool(Config.disable_model_thinking)
        status = {
            "backend": {
                "running": True,
                "started_at": self.started_at,
                "run_id": self.run_id,
                "version": "2026.06-cli",
                "current_task": self.current_task,
                "control": self.control,
                "last_error": self.last_error,
            },
            "ollama": self.ollama_status(),
            "models": {
                "provider": Config.model_provider,
                "model": Config.think_model,
                "openai_api_base": Config.openai_api_base if Config.model_provider == "openai" else "",
                "openai_api_key_configured": bool(str(Config.openai_api_key).strip()),
                "disable_model_thinking": model_thinking_disabled,
                "show_model_reasoning": bool(Config.show_model_reasoning),
                "scoring_thinking": not model_thinking_disabled,
                "non_scoring_thinking": not model_thinking_disabled,
                "profile_tags_thinking": not model_thinking_disabled,
                "greeting_thinking": not model_thinking_disabled,
                "thinking_policy": {
                    "scoring": not model_thinking_disabled,
                    "profile_tags": not model_thinking_disabled,
                    "greeting": not model_thinking_disabled,
                },
                "external_model_profile": Config.external_model_profile if Config.model_provider == "openai" else "",
                "parameters": {
                    "temperature": Config.model_temperature,
                    "top_p": Config.model_top_p,
                    "repeat_penalty": Config.model_repeat_penalty,
                    "repeat_last_n": Config.model_repeat_last_n,
                    "frequency_penalty": Config.model_frequency_penalty,
                    "presence_penalty": Config.model_presence_penalty,
                },
                "warmup": dict(self.model_warmup),
            },
            "resume": resume_status,
            "cache": cache_status,
            "script": self.script_snapshot(),
            "autorun": dict(self.autorun),
        }
        return status


runtime_state = RuntimeState()
