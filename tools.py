'''
Description: 工具
Author: Chatbot-Zhou
OriginalAuthor: 嘎嘣脆的贝爷
Date: 2025-02-14 22:31:43
LastEditTime: 2025-02-16 01:12:05
LastEditors: Chatbot-Zhou
'''
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_llm_reply(content: str) -> str:
    """获取大模型的最终回复，剥离常见 think 标签。"""
    text = content or ""
    if "<think>" in text:
        close_index = text.rfind("</think>")
        if close_index >= 0:
            text = text[close_index + len("</think>"):]
        else:
            text = text.split("<think>", 1)[0]
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def getLLMReply(content: str) -> str:
    """Backward-compatible wrapper."""
    return extract_llm_reply(content)


def extract_match_score(text: str) -> int | None:
    """从文本直接获取匹配度数值"""
    text = extract_llm_reply(text or "").strip()

    def valid(value: str) -> int | None:
        try:
            score = int(value)
        except ValueError:
            return None
        return score if 0 <= score <= 100 else None

    if re.fullmatch(r"\d{1,3}\s*分?", text):
        return valid(re.search(r"\d{1,3}", text).group())

    patterns = (
        r"(?:匹配度|匹配|综合评分|评分|分数|score)\D{0,16}(\d{1,3})\s*分?",
        r"(\d{1,3})\s*分",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            score = valid(match.group(1))
            if score is not None:
                return score

    numbers = re.findall(r"(?<![\d.-])(\d{1,3})(?!\s*[-~到至]\s*\d)(?![\d.])", text)
    scores = [score for value in numbers if (score := valid(value)) is not None]
    if len(scores) == 1:
        return scores[0]
    return None


def getMatchScore(text: str) -> int | None:
    """Backward-compatible wrapper."""
    return extract_match_score(text)


def script_connect_hosts(base_url: str) -> list[str]:
    hosts = ["127.0.0.1", "localhost"]
    parsed_host = urlparse(base_url).hostname
    if parsed_host and parsed_host not in hosts:
        hosts.append(parsed_host)
    return hosts


PRIVACY_PATTERNS = {
    "phone": r"(?<!\d)(?:1[3-9]\d{9})(?!\d)",
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "wechat": r"(?:微信|wechat|vx|VX|Vx)[:：\s]*[A-Za-z][-_A-Za-z0-9]{5,19}",
    "qq": r"(?:QQ|qq)[:：\s]*[1-9]\d{4,11}",
}


def detect_privacy(text: str) -> list[dict[str, Any]]:
    """Detect privacy-sensitive fragments without returning excessive context."""
    findings: list[dict[str, Any]] = []
    for kind, pattern in PRIVACY_PATTERNS.items():
        for match in re.finditer(pattern, text or ""):
            value = match.group(0)
            findings.append({
                "kind": kind,
                "value": value,
                "start": match.start(),
                "end": match.end(),
            })
    return findings


def redact_privacy(text: str) -> str:
    result = text or ""
    for kind, pattern in PRIVACY_PATTERNS.items():
        result = re.sub(pattern, f"[已隐藏{kind}]", result)
    return result
