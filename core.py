"""
LLM-facing business logic.

The functions intentionally keep the original public names so the legacy
Tampermonkey script can keep working while the CLI uses richer APIs.
"""

from __future__ import annotations

from typing import Any

from config import Config
from model_stream import DEFAULT_MODEL_OPTIONS, stream_ollama_chat
from prompts import JOB_SCORE_BREAKDOWN, TAGS, USER_DETAIL
from schema import JobAnalysis
from tools import extract_llm_reply, redact_privacy


DEFAULT_OPTIONS = DEFAULT_MODEL_OPTIONS
SCORING_VERSION = "single_call_weighted_score"


def _stream_messages(
    label: str,
    messages: list[dict[str, str]],
    options: dict[str, Any] | None = None,
    model: str | None = None,
    format_schema: dict[str, Any] | None = None,
) -> str:
    return stream_ollama_chat(
        label,
        messages,
        options=options or DEFAULT_OPTIONS,
        model=model or Config.think_model,
        format_schema=format_schema,
    )


def _stream_chat(sys_prompt: str, prompt: str, options: dict[str, Any] | None = None, model: str | None = None, label: str = "模型调用") -> str:
    content = _stream_messages(
        label,
        [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt},
        ],
        options=options,
        model=model,
    )
    return extract_llm_reply(content)


def generate_tags(resume: str) -> list[str]:
    """获取匹配标签"""
    return [tag for tag in _stream_chat(TAGS, redact_privacy(resume), label="生成职位标签").split(" ") if tag]


def getTags(resume: str) -> list[str]:
    """Backward-compatible wrapper."""
    return generate_tags(resume)


def generate_user_detail(resume: str) -> str:
    """提取用于岗位匹配的用户详情。"""
    return _stream_chat(USER_DETAIL, redact_privacy(resume), label="生成用户详情")


def getUserDetail(resume: str) -> str:
    """Backward-compatible wrapper."""
    return generate_user_detail(resume)


def _clip_text(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    return text[:max_chars]


def _analysis_from_weighted_score(
    education_score: int,
    skill_score: int,
    experience_score: int,
    *,
    greeting: str = "",
    match_reason: str = "",
    risks: list[str] | None = None,
) -> dict[str, Any]:
    education_score = _clamp_score(education_score)
    skill_score = _clamp_score(skill_score)
    experience_score = _clamp_score(experience_score)
    weighted_score = skill_score * 0.5 + experience_score * 0.35 + education_score * 0.15
    total_score = int(weighted_score + 0.5)
    recommendation = "greet" if total_score >= int(Config.score_threshold) else "skip"
    reason = match_reason or (
        f"学历专业: {education_score} / 技术栈: {skill_score} / "
        f"项目经验: {experience_score} / 加权匹配度: {total_score}"
    )
    return JobAnalysis(
        total_score=total_score,
        skill_score=skill_score,
        experience_score=experience_score,
        industry_score=total_score,
        location_salary_score=total_score,
        education_score=education_score,
        other_score=total_score,
        risks=risks or [],
        recommendation=recommendation,
        greeting=greeting,
        decision_source="single_call_weighted_score",
        match_reason=reason,
        blocked_reason=reason if recommendation == "skip" else "",
    ).model_dump()


def _clamp_score(value: int) -> int:
    return max(0, min(100, int(value)))


def _parse_score_breakdown(reply: str) -> dict[str, int] | None:
    lines = [line.strip() for line in extract_llm_reply(reply).splitlines() if line.strip()]
    if len(lines) != 3:
        return None
    expected = {
        "学历专业": None,
        "技术栈": None,
        "项目经验": None,
    }
    for line in lines:
        if ":" in line:
            name, value = line.split(":", 1)
        elif "：" in line:
            name, value = line.split("：", 1)
        else:
            return None
        name = name.strip()
        value = value.strip()
        if name not in expected or not value.isdigit():
            return None
        score = int(value)
        if not 0 <= score <= 100:
            return None
        expected[name] = score
    if any(value is None for value in expected.values()):
        return None
    return {key: int(value) for key, value in expected.items()}


def calculate_job_score(job_text: str, user_detail: str) -> tuple[dict[str, int] | None, str]:
    """单次岗位评分：模型输出三项分数，系统负责加权。"""
    content = _stream_messages(
        "计算职位匹配度",
        [
            {"role": "system", "content": JOB_SCORE_BREAKDOWN},
            {
                "role": "user",
                "content": f"# 岗位详情\n{job_text}\n\n# 用户画像\n{redact_privacy(user_detail)}",
            },
        ],
        model=Config.think_model,
        options={"temperature": 0.2, "num_ctx": 4096, "num_predict": 256},
    )
    reply = extract_llm_reply(content)
    return _parse_score_breakdown(reply), reply


def analyze_job(
    job: dict[str, str],
    user_detail: str,
    greeting: str = "",
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """使用单分匹配度评分，保证打招呼主链路可用。"""
    job_text = (
        f"# 职位名称\n{job.get('title', '')}\n\n"
        f"# 公司\n{job.get('company', '')}\n\n"
        f"# 薪资范围\n{job.get('salary', '')}\n\n"
        f"# 城市\n{job.get('city', '')}\n\n"
        f"# 职位描述\n{_clip_text(job.get('detail', ''), int(Config.job_detail_max_chars))}"
    )
    try:
        scores, raw_reply = calculate_job_score(job_text, user_detail)
        if scores is None:
            summary = raw_reply.replace("\n", " ")[:180] or "模型没有返回内容"
            return _analysis_from_weighted_score(
                0,
                0,
                0,
                greeting=greeting,
                match_reason=f"模型评分格式错误，已跳过。模型原始输出: {summary}",
                risks=["模型评分格式错误"],
            )
        return _analysis_from_weighted_score(
            scores["学历专业"],
            scores["技术栈"],
            scores["项目经验"],
            greeting=greeting,
        )
    except Exception as exc:
        return _analysis_from_weighted_score(
            0,
            0,
            0,
            greeting=greeting,
            match_reason=f"岗位判断失败，已跳过: {exc}",
            risks=[str(exc)],
        )


def analyzeJob(
    job: dict[str, str],
    user_detail: str,
    greeting: str = "",
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Backward-compatible wrapper."""
    return analyze_job(job, user_detail, greeting, profile)
