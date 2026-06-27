from __future__ import annotations

import os
import subprocess
import threading
import importlib.util
import json
import re
from getpass import getpass
from pathlib import Path
from typing import Any

import database
import greeting_service
import resume_service
from cache import cache
from config import CONFIG_WAS_MISSING, Config
from runtime_state import runtime_state
from tools import script_connect_hosts as build_script_connect_hosts


PREFIX = {
    "startup": "[启动]",
    "config": "[配置]",
    "service": "[服务]",
    "script": "[脚本]",
    "page": "[页面]",
    "job": "[职位]",
    "model": "[模型]",
    "decision": "[决策]",
    "confirm": "[确认]",
    "history": "[历史]",
    "error": "[错误]",
    "action": "[确认]",
    "control": "[控制]",
    "backend": "[系统]",
}

CLI_CONFIRM_ACTIONS = {
    "send_resume",
}

WEB_SCRIPT_PATH = Path(__file__).resolve().parent / "web_script.js"
SESSION_PREPARED = False

DETAIL_EVENT_TYPES = {
    "message_send_failed",
    "message_send_finished",
    "job_detail_failed",
    "job_detail_timeout",
    "job_detail_fetch_fallback_failed",
    "greet_failed",
    "greet_unavailable",
    "greet_entry_fallback",
    "broadcast_send_failed",
    "manual_intervention_required",
}

COMPACT_SCRIPT_STATUS_KEYWORDS = (
    "等待详情页回传",
    "暂停检查",
    "读取职位列表",
    "搜索关键词",
    "职位列表已处理完毕",
    "详情页已启动",
    "附件请求监听",
    "检查当前聊天页官方简历请求卡片",
)


def log_verbosity() -> str:
    value = str(getattr(Config, "log_verbosity", "compact"))
    return value if value in {"compact", "normal", "debug"} else "compact"


def prefix_for(event: dict[str, Any]) -> str:
    if event.get("level") == "error":
        return "[错误]"
    source = str(event.get("source", "backend"))
    event_type = str(event.get("type", ""))
    return PREFIX.get(source) or PREFIX.get(event_type) or "[系统]"


