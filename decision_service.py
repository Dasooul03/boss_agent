"""Single entry point for deterministic decisions before LLM scoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import database
from config import Config
from job_filters import blocked_reason as config_filter_reason


@dataclass(frozen=True)
class PreflightDecision:
    reason: str
    source: str
    final_action: str = ""


def evaluate_preflight(job: dict[str, Any], existing_job: dict[str, Any] | None) -> PreflightDecision | None:
    """Return a skip decision in business-priority order, or None for LLM scoring."""
    if job.get("talked"):
        return PreflightDecision(
            job.get("talked_reason") or "页面显示该职位已沟通，跳过重复联系",
            "page_contacted",
            "already_contacted",
        )

    reason = config_filter_reason(job)
    if reason:
        return PreflightDecision(reason, "config_filter")

    if not Config.skip_contacted_companies:
        return None
    if existing_job and existing_job.get("greeted"):
        return PreflightDecision("该职位已打过招呼，跳过重复联系", "history")
    if existing_job and recently_processed(existing_job):
        action = existing_job.get("final_action") or existing_job.get("recommendation") or "已处理"
        return PreflightDecision(f"该职位近期已处理，跳过重复打开: {action}", "history")
    company = job.get("company", "")
    if company and database.count_greeted_company(company) >= int(Config.max_contacts_per_company):
        return PreflightDecision(f"公司已达到联系上限: {company}", "company_limit")
    return None


def recently_processed(job: dict[str, Any], hours: int = 24) -> bool:
    updated_at = job.get("updated_at")
    if not updated_at:
        return False
    try:
        age_seconds = (datetime.now(timezone.utc) - datetime.fromisoformat(updated_at)).total_seconds()
    except (TypeError, ValueError):
        return False
    return age_seconds <= hours * 3600 and bool(job.get("recommendation") or job.get("final_action") or job.get("error"))
