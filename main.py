"""Job Seeker local API used by the CLI controller and Tampermonkey script."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, File, HTTPException, Query, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import PlainTextResponse
except ModuleNotFoundError as exc:
    print("[错误] 缺少 Python 依赖，请先运行: pip install -r requirements.txt")
    raise SystemExit(1) from exc

import database
import greeting_service
import resume_service
from cache import cache
from config import Config
from core import SCORING_VERSION, analyze_job
from runtime_state import runtime_state
from schema import (
    ActionCreate,
    ActionDecision,
    ConfigUpdate,
    ControlUpdate,
    EventCreate,
    GreetingGenerateRequest,
    GreetingUpdate,
    JobAnalyzeRequest,
    ResumeUpdate,
    ScriptHeartbeat,
)
from tools import script_connect_hosts

BASE_DIR = Path(__file__).resolve().parent
WEB_SCRIPT_PATH = BASE_DIR / "web_script.js"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Config.load()
    database.init_db()
    cache.load()
    runtime_state.log("Job Seeker 服务已启动")
    runtime_state.log(f"岗位评分版本: {SCORING_VERSION}")
    yield


app = FastAPI(title="Job Seeker", version="2026.06-cli", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def fail(message: str, status_code: int = 400) -> None:
    runtime_state.log(message, level="error")
    raise HTTPException(status_code=status_code, detail=message)


def require_resume() -> str:
    if not cache.resume.strip():
        fail("请先在 CLI 中上传或保存简历")
    return cache.resume


def missing_profile_analysis(reason: str) -> dict[str, Any]:
    return {
        "total_score": 0,
        "skill_score": 0,
        "experience_score": 0,
        "industry_score": 0,
        "location_salary_score": 0,
        "education_score": 0,
        "other_score": 0,
        "risks": [reason],
        "recommendation": "skip",
        "greeting": "",
        "decision_source": "profile_missing",
        "match_reason": reason,
        "blocked_reason": reason,
    }


def script_base_url() -> str:
    return f"http://{Config.server_host}:{Config.server_port}"


def render_userscript() -> str:
    if not WEB_SCRIPT_PATH.exists():
        fail("web_script.js 不存在", 404)
    base_url = script_base_url()
    script = WEB_SCRIPT_PATH.read_text(encoding="utf-8")
    script = script.replace("http://127.0.0.1:33333/web_script.user.js", f"{base_url}/web_script.user.js")
    script = script.replace("serverHost: 'http://127.0.0.1:33333'", f"serverHost: '{base_url}'")
    lines = script.splitlines()
    connect_hosts = script_connect_hosts(base_url)
    rendered_lines: list[str] = []
    inserted_connect = False
    for line in lines:
        if line.startswith("// @connect"):
            if not inserted_connect:
                rendered_lines.extend(f"// @connect      {host}" for host in connect_hosts)
                inserted_connect = True
            continue
        rendered_lines.append(line)
    return "\n".join(rendered_lines) + ("\n" if script.endswith("\n") else "")


@app.get("/")
async def index():
    return {
        "message": "Job Seeker CLI API is running",
        "health": "/health",
        "status": "/status",
        "userscript": "/web_script.user.js",
    }


@app.get("/health", summary="轻量存活检查")
async def health():
    return {"ok": True, "version": app.version}


@app.get("/web_script.user.js", summary="安装或更新篡改猴脚本")
async def web_script_user_js():
    return PlainTextResponse(render_userscript(), media_type="application/javascript")


@app.get("/status", summary="系统状态")
async def status():
    cache.load()
    return runtime_state.as_dict(cache.status(), cache.cache_status())


@app.get("/config", summary="读取配置")
async def get_config():
    return {"config": Config.public_dict()}


@app.post("/config", summary="保存配置")
async def save_config(payload: ConfigUpdate):
    Config.save(payload.config)
    cache.load()
    runtime_state.log("配置已保存")
    return {"config": Config.public_dict()}


@app.post("/reload-resume", summary="重新加载简历")
async def reload_resume():
    cache.load()
    runtime_state.log("简历已重新加载")
    return resume_service.get_resume()


@app.get("/logs", summary="运行日志")
async def logs(limit: int = Query(100, ge=1, le=300)):
    return {"logs": list(runtime_state.logs)[:limit]}


@app.post("/events", summary="记录执行事件")
async def create_event(payload: EventCreate):
    event = runtime_state.emit(
        payload.type,
        payload.message,
        source=payload.source,
        level=payload.level,
        detail=payload.detail,
    )
    return event


@app.get("/events", summary="读取执行事件")
async def events(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return {"events": database.list_events(limit, offset)}


@app.post("/resume/upload-pdf", summary="上传 PDF 简历")
async def upload_resume_pdf(file: UploadFile = File(...)):
    content = await file.read()
    try:
        return resume_service.upload_pdf(file.filename or "resume.pdf", content)
    except Exception as exc:
        fail(str(exc))


@app.get("/resume", summary="读取简历")
async def get_resume():
    return resume_service.get_resume()


@app.put("/resume", summary="保存简历")
async def put_resume(payload: ResumeUpdate):
    return resume_service.save_resume(payload.markdown)


@app.post("/resume/profile/generate", summary="生成简历画像")
async def generate_resume_profile():
    try:
        return cache.generate_profile()
    except Exception as exc:
        runtime_state.set_task("idle")
        fail(str(exc))


@app.get("/resume/profile", summary="读取简历画像")
async def get_resume_profile():
    cache.load()
    return {
        "tags": cache.tags,
        "user_detail": cache.user_detail,
        "status": cache.cache_status(),
    }


@app.post("/greeting/generate", summary="生成打招呼草稿")
async def generate_greeting(payload: GreetingGenerateRequest):
    try:
        return greeting_service.generate_greeting(payload.style)
    except Exception as exc:
        runtime_state.set_task("idle")
        fail(str(exc))


@app.get("/greeting", summary="读取打招呼用语")
async def get_greeting():
    return greeting_service.get_greeting()


@app.put("/greeting", summary="保存打招呼用语")
async def put_greeting(payload: GreetingUpdate):
    try:
        return greeting_service.save_greeting(payload.content, payload.name)
    except Exception as exc:
        fail(str(exc))


@app.post("/greeting/variants", summary="生成多个打招呼变体")
async def greeting_variants():
    try:
        return greeting_service.generate_variants()
    except Exception as exc:
        runtime_state.set_task("idle")
        fail(str(exc))


@app.post("/script/heartbeat", summary="脚本心跳")
async def script_heartbeat(payload: ScriptHeartbeat):
    runtime_state.update_script(payload.page, payload.status, payload.current_action, payload.detail)
    if payload.status == "error":
        runtime_state.log(payload.current_action or "脚本上报错误", level="error", source="script")
    payload = runtime_state.control_payload()
    payload.update({"ok": True, "config": Config.public_dict()})
    return payload


@app.post("/control", summary="暂停/继续/停止")
async def control(payload: ControlUpdate):
    runtime_state.set_control(payload.command)
    return runtime_state.control_payload()


@app.post("/jobs/analyze", summary="结构化职位分析")
async def jobs_analyze(payload: JobAnalyzeRequest):
    cache.load()
    job = payload.model_dump()
    existing_job = database.get_job(job.get("url", ""))
    blocked_reason = blocked_by_history(job, existing_job) or blocked_by_config(job)
    if blocked_reason:
        analysis = {
            "total_score": 0,
            "skill_score": 0,
            "experience_score": 0,
            "industry_score": 0,
            "location_salary_score": 0,
            "education_score": 0,
            "other_score": 0,
            "risks": [blocked_reason],
            "recommendation": "skip",
            "greeting": "",
            "decision_source": "history_or_config",
            "match_reason": blocked_reason,
            "blocked_reason": blocked_reason,
        }
    elif not cache.user_detail.strip():
        analysis = missing_profile_analysis("请先生成并确认用户详情")
    else:
        greeting = greeting_service.get_greeting()
        confirmed_greeting = greeting["active_content"] if greeting.get("confirmed") else ""
        analysis = analyze_job(job, cache.user_detail, confirmed_greeting, cache.profile)
    final_action = "already_contacted" if job.get("talked") else ""
    saved_job = database.upsert_job(job, analysis, final_action=final_action)
    if job.get("talked"):
        saved_job = database.update_job_status(job.get("url", ""), final_action="already_contacted", greeted=True) or saved_job
    runtime_state.emit(
        "job_analyzed",
        f"职位已分析: {payload.company} {payload.title}",
        source="job",
        detail={"analysis": analysis, "job": job},
    )
    return {"analysis": analysis, "job": saved_job}


@app.post("/actions", summary="创建待执行动作")
async def create_action(payload: ActionCreate):
    action = database.create_action(payload.model_dump())
    if payload.action_type in {"greet", "send_greeting"} and payload.status in {"completed", "approved"}:
        database.update_job_status(payload.job_url, final_action="greeted", greeted=True)
    if payload.action_type == "already_contacted" and payload.status in {"completed", "approved"}:
        database.update_job_status(payload.job_url, final_action="already_contacted", greeted=True)
    if payload.action_type == "send_resume" and payload.status in {"completed", "approved"}:
        database.update_job_status(payload.job_url, final_action="resume_sent", resume_sent=True)
    runtime_state.log(f"动作已创建: {payload.action_type}", source="action")
    return action


@app.get("/actions/pending", summary="读取待确认动作")
async def pending_actions():
    return {"actions": database.list_pending_actions()}


@app.get("/actions/{action_id}", summary="读取动作")
async def get_action(action_id: int):
    action = database.get_action(action_id)
    if not action:
        fail("动作不存在", 404)
    return action


@app.post("/actions/{action_id}/approve", summary="批准动作")
async def approve_action(action_id: int, payload: ActionDecision):
    action = database.update_action(action_id, "approved", payload.note)
    runtime_state.log(f"动作已批准: {action_id}", source="action")
    return action


@app.post("/actions/{action_id}/reject", summary="拒绝动作")
async def reject_action(action_id: int, payload: ActionDecision):
    action = database.update_action(action_id, "rejected", payload.note)
    runtime_state.log(f"动作已拒绝: {action_id}", source="action")
    return action


@app.get("/history", summary="历史记录")
async def history(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return database.list_history(limit, offset)


@app.get("/tags", summary="获取职位标签")
async def get_tags():
    cache.load()
    return {"tags": cache.tags}


@app.get("/get-introduce", summary="获取已确认打招呼用语")
async def get_introduce():
    greeting = greeting_service.get_greeting()
    return {"introduce": greeting["active_content"] if greeting.get("confirmed") else ""}


def blocked_by_config(job: dict[str, Any]) -> str:
    company = job.get("company", "")
    title = job.get("title", "")
    detail = job.get("detail", "")
    city = job.get("city", "")
    text = f"{company}\n{title}\n{detail}\n{city}"
    for blocked_company in Config.blacklist_companies:
        if blocked_company and blocked_company in company:
            return f"公司命中黑名单: {blocked_company}"
    for keyword in Config.blacklist_keywords:
        if keyword and keyword in text:
            return f"职位命中黑名单关键词: {keyword}"
    if Config.target_cities and city and not any(target in city for target in Config.target_cities):
        return "城市不在目标城市范围"
    if Config.job_keywords and not any(keyword in text for keyword in Config.job_keywords):
        return "未命中目标岗位关键词"
    return ""


def blocked_by_history(job: dict[str, Any], existing_job: dict[str, Any] | None) -> str:
    if not Config.skip_contacted_companies:
        return ""
    if job.get("talked"):
        return job.get("talked_reason") or "页面显示该职位已沟通，跳过重复联系"
    if existing_job and existing_job.get("greeted"):
        return "该职位已打过招呼，跳过重复联系"
    company = job.get("company", "")
    if company and database.count_greeted_company(company) >= int(Config.max_contacts_per_company):
        return f"公司已达到联系上限: {company}"
    return ""


if __name__ == "__main__":
    from cli_console import run_cli

    run_cli(app)
