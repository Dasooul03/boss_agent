from __future__ import annotations

import json
import sys
from typing import Any

import database
import greeting_service
from cache import cache
from config import Config
from runtime_state import runtime_state


ALLOWED_CONFIG_FIELDS = {
    "score_threshold",
    "session_greet_limit",
    "log_verbosity",
    "skip_contacted_companies",
    "max_contacts_per_company",
    "job_detail_max_chars",
    "model_provider",
    "ollama_host",
    "openai_api_base",
    "think_model",
    "disable_model_thinking",
    "show_model_reasoning",
    "external_model_profile",
    "model_temperature",
    "model_top_p",
    "model_repeat_penalty",
    "model_repeat_last_n",
    "model_frequency_penalty",
    "model_presence_penalty",
}

DENIED_CONFIG_FIELDS = {
    "openai_api_key",
    "api_key",
    "resume",
    "resume_markdown",
    "markdown",
    "profile",
    "user_detail",
    "greeting",
    "greeting_content",
    "history",
    "actions",
    "database",
}


def print_json(payload: dict[str, Any]) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_tags(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "")


def normalize_config_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(payload or {})
    if isinstance(payload.get("config"), dict):
        merged = dict(payload["config"])
        for key, value in payload.items():
            if key != "config":
                merged[key] = value
        return merged
    return payload


def build_status_data() -> dict[str, Any]:
    cache.load()
    greeting = greeting_service.get_greeting()
    data = runtime_state.as_dict(cache.status(), cache.cache_status())
    data["greeting"] = {
        "confirmed": bool(greeting.get("confirmed")),
        "active_name": (greeting.get("active") or {}).get("name", "") if isinstance(greeting.get("active"), dict) else "",
    }
    contract = agent_contract(data)
    data["agent"] = {
        "ok": True,
        "ready": contract["ready"],
        "control": contract["control"],
        "run_id": contract["run_id"],
        "readiness": contract["readiness"],
        "missing_requirements": contract["missing_requirements"],
        "human_required": contract["human_required"],
        "next_action": contract["next_action"],
        "suggested_command": contract["suggested_command"],
        "last_error": contract["last_error"],
    }
    return data


def readiness_from_status(data: dict[str, Any]) -> dict[str, Any]:
    backend = data.get("backend") if isinstance(data.get("backend"), dict) else {}
    script = data.get("script") if isinstance(data.get("script"), dict) else {}
    resume = data.get("resume") if isinstance(data.get("resume"), dict) else {}
    cache_status = data.get("cache") if isinstance(data.get("cache"), dict) else {}
    greeting = data.get("greeting") if isinstance(data.get("greeting"), dict) else {}
    model = data.get("ollama") if isinstance(data.get("ollama"), dict) else data.get("model") or {}

    checks = {
        "resume_saved": bool(resume.get("saved")),
        "profile_generated": bool(cache_status.get("profile_generated")),
        "greeting_confirmed": bool(greeting.get("confirmed")),
        "script_connected": bool(script.get("connected")),
        "model_available": bool(model.get("available", True)),
    }
    if not model:
        checks["model_available"] = True

    requirements: list[dict[str, Any]] = []
    if not checks["resume_saved"]:
        requirements.append({
            "key": "resume_missing",
            "message": "简历尚未保存或确认",
            "human_required": True,
            "suggested_command": "python main.py",
        })
    if not checks["profile_generated"]:
        requirements.append({
            "key": "profile_missing",
            "message": "简历画像尚未生成或确认",
            "human_required": True,
            "suggested_command": "python main.py",
        })
    if not checks["greeting_confirmed"]:
        requirements.append({
            "key": "greeting_missing",
            "message": "打招呼话术尚未确认",
            "human_required": True,
            "suggested_command": "python main.py",
        })
    if not checks["script_connected"]:
        requirements.append({
            "key": "script_offline",
            "message": "油猴脚本未连接或心跳过期",
            "human_required": True,
            "suggested_command": "刷新 BOSS 搜索页后运行 python main.py agent wait --until script_online --timeout 120 --json",
        })
    if not checks["model_available"]:
        provider = model.get("provider") or (data.get("models") or {}).get("provider", "")
        key = "openai_api_key_missing" if provider == "openai" and not model.get("api_key_configured", True) else "model_unavailable"
        requirements.append({
            "key": key,
            "message": model.get("error") or "模型服务不可用",
            "human_required": True,
            "suggested_command": "python main.py",
        })

    ready = not requirements
    control = backend.get("control") or data.get("control", "")
    last_error = backend.get("last_error") or data.get("last_error", "")
    if requirements:
        next_action = {
            "resume_missing": "prepare_resume",
            "profile_missing": "generate_profile",
            "greeting_missing": "confirm_greeting",
            "script_offline": "refresh_boss_page",
            "openai_api_key_missing": "configure_model",
            "model_unavailable": "configure_model",
        }.get(requirements[0]["key"], "inspect_status")
        suggested_command = requirements[0]["suggested_command"]
    elif control in {"paused", "stopped", ""}:
        next_action = "start"
        suggested_command = "python main.py agent start --json"
    elif last_error:
        next_action = "inspect_logs"
        suggested_command = "python main.py agent logs --level error --json"
    else:
        next_action = "wait"
        suggested_command = "python main.py agent wait --until stopped --timeout 60 --json"

    return {
        "ready": ready,
        "checks": checks,
        "requirements": requirements,
        "missing_requirements": [item["key"] for item in requirements],
        "human_required": any(bool(item.get("human_required")) for item in requirements),
        "next_action": next_action,
        "suggested_command": suggested_command,
    }


