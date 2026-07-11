from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    greet_suggestion = "greet_suggestion"
    already_contacted = "already_contacted"


class JobAnalysis(BaseModel):
    total_score: int = Field(ge=0, le=100)
    skill_score: int = Field(ge=0, le=100)
    experience_score: int = Field(ge=0, le=100)
    industry_score: int = Field(ge=0, le=100)
    location_salary_score: int = Field(ge=0, le=100)
    education_score: int = Field(default=0, ge=0, le=100)
    other_score: int = Field(default=0, ge=0, le=100)
    risks: list[str] = Field(default_factory=list)
    recommendation: str = "wait_for_confirm"
    greeting: str = ""
    decision_source: str = "fast_llm"
    match_reason: str = ""
    blocked_reason: str = ""


class ResumeUpdate(BaseModel):
    markdown: str


class GreetingUpdate(BaseModel):
    content: str
    name: str = "默认话术"


class GreetingGenerateRequest(BaseModel):
    style: str = "default"


class ConfigUpdate(BaseModel):
    config: dict[str, Any]


class ScriptHeartbeat(BaseModel):
    page: str = "unknown"
    status: str = "idle"
    current_action: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


class JobAnalyzeRequest(BaseModel):
    title: str
    salary: str = ""
    detail: str
    company: str = ""
    url: str = ""
    city: str = ""
    talked: bool = False
    talked_reason: str = ""


class ActionCreate(BaseModel):
    action_type: str
    status: str = "pending"
    job_url: str = ""
    company: str = ""
    title: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class ActionDecision(BaseModel):
    note: str = ""


class ControlUpdate(BaseModel):
    command: str = Field(pattern="^(pause|resume|stop)$")
    new_run: bool = False


class EventCreate(BaseModel):
    type: str = "event"
    source: str = "script"
    level: str = "info"
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
