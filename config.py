"""
Application configuration.

The class keeps the old ``Config.think_model`` style access so existing code can
continue to import it, while the values now live in ``data/config.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RESUME_DIR = DATA_DIR / "resume"
CACHE_DIR = DATA_DIR / "cache"
CONFIG_PATH = DATA_DIR / "config.json"
CONFIG_WAS_MISSING = not CONFIG_PATH.exists()


DEFAULT_CONFIG: dict[str, Any] = {
    "server_host": "127.0.0.1",
    "server_port": 33333,
    "model_provider": "ollama",
    "ollama_host": "http://127.0.0.1:11434",
    "openai_api_base": "https://api.openai.com/v1",
    "openai_api_key": "",
    "think_model": "qwen3:4b",
    "score_threshold": 70,
    "session_greet_limit": 50,
    "max_contacts_per_company": 1,
    "skip_contacted_companies": True,
    "job_detail_max_chars": 1600,
    "log_verbosity": "compact",
    "disable_model_thinking": True,
    "show_model_reasoning": False,
    "external_model_profile": "generic",
}


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "是", "显示"}
    return bool(value)


def _detect_external_model_profile(data: dict[str, Any]) -> str:
    profile = str(data.get("external_model_profile") or "generic").strip().lower()
    if profile and profile != "generic":
        return profile
    text = f"{data.get('openai_api_base', '')} {data.get('think_model', '')}".lower()
    if "ark.cn" in text or "volces" in text or "doubao" in text:
        return "doubao"
    if "dashscope" in text or "qwen" in text or "通义" in text:
        return "qwen"
    if "deepseek" in text:
        return "deepseek"
    return "generic"


class Config:
    resume_name = str(RESUME_DIR / "resume.md")
    extracted_resume_name = str(RESUME_DIR / "extracted.txt")
    original_resume_pdf_name = str(RESUME_DIR / "original.pdf")
    profile_cache_name = str(CACHE_DIR / "profile.json")
    user_detail_name = str(CACHE_DIR / "user_detail.md")
    tags_name = str(CACHE_DIR / "tags.txt")
    greeting_cache_name = str(CACHE_DIR / "greeting.json")
    app_db_name = str(DATA_DIR / "app.db")

    server_host = DEFAULT_CONFIG["server_host"]
    server_port = DEFAULT_CONFIG["server_port"]
    model_provider = DEFAULT_CONFIG["model_provider"]
    ollama_host = DEFAULT_CONFIG["ollama_host"]
    openai_api_base = DEFAULT_CONFIG["openai_api_base"]
    openai_api_key = DEFAULT_CONFIG["openai_api_key"]
    think_model = DEFAULT_CONFIG["think_model"]
    score_threshold = DEFAULT_CONFIG["score_threshold"]
    session_greet_limit = DEFAULT_CONFIG["session_greet_limit"]
    max_contacts_per_company = DEFAULT_CONFIG["max_contacts_per_company"]
    skip_contacted_companies = DEFAULT_CONFIG["skip_contacted_companies"]
    job_detail_max_chars = DEFAULT_CONFIG["job_detail_max_chars"]
    log_verbosity = DEFAULT_CONFIG["log_verbosity"]
    disable_model_thinking = DEFAULT_CONFIG["disable_model_thinking"]
    show_model_reasoning = DEFAULT_CONFIG["show_model_reasoning"]
    external_model_profile = DEFAULT_CONFIG["external_model_profile"]

    @classmethod
    def load(cls) -> dict[str, Any]:
        ensure_data_dirs()
        data = dict(DEFAULT_CONFIG)
        should_rewrite = False
        if CONFIG_PATH.exists():
            try:
                saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    if not saved.get("think_model") and saved.get("chat_model"):
                        saved["think_model"] = saved.get("chat_model")
                        should_rewrite = True
                    if saved.get("model_provider") == "openai_compatible":
                        saved["model_provider"] = "openai"
                        should_rewrite = True
                    if "daily_greet_limit" in saved and "session_greet_limit" not in saved:
                        saved["session_greet_limit"] = saved.get("daily_greet_limit")
                        should_rewrite = True
                    if any(key not in DEFAULT_CONFIG for key in saved):
                        should_rewrite = True
                    if any(key not in saved for key in DEFAULT_CONFIG):
                        should_rewrite = True
                    data.update({k: v for k, v in saved.items() if k in DEFAULT_CONFIG})
            except json.JSONDecodeError:
                pass
        cls.apply(data)
        if not CONFIG_PATH.exists() or should_rewrite:
            cls.save(data)
        return cls.as_dict()

    @classmethod
    def apply(cls, data: dict[str, Any]) -> None:
        data = dict(data)
        if data.get("model_provider") == "openai_compatible":
            data["model_provider"] = "openai"
        if data.get("model_provider") not in {"ollama", "openai"}:
            data["model_provider"] = DEFAULT_CONFIG["model_provider"]
        if data.get("log_verbosity") not in {"compact", "normal", "debug"}:
            data["log_verbosity"] = DEFAULT_CONFIG["log_verbosity"]
        data["external_model_profile"] = _detect_external_model_profile(data)
        if data.get("external_model_profile") not in {"generic", "qwen", "deepseek", "doubao"}:
            data["external_model_profile"] = DEFAULT_CONFIG["external_model_profile"]
        data["disable_model_thinking"] = _as_bool(data.get("disable_model_thinking"))
        data["show_model_reasoning"] = _as_bool(data.get("show_model_reasoning"))
        for key in DEFAULT_CONFIG:
            setattr(cls, key, data.get(key, DEFAULT_CONFIG[key]))

    @classmethod
    def as_dict(cls) -> dict[str, Any]:
        return {key: getattr(cls, key) for key in DEFAULT_CONFIG}

    @classmethod
    def public_dict(cls) -> dict[str, Any]:
        data = cls.as_dict()
        key = str(data.get("openai_api_key", ""))
        if key:
            data["openai_api_key"] = f"已配置(...{key[-4:]})" if len(key) > 4 else "已配置"
        else:
            data["openai_api_key"] = ""
        data["openai_api_key_configured"] = bool(key)
        return data

    @classmethod
    def save(cls, updates: dict[str, Any]) -> dict[str, Any]:
        ensure_data_dirs()
        updates = dict(updates)
        if "daily_greet_limit" in updates and "session_greet_limit" not in updates:
            updates["session_greet_limit"] = updates.get("daily_greet_limit")
        current = cls.as_dict()
        current.update({k: v for k, v in updates.items() if k in DEFAULT_CONFIG})
        cls.apply(current)
        current = cls.as_dict()
        CONFIG_PATH.write_text(
            json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return cls.as_dict()


Config.load()