def compact_detail(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "..."
    if isinstance(value, str):
        return value if len(value) <= 180 else value[:177] + "..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        items = [compact_detail(item, depth + 1) for item in value[:4]]
        if len(value) > 4:
            items.append(f"... 共 {len(value)} 项")
        return items
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 12:
                result["..."] = f"共 {len(value)} 项"
                break
            result[str(key)] = compact_detail(item, depth + 1)
        return result
    return str(value)


def format_detail(event: dict[str, Any]) -> str:
    detail = event.get("detail") or {}
    if not detail:
        return ""
    event_type = str(event.get("type", ""))
    should_show = event.get("level") == "error" or event_type in DETAIL_EVENT_TYPES
    if not should_show:
        return ""
    text = json.dumps(compact_detail(detail), ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= 900 else text[:897] + "..."


def should_print_event(event: dict[str, Any], force: bool = False) -> bool:
    if force or log_verbosity() == "debug":
        return True
    if event.get("level") == "error":
        return True
    if log_verbosity() == "normal":
        return True
    event_type = str(event.get("type", ""))
    source = str(event.get("source", ""))
    message = str(event.get("message", ""))
    if source == "model" and event_type in {"model_started", "model_finished"}:
        return False
    if event_type == "script_status" and any(keyword in message for keyword in COMPACT_SCRIPT_STATUS_KEYWORDS):
        return False
    return True


def format_job_score_block(event: dict[str, Any]) -> str:
    if str(event.get("type", "")) != "job_analyzed":
        return ""
    detail = event.get("detail") or {}
    analysis = detail.get("analysis") or {}
    if not analysis:
        return ""
    education = analysis.get("education_score", 0)
    skill = analysis.get("skill_score", 0)
    experience = analysis.get("experience_score", 0)
    total = analysis.get("total_score", 0)
    recommendation = analysis.get("recommendation", "")
    reason = analysis.get("match_reason", "")
    lines = [
        f"[评分] 学历专业 {education} / 技术栈 {skill} / 项目经验 {experience} / 加权匹配度 {total}",
        f"[决策] {recommendation}",
    ]
    if reason and not str(reason).startswith("学历专业:"):
        lines.append(f"[原因] {reason}")
    return "\n".join(lines)


def print_event(event: dict[str, Any], force: bool = False) -> None:
    if not should_print_event(event, force=force):
        return
    time_part = str(event.get("time", ""))[11:19]
    print(f"\n{prefix_for(event)} {time_part} {event.get('message', '')}", flush=True)
    score_block = format_job_score_block(event)
    if score_block:
        print(score_block, flush=True)
    detail = format_detail(event)
    if detail:
        print(f"[详情] {detail}", flush=True)



def start_event_printer() -> None:
    queue = runtime_state.subscribe()

    def worker() -> None:
        while True:
            event = queue.get()
            print_event(event)

    threading.Thread(target=worker, daemon=True).start()


def start_api_server(app) -> uvicorn.Server:
    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        print("[错误] 缺少 Python 依赖 uvicorn，请先运行: pip install -r requirements.txt")
        raise SystemExit(1) from exc
    config = uvicorn.Config(
        app,
        host=Config.server_host,
        port=int(Config.server_port),
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    runtime_state.emit(
        "service_started",
        f"API 服务已启动: http://{Config.server_host}:{Config.server_port}",
        source="service",
    )
    return server


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def ask_bool(prompt: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{suffix}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "是", "1", "true"}


def ask_list(prompt: str, current: list[str]) -> list[str]:
    value = ask(prompt + "，多个用逗号分隔", ", ".join(current))
    return [item.strip() for item in value.split(",") if item.strip()]


def ask_api_key(current: str) -> str:
    if current and not ask_bool("是否更新 OpenAI API Key", False):
        return current
    return getpass("OpenAI API Key: ").strip()


def open_editor(path: Path, message: str = "打开编辑器确认文件", event_type: str = "file_edit") -> None:
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "notepad"
    runtime_state.emit(event_type, f"{message}: {path}", source="config")
    subprocess.run([editor, str(path)], check=False)
    input("保存并关闭编辑器后按回车继续...")


def configure_base() -> None:
    current = Config.as_dict()
    runtime_state.emit("config_start", "进入配置向导", source="config")
    model_provider = ask("模型来源 ollama/openai", current["model_provider"]).strip()
    if model_provider == "openai_compatible":
        model_provider = "openai"
    if model_provider not in {"ollama", "openai"}:
        print("模型来源无效，已使用 ollama。")
        model_provider = "ollama"
    updates = {
        "model_provider": model_provider,
        "ollama_host": ask("Ollama 地址", current["ollama_host"]),
        "openai_api_base": ask("OpenAI API 地址", current["openai_api_base"]),
        "openai_api_key": ask_api_key(str(current.get("openai_api_key", ""))) if model_provider == "openai" else current.get("openai_api_key", ""),
        "think_model": ask("模型名称", current["think_model"]),
        "server_port": int(ask("本地服务端口", str(current["server_port"]))),
        "score_threshold": int(ask("最低匹配度阈值", str(current["score_threshold"]))),
        "session_greet_limit": int(ask("本次最多打招呼数量", str(current["session_greet_limit"]))),
        "job_detail_max_chars": int(ask("职位描述传给模型的最大字数", str(current["job_detail_max_chars"]))),
        "log_verbosity": ask("日志模式 compact/normal/debug", str(current.get("log_verbosity", "compact"))),
        "disable_model_thinking": ask_bool("是否关闭模型思考", bool(current.get("disable_model_thinking", True))),
        "show_model_reasoning": ask_bool("是否显示模型思考过程", bool(current.get("show_model_reasoning", False))),
        "external_model_profile": ask("OpenAI 模型类型 generic/qwen/deepseek/doubao", str(current.get("external_model_profile", "generic"))),
    }
    Config.save(updates)
    runtime_state.emit("config_saved", "配置已保存", source="config", detail=Config.public_dict())


def ensure_resume() -> None:
    cache.load()
    if cache.resume.strip() and ask_bool("检测到已有简历，是否继续使用", True):
        runtime_state.emit("resume_ready", "继续使用已有简历", source="config")
        return
    while True:
        pdf_path = Path(ask("请输入 PDF 简历路径"))
        if pdf_path.exists() and pdf_path.suffix.lower() == ".pdf":
            data = resume_service.upload_pdf(pdf_path.name, pdf_path.read_bytes())
            runtime_state.emit("resume_extracted", "PDF 简历已提取", source="config")
            open_editor(Path(Config.resume_name), "打开编辑器确认简历", "resume_edit")
            cache.load()
            runtime_state.emit("resume_saved", f"简历已确认，长度 {len(cache.resume)} 字", source="config")
            return
        print("路径无效或不是 PDF，请重新输入。")


def ensure_profile() -> None:
    cache.load()
    if cache.cache_status()["profile_generated"] and ask_bool("检测到已有简历画像，是否继续使用", True):
        runtime_state.emit("profile_ready", "继续使用已有简历画像", source="config")
        return
    profile = cache.generate_profile()
    tags_path = cache.write_tags_file(profile.get("tags", []))
    open_editor(tags_path, "打开编辑器确认岗位搜索标签", "tags_edit")
    cache.save_tags(tags_path.read_text(encoding="utf-8"))
    runtime_state.emit("tags_saved", f"岗位标签已确认: {'、'.join(cache.tags)}", source="config")
    detail_path = cache.write_user_detail_file(profile.get("user_detail", ""))
    open_editor(detail_path, "打开编辑器确认用户详情", "profile_edit")
    cache.save_user_detail(detail_path.read_text(encoding="utf-8"))
    runtime_state.emit("profile_saved", f"用户详情已确认，长度 {len(cache.user_detail)} 字", source="config")


def edit_tags() -> None:
    cache.load()
    if not cache.tags:
        if not cache.resume.strip():
            print("[配置] 当前没有简历，无法生成岗位标签。")
            return
        profile = cache.generate_profile()
        cache.write_tags_file(profile.get("tags", []))
    tags_path = cache.write_tags_file()
    open_editor(tags_path, "打开编辑器编辑岗位搜索标签", "tags_edit")
    cache.save_tags(tags_path.read_text(encoding="utf-8"))
    print(f"[配置] 岗位标签已保存: {'、'.join(cache.tags)}")


def prepare_session_start(force: bool = False) -> bool:
    global SESSION_PREPARED
    if SESSION_PREPARED and runtime_state.control != "stopped" and not force:
        return True

    cache.load()
    if not cache.tags:
        if not cache.resume.strip():
            print("[配置] 当前没有简历，无法生成本轮岗位标签。")
            runtime_state.emit("session_prepare_failed", "当前没有简历，无法生成本轮岗位标签", source="config", level="error")
            return False
        profile = cache.generate_profile()
        cache.write_tags_file(profile.get("tags", []))

    tags_path = cache.write_tags_file()
    open_editor(tags_path, "打开编辑器确认本轮岗位搜索标签", "session_tags_edit")
    cache.save_tags(tags_path.read_text(encoding="utf-8"))
    if not cache.tags:
        print("[配置] 岗位标签为空，请至少保留一个搜索关键词。")
        runtime_state.emit("session_prepare_failed", "岗位标签为空，本轮未启动", source="config", level="error")
        return False

    while True:
        raw_limit = ask("本次最多打招呼数量", str(Config.session_greet_limit))
        try:
            limit = int(raw_limit)
        except ValueError:
            print("[配置] 请输入整数。")
            continue
        if limit <= 0:
            print("[配置] 本次最多打招呼数量必须大于 0。")
            continue
        break

    Config.save({"session_greet_limit": limit})
    SESSION_PREPARED = True
    runtime_state.emit(
        "session_config_saved",
        f"本轮设置已确认: 标签 {len(cache.tags)} 个 / 本次上限 {limit}",
        source="config",
        detail={"tags": cache.tags, "session_greet_limit": limit},
    )
    print(f"[配置] 本轮岗位标签: {'、'.join(cache.tags)}")
    print(f"[配置] 本次最多打招呼数量: {limit}")
    return True


def ensure_greeting() -> None:
    greeting = greeting_service.get_greeting()
    if greeting.get("confirmed") and ask_bool("检测到已有打招呼用语，是否继续使用", True):
        runtime_state.emit("greeting_ready", "继续使用已确认打招呼用语", source="config")
        return
    while True:
        draft = greeting_service.generate_greeting("default")
        print("\n[模型输出] 打招呼草稿：")
        print(draft["content"])
        if ask_bool("是否启用这条话术", True):
            greeting_service.save_greeting(draft["content"], "CLI 确认话术")
            return
        if ask_bool("是否手动输入话术", False):
            content = ask("请输入打招呼用语")
            greeting_service.save_greeting(content, "CLI 手动话术")
            return


def needs_initialization() -> bool:
    cache.load()
    greeting = greeting_service.get_greeting()
    return (
        CONFIG_WAS_MISSING
        or not cache.resume.strip()
        or not cache.cache_status()["profile_generated"]
        or not greeting.get("confirmed")
    )


def run_initialization() -> None:
    if not needs_initialization():
        runtime_state.emit("init_skip", "初始化已跳过", source="startup")
        return
    configure_base()
    ensure_resume()
    ensure_profile()
    ensure_greeting()
    print_summary()
    if ask_bool("确认以上配置并进入待启动状态", True):
        runtime_state.set_control("pause")
        print("[控制] 初始化完成。打开 BOSS 搜索页后输入 start 开始自动化。")
    else:
        runtime_state.set_control("pause")
        print("[控制] 已暂停。可输入 config/resume/greeting 调整配置。")


def print_summary() -> None:
    cache.load()
    greeting = greeting_service.get_greeting()
    print("\n[配置] 当前运行摘要")
    print(f"- 服务端口: {Config.server_port}")
    print(f"- 模型来源: {Config.model_provider}")
    if Config.model_provider == "openai":
        print(f"- OpenAI: {Config.openai_api_base} / Key: {'已配置' if Config.openai_api_key else '未配置'}")
    else:
        print(f"- Ollama: {Config.ollama_host}")
    print(f"- 模型: {Config.think_model}")
    if Config.model_provider == "openai":
        print(f"- OpenAI 模型类型: {Config.external_model_profile}")
    print(f"- 阈值/本次上限: {Config.score_threshold} / {Config.session_greet_limit}")
    print(
        f"- 日志模式: {Config.log_verbosity} / "
        f"模型思考: {'关闭' if Config.disable_model_thinking else '允许'} / "
        f"思考过程: {'显示' if Config.show_model_reasoning else '隐藏'}"
    )
    print(f"- 简历: {'已保存' if cache.resume.strip() else '未准备'}")
    print(f"- 画像: {'已生成' if cache.cache_status()['profile_generated'] else '未生成'}")
    print(f"- 用户详情: {'已确认' if cache.user_detail.strip() else '未确认'}")
    print(f"- 话术: {greeting.get('active_content', '')[:80]}")


def script_install_url() -> str:
    return f"http://{Config.server_host}:{Config.server_port}/web_script.user.js"


def read_script_versions() -> tuple[str, str]:
    if not WEB_SCRIPT_PATH.exists():
        return "未找到", "未找到"
    text = WEB_SCRIPT_PATH.read_text(encoding="utf-8")
    meta = re.search(r"//\s*@version\s+(.+)", text)
    runtime = re.search(r"scriptVersion:\s*'([^']+)'", text)
    return (
        meta.group(1).strip() if meta else "未知",
        runtime.group(1).strip() if runtime else "未知",
    )


def show_script_install() -> None:
    meta_version, runtime_version = read_script_versions()
    print("[脚本] 篡改猴安装/更新")
    print(f"- 安装地址: {script_install_url()}")
    print(f"- 元数据版本: {meta_version}")
    print(f"- 运行版本: {runtime_version}")
    print(f"- 需要 @connect: {', '.join(build_script_connect_hosts(script_install_url()))}")
    print("- 用法: 在浏览器打开安装地址，按篡改猴提示安装或更新，然后刷新 BOSS 搜索页。")
    print("- 验证: CLI 应显示脚本就绪，并且 status/doctor 中的脚本版本等于运行版本。")


def show_status() -> None:
    status = runtime_state.as_dict(cache.status(), cache.cache_status())
    print_summary()
    script = status["script"]
    connected = "在线" if script.get("connected") else ("心跳过期" if script.get("stale") else "离线")
    print(f"- 脚本: {connected} / {script['page']} / {script['status']} / {script['current_action'] or '空闲'}")
    if script.get("heartbeat_age_seconds") is not None:
        print(f"- 脚本心跳: {script.get('heartbeat_age_seconds')} 秒前")
    detail = script.get("detail") or {}
    if detail.get("version"):
        print(f"- 脚本版本: {detail.get('version')}")
    if detail.get("sessionGreetLimit") is not None:
        print(f"- 本轮打招呼: {detail.get('sessionGreetCount', 0)} / {detail.get('sessionGreetLimit')}")
    if not script.get("connected"):
        print("- 提示: 请打开或刷新 BOSS 搜索页，并确认油猴脚本已启用。")
    print(f"- 控制: {status['backend']['control']}")
    model_status = status["ollama"]
    print(f"- 模型服务状态: {'可用' if model_status.get('available') else '不可用'}")


def show_control_result(command: str) -> None:
    global SESSION_PREPARED
    if command == "resume" and (not SESSION_PREPARED or runtime_state.control == "stopped"):
        if not prepare_session_start(force=True):
            return
    runtime_state.set_control(command)
    if command == "stop":
        SESSION_PREPARED = False
    payload = runtime_state.control_payload()
    script = payload["script"]
    print(f"[控制] {payload['message']}")
    print(f"[控制] 当前状态: {payload['control']} / 任务: {payload['current_task']}")
    if script.get("connected"):
        print(
            f"[脚本] 在线: {script.get('page')} / {script.get('status')} / "
            f"{script.get('current_action') or '空闲'}"
        )
    elif script.get("stale"):
        print(
            f"[脚本] 心跳过期: {script.get('page')} / {script.get('status')} / "
            f"{script.get('current_action') or '空闲'}"
        )
        print("[脚本] 请刷新 BOSS 搜索页，确认 CLI 出现新的脚本心跳后再 start。")
    else:
        print("[脚本] 未连接。请打开或刷新 BOSS 搜索页，等待 CLI 出现脚本心跳后再 start。")


def handle_pending_action(action: dict[str, Any]) -> None:
    print("\n[确认] 有待确认动作")
    print(f"- ID: {action['id']}")
    print(f"- 类型: {action['action_type']}")
    print(f"- 公司/职位: {action.get('company') or '-'} / {action.get('title') or '-'}")
    payload = action.get("payload") or {}
    print("- 详情:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if ask_bool("是否批准", False):
        database.update_action(action["id"], "approved", "CLI 批准")
        runtime_state.emit("action_approved", f"动作已批准: {action['id']}", source="confirm")
    else:
        database.update_action(action["id"], "rejected", "CLI 拒绝")
        runtime_state.emit("action_rejected", f"动作已拒绝: {action['id']}", source="confirm")


def handle_pending_actions_once() -> None:
    actions = database.list_pending_actions()
    handled = 0
    for action in actions:
        if action["action_type"] in CLI_CONFIRM_ACTIONS:
            handle_pending_action(action)
            handled += 1
    if not actions:
        print("[确认] 当前无待确认动作。")
    elif handled == 0:
        print(f"[确认] 有 {len(actions)} 个待处理动作，但没有当前 CLI 可确认的动作。")


def show_history() -> None:
    history = database.list_history(20)
    jobs = history["jobs"]
    actions = history["actions"]
    if not jobs and not actions:
        print("[历史] 暂无历史记录。")
        return
    if jobs:
        print("[历史] 最近职位:")
        for job in jobs:
            print(
                f"- {job.get('company') or '-'} / {job.get('title') or '-'} / "
                f"{job.get('recommendation') or '-'} / {job.get('final_action') or '-'} / "
                f"{job.get('updated_at') or '-'}"
            )
    if actions:
        print("[历史] 最近动作:")
        for action in actions:
            print(
                f"- #{action.get('id')} {action.get('action_type')} / {action.get('status')} / "
                f"{action.get('company') or '-'} / {action.get('title') or '-'}"
            )


def show_logs(limit: int = 30) -> None:
    logs = list(runtime_state.logs)[:limit]
    if not logs:
        print("[日志] 暂无运行日志。")
        return
    for event in logs:
        print_event(event, force=True)


def show_doctor() -> None:
    print("[诊断] 本地环境")
    for package in ("fastapi", "uvicorn", "ollama", "pypdf", "multipart"):
        found = importlib.util.find_spec(package) is not None
        print(f"- Python 依赖 {package}: {'已安装' if found else '缺失'}")
    print(f"- API 地址: http://{Config.server_host}:{Config.server_port}")
    print(f"- 模型来源: {Config.model_provider}")
    if Config.model_provider == "openai":
        print(f"- OpenAI: {Config.openai_api_base}")
        print(f"- API Key: {'已配置' if Config.openai_api_key else '未配置'}")
    else:
        print(f"- Ollama 地址: {Config.ollama_host}")
    model_status = runtime_state.ollama_status()
    print(f"- 模型服务连接: {'可用' if model_status.get('available') else '不可用'}")
    if Config.model_provider == "ollama" and model_status.get("available"):
        installed = "已安装" if model_status.get("model_available") else "未在 Ollama 模型列表中"
        print(f"- 当前模型: {Config.think_model} / {installed}")
    if not model_status.get("available") and model_status.get("error"):
        print(f"  错误: {model_status['error']}")
    script = runtime_state.script_snapshot()
    state = "在线" if script.get("connected") else ("心跳过期" if script.get("stale") else "离线")
    print(f"- 油猴脚本: {state}")
    print(f"  页面/状态/动作: {script.get('page')} / {script.get('status')} / {script.get('current_action') or '空闲'}")
    if script.get("heartbeat_age_seconds") is not None:
        print(f"  最近心跳: {script.get('heartbeat_age_seconds')} 秒前")
    detail = script.get("detail") or {}
    if detail.get("version"):
        print(f"  版本/阈值: {detail.get('version')} / {detail.get('threshold') or '-'}")
    if script.get("stale"):
        print("- 建议: 刷新 BOSS 搜索页，等待 CLI 出现新的脚本心跳后再输入 start。")
    elif not script.get("connected"):
        print("- 建议: 打开或刷新 BOSS 搜索页，确认脚本头包含 @connect 127.0.0.1 和 @connect localhost。")
    greeting = greeting_service.get_greeting()
    cache.load()
    print(f"- 简历: {'已保存' if cache.resume.strip() else '未保存'}")
    print(f"- 简历画像: {'已生成' if cache.cache_status()['profile_generated'] else '未生成'}")
    print(f"- 用户详情: {'已确认' if cache.user_detail.strip() else '未确认'}")
    print(f"- 打招呼话术: {'已确认' if greeting.get('confirmed') else '未确认'}")


def show_help() -> None:
    print(
        """
可用命令:
  status        显示系统状态
  config        重新配置基础参数
  resume        重新上传/编辑简历
  tags          编辑岗位搜索标签
  greeting      重新生成并确认打招呼用语
  start         开始或继续运行
  pause         暂停运行
  stop          停止自动化
  actions       处理待确认动作
  history       显示最近历史
  logs          显示最近日志
  script        显示篡改猴脚本安装/更新地址
  doctor        检查依赖、Ollama 和油猴连接
  help          显示帮助
  quit          退出 CLI
""".strip()
    )


def command_loop() -> None:
    show_help()
    while True:
        command = input("\njob-seeker> ").strip().lower()
        if not command:
            continue
        if command == "status":
            show_status()
        elif command == "config":
            configure_base()
        elif command == "resume":
            ensure_resume()
        elif command == "tags":
            edit_tags()
        elif command == "greeting":
            ensure_greeting()
        elif command in {"start", "resume-run"}:
            show_control_result("resume")
        elif command == "pause":
            show_control_result("pause")
        elif command == "stop":
            show_control_result("stop")
        elif command == "actions":
            handle_pending_actions_once()
        elif command == "history":
            show_history()
        elif command == "logs":
            show_logs()
        elif command == "script":
            show_script_install()
        elif command == "doctor":
            show_doctor()
        elif command == "help":
            show_help()
        elif command in {"quit", "exit"}:
            runtime_state.emit("cli_exit", "CLI 已退出，API 线程将随进程停止", source="startup")
            return
        else:
            print("未知命令，输入 help 查看帮助。")


def run_cli(app) -> None:
    database.init_db()
    cache.load()
    start_event_printer()
    runtime_state.emit("cli_start", "Job Seeker CLI 启动", source="startup")
    run_initialization()
    start_api_server(app)
    command_loop()
