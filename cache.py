from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import BASE_DIR, Config, ensure_data_dirs
from core import generate_tags, generate_user_detail
from runtime_state import runtime_state


class CacheManager:
    def __init__(self) -> None:
        self._resume = ""
        self._profile: dict[str, Any] = {}
        self.load()

    @property
    def resume(self) -> str:
        if not self._resume:
            self.load()
        return self._resume

    @property
    def user_detail(self) -> str:
        return str(self._profile.get("user_detail", ""))

    @property
    def tags(self) -> list[str]:
        tags_path = Path(Config.tags_name)
        if tags_path.exists():
            tags = self.parse_tags(tags_path.read_text(encoding="utf-8"))
            if tags:
                return tags
        tags = self._profile.get("tags", [])
        return tags if isinstance(tags, list) else []

    @property
    def profile(self) -> dict[str, Any]:
        profile = self._normalize_profile(self._profile)
        profile["tags"] = self.tags
        return profile

    def _normalize_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        tags = profile.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        return {
            "tags": [str(tag).strip() for tag in tags if str(tag).strip()],
            "user_detail": str(profile.get("user_detail", "")).strip(),
        }

    def parse_tags(self, content: str) -> list[str]:
        items = content.replace("，", "\n").replace(",", "\n").splitlines()
        tags: list[str] = []
        for item in items:
            for tag in str(item).split():
                tag = tag.strip()
                if tag and tag not in tags:
                    tags.append(tag)
        return tags

    def load(self) -> None:
        ensure_data_dirs()
        resume_path = Path(Config.resume_name)
        legacy_resume_path = BASE_DIR / "resume.md"
        if resume_path.exists():
            self._resume = resume_path.read_text(encoding="utf-8")
        elif legacy_resume_path.exists():
            self._resume = legacy_resume_path.read_text(encoding="utf-8")
        else:
            self._resume = ""

        profile_path = Path(Config.profile_cache_name)
        if profile_path.exists():
            try:
                data = json.loads(profile_path.read_text(encoding="utf-8"))
                self._profile = self._normalize_profile(data if isinstance(data, dict) else {})
                if data != self._profile:
                    profile_path.write_text(
                        json.dumps(self._profile, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            except json.JSONDecodeError:
                self._profile = {}
        else:
            self._profile = {}

    def save_resume(self, markdown: str) -> None:
        ensure_data_dirs()
        Path(Config.resume_name).write_text(markdown, encoding="utf-8")
        self._resume = markdown
        runtime_state.log("简历已保存")

    def generate_profile(self) -> dict[str, Any]:
        if not self.resume.strip():
            raise ValueError("请先上传或保存简历")
        runtime_state.set_task("generating_resume_profile")
        try:
            profile = {
                "tags": generate_tags(self.resume),
                "user_detail": generate_user_detail(self.resume),
            }
            self._save_profile(profile)
            self.write_tags_file(profile["tags"])
            self.write_user_detail_file(profile["user_detail"])
            runtime_state.log("简历画像已生成")
            return self.profile
        finally:
            runtime_state.set_task("idle")

    def _save_profile(self, profile: dict[str, Any]) -> None:
        profile = self._normalize_profile(profile)
        Path(Config.profile_cache_name).write_text(
            json.dumps(profile, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._profile = profile
        self.write_tags_file(profile["tags"])

    def write_tags_file(self, tags: list[str] | None = None) -> Path:
        ensure_data_dirs()
        path = Path(Config.tags_name)
        values = tags if tags is not None else self.tags
        path.write_text("\n".join(values).strip() + "\n", encoding="utf-8")
        return path

    def save_tags(self, content: str) -> dict[str, Any]:
        tags = self.parse_tags(content)
        if not tags:
            raise ValueError("岗位标签不能为空")
        profile = self.profile
        profile["tags"] = tags
        self._save_profile(profile)
        self.write_tags_file(tags)
        runtime_state.log("岗位标签已保存")
        return self.profile

    def write_user_detail_file(self, content: str | None = None) -> Path:
        ensure_data_dirs()
        path = Path(Config.user_detail_name)
        path.write_text((content if content is not None else self.user_detail).strip() + "\n", encoding="utf-8")
        return path

    def save_user_detail(self, content: str) -> dict[str, Any]:
        content = content.strip()
        if not content:
            raise ValueError("用户详情不能为空")
        profile = self.profile
        profile["user_detail"] = content
        self._save_profile(profile)
        self.write_user_detail_file(content)
        runtime_state.log("用户详情已保存")
        return self.profile

    def status(self) -> dict[str, Any]:
        resume_path = Path(Config.resume_name)
        legacy_resume_path = BASE_DIR / "resume.md"
        active_path = resume_path if resume_path.exists() else legacy_resume_path
        return {
            "uploaded": Path(Config.original_resume_pdf_name).exists(),
            "saved": bool(self.resume.strip()),
            "path": str(active_path) if active_path.exists() else "",
            "last_updated": active_path.stat().st_mtime if active_path.exists() else None,
            "extracted": Path(Config.extracted_resume_name).exists(),
        }

    def cache_status(self) -> dict[str, Any]:
        return {
            "profile_generated": bool(self.tags and self.user_detail.strip()),
            "tags_generated": bool(self.tags),
            "user_detail_generated": bool(self.user_detail.strip()),
        }


cache = CacheManager()