def agent_contract(data: dict[str, Any] | None = None, *, ok: bool = True, error: str = "") -> dict[str, Any]:
    data = data or {}
    backend = data.get("backend") if isinstance(data.get("backend"), dict) else {}
    script = data.get("script") if isinstance(data.get("script"), dict) else {}
    script_detail = script.get("detail") if isinstance(script.get("detail"), dict) else {}
    model = data.get("ollama") if isinstance(data.get("ollama"), dict) else data.get("model") or {}
    readiness = readiness_from_status(data)
    run_id = backend.get("run_id") or data.get("run_id") or runtime_state.run_id
    return {
        "ok": ok,
        "ready": bool(readiness["ready"]),
        "control": backend.get("control") or data.get("control", ""),
        "run_id": run_id,
        "readiness": readiness,
        "missing_requirements": readiness["missing_requirements"],
        "human_required": bool(readiness["human_required"]),
        "next_action": readiness["next_action"] if ok else "inspect_error",
        "suggested_command": readiness["suggested_command"] if ok else "python main.py agent diagnose --json",
        "script": script,
        "model": model,
        "session": {
            "greet_count": script_detail.get("sessionGreetCount", 0),
            "greet_limit": script_detail.get("sessionGreetLimit", Config.session_greet_limit),
            "script_run_id": script_detail.get("runId", ""),
        },
        "last_error": error or backend.get("last_error") or data.get("last_error", ""),
        "data": data,
    }


def status_payload() -> dict[str, Any]:
    return agent_contract(build_status_data())


def diagnose_payload() -> dict[str, Any]:
    data = build_status_data()
    error_logs = [
        item for item in list(runtime_state.logs)
        if item.get("level") == "error"
    ][:10]
    data["diagnostics"] = {
        "recent_errors": error_logs,
        "agent_contract_version": "2026.07-agent-v1",
    }
    return agent_contract(data)


def configure_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    updates = normalize_config_payload(payload)
    denied = sorted(key for key in updates if key in DENIED_CONFIG_FIELDS)
    unknown = sorted(
        key for key in updates
        if key not in ALLOWED_CONFIG_FIELDS and key not in {"tags", "job_tags"} and key not in DENIED_CONFIG_FIELDS
    )
    if denied or unknown:
        data = build_status_data()
        data["configure"] = {
            "applied": {},
            "denied_fields": denied,
            "unknown_fields": unknown,
            "allowed_fields": sorted(ALLOWED_CONFIG_FIELDS | {"tags"}),
        }
        return agent_contract(data, ok=False, error="配置包含不允许 agent 写入的字段")

    applied: dict[str, Any] = {}
    config_updates = {key: value for key, value in updates.items() if key in ALLOWED_CONFIG_FIELDS}
    if config_updates:
        Config.save(config_updates)
        applied.update(config_updates)
    if "tags" in updates or "job_tags" in updates:
        cache.save_tags(_parse_tags(updates.get("tags", updates.get("job_tags"))))
        applied["tags"] = cache.tags
    cache.load()
    runtime_state.emit("agent_configured", "agent 已更新允许运行配置", source="agent", detail={"applied": applied})
    data = build_status_data()
    data["configure"] = {"applied": applied}
    return agent_contract(data)


def start_payload() -> dict[str, Any]:
    data = build_status_data()
    readiness = readiness_from_status(data)
    if not readiness["ready"]:
        data["start"] = {"started": False, "reason": "readiness_failed"}
        return agent_contract(data, ok=False, error="启动条件未满足")
    runtime_state.set_control("resume")
    data = build_status_data()
    data["start"] = {"started": True}
    return agent_contract(data)


def control_payload(command: str) -> dict[str, Any]:
    if command not in {"pause", "stop"}:
        return agent_contract(build_status_data(), ok=False, error=f"不支持的控制命令: {command}")
    runtime_state.set_control(command)
    data = build_status_data()
    data["control_result"] = runtime_state.control_payload()
    return agent_contract(data)


def logs_payload(limit: int = 100, level: str = "", source: str = "", event_type: str = "") -> dict[str, Any]:
    items = list(runtime_state.logs)
    if level:
        items = [item for item in items if item.get("level") == level]
    if source:
        items = [item for item in items if item.get("source") == source]
    if event_type:
        items = [item for item in items if item.get("type") == event_type]
    data = build_status_data()
    data["logs"] = items[:limit]
    return agent_contract(data)


def history_payload(limit: int = 100, offset: int = 0) -> dict[str, Any]:
    data = build_status_data()
    data["history"] = database.list_history(limit, offset)
    return agent_contract(data)


def actions_payload() -> dict[str, Any]:
    data = build_status_data()
    data["actions"] = database.list_pending_actions()
    return agent_contract(data)
