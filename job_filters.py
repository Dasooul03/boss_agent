"""Deterministic job filters evaluated before any model request.

These filters complement LLM scoring. They make explicit preferences cheap to
evaluate and keep jobs that clearly violate them out of the model queue.
"""

from __future__ import annotations

import re
from typing import Any

from config import Config


def _normalized_terms(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip().casefold() for item in value if str(item).strip()]


def _matches_any(value: str, terms: list[str]) -> bool:
    text = (value or "").casefold()
    return any(term in text for term in terms)


def salary_range_k(salary: str) -> tuple[float, float] | None:
    """Return the displayed monthly salary range in K, when BOSS exposes one."""
    range_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:[-~～至到])\s*(\d+(?:\.\d+)?)\s*[kK]",
        salary or "",
    )
    if range_match:
        low, high = (float(item) for item in range_match.groups())
        return min(low, high), max(low, high)
    values = [float(item) for item in re.findall(r"(\d+(?:\.\d+)?)\s*[kK]", salary or "")]
    if not values:
        return None
    low = values[0]
    high = values[1] if len(values) > 1 else low
    return min(low, high), max(low, high)


def is_internship(job: dict[str, Any]) -> bool:
    """Recognize common internship labels from the job information available to us."""
    text = f"{job.get('title', '')}\n{job.get('detail', '')}".casefold()
    return bool(re.search(r"实习|intern(?:ship)?|trainee", text, flags=re.IGNORECASE))


def blocked_reason(job: dict[str, Any]) -> str:
    """Return a user-facing skip reason, or an empty string when the job passes."""
    employment_type = str(getattr(Config, "job_filter_employment_type", "any"))
    internship = is_internship(job)
    if employment_type == "internship" and not internship:
        return "仅筛选实习岗位，当前职位未标记为实习"
    if employment_type == "full_time" and internship:
        return "仅筛选正式岗位，当前职位标记为实习"

    cities = _normalized_terms(getattr(Config, "job_filter_cities", []))
    if cities and not _matches_any(str(job.get("city", "")), cities):
        return f"城市不在期望范围: {job.get('city') or '未知'}"

    title_keywords = _normalized_terms(getattr(Config, "job_filter_title_keywords", []))
    if title_keywords and not _matches_any(str(job.get("title", "")), title_keywords):
        return f"职位名称未命中关键词: {job.get('title') or '未知'}"

    required_title_keywords = _normalized_terms(getattr(Config, "job_filter_required_title_keywords", []))
    if required_title_keywords and not _matches_any(str(job.get("title", "")), required_title_keywords):
        return f"职位标题未命中硬性关键词: {job.get('title') or '未知'}"

    blocked_companies = _normalized_terms(getattr(Config, "job_filter_blocked_companies", []))
    if blocked_companies and _matches_any(str(job.get("company", "")), blocked_companies):
        return f"公司在屏蔽列表中: {job.get('company') or '未知'}"

    salary_range = salary_range_k(str(job.get("salary", "")))
    minimum = float(getattr(Config, "job_filter_salary_min_k", 0) or 0)
    maximum = float(getattr(Config, "job_filter_salary_max_k", 0) or 0)
    if salary_range:
        low, high = salary_range
        if minimum > 0 and high < minimum:
            return f"薪资上限 {high:g}K 低于期望最低 {minimum:g}K"
        if maximum > 0 and low > maximum:
            return f"薪资下限 {low:g}K 高于期望最高 {maximum:g}K"
    return ""
