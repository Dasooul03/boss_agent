from __future__ import annotations

import os
import subprocess
import threading
import importlib.util
import json
import re
import shutil
import time
import webbrowser
from getpass import getpass
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import urlopen

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

CLI_CONFIRM_ACTIONS: set[str] = {"greet_suggestion"}

WEB_SCRIPT_PATH = Path(__file__).resolve().parent / "web_script.js"
BOSS_SEARCH_URL = "https://www.zhipin.com/web/geek/job"
SESSION_PREPARED = False
BROWSER_OPEN_COOLDOWN_SECONDS = 60
DEFAULT_AUTORUN_OLLAMA_MODEL = "qwen3:1.7b"
OLLAMA_PULL_TIMEOUT_SECONDS = 1800

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


def ask_float(prompt: str, current: float) -> float:
    while True:
        value = ask(prompt, str(current)).strip()
        try:
            return float(value)
        except ValueError:
            print("[配置] 请输入数字。")


def ask_int(prompt: str, current: int) -> int:
    while True:
        value = ask(prompt, str(current)).strip()
        try:
            return int(value)
        except ValueError:
            print("[配置] 请输入整数。")


def ask_list(prompt: str, current: list[str]) -> list[str]:
    value = ask(prompt + "，多个用逗号分隔", ", ".join(current))
    return [item.strip() for item in value.split(",") if item.strip()]


def _ask_thinking(current: dict[str, Any]) -> bool:
    """询问是否关闭模型思考，提前告知策略再让用户选择。"""
    print("[提示] 评分任务输出简短（仅3个数字），推荐关闭思考以获得更快响应。")
    print("       关思考时评分令牌 {} / 开思考时 {}，系统支持3次自动重试。".format(
        current.get("job_score_num_predict_think_off", Config.job_score_num_predict_think_off),
        current.get("job_score_num_predict_think_on", Config.job_score_num_predict_think_on)))
    print("       标签/画像/打招呼默认遵循此全局设置；打招呼为空输出时会尝试一次开启思考兜底。")
    return ask_bool("是否关闭模型思考", bool(current.get("disable_model_thinking", True)))


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
        "server_port": ask_int("本地服务端口", int(current["server_port"])),
        "score_threshold": ask_int("最低匹配度阈值", int(current["score_threshold"])),
        "session_greet_limit": ask_int("本次最多打招呼数量", int(current["session_greet_limit"])),
        "job_detail_max_chars": ask_int("职位描述传给模型的最大字数", int(current["job_detail_max_chars"])),
        "log_verbosity": ask("日志模式 compact/normal/debug", str(current.get("log_verbosity", "compact"))),
        "disable_model_thinking": _ask_thinking(current),
        "show_model_reasoning": ask_bool("是否显示模型思考过程", bool(current.get("show_model_reasoning", False))),
        "external_model_profile": ask("OpenAI 模型类型 generic/qwen/deepseek/doubao", str(current.get("external_model_profile", "generic"))),
    }
    if ask_bool("是否配置高级模型参数", False):
        updates.update({
            "model_temperature": ask_float("temperature", float(current.get("model_temperature", 0.2))),
            "model_top_p": ask_float("top_p", float(current.get("model_top_p", 0.8))),
            "model_repeat_penalty": ask_float("Ollama repeat_penalty", float(current.get("model_repeat_penalty", 1.18))),
            "model_repeat_last_n": ask_int("Ollama repeat_last_n", int(current.get("model_repeat_last_n", 128))),
            "model_frequency_penalty": ask_float("OpenAI frequency_penalty", float(current.get("model_frequency_penalty", 0.3))),
            "model_presence_penalty": ask_float("OpenAI presence_penalty", float(current.get("model_presence_penalty", 0.1))),
        })
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


def edit_profile() -> None:
    """重新生成或手动编辑用户画像（不涉及标签）。"""
    from core import generate_user_detail

    cache.load()
    if not cache.resume.strip():
        print("[错误] 请先上传或保存简历（输入 resume 命令）")
        return
    print("[1] 重新从简历生成用户画像")
    print("[2] 手动编辑画像文件（data/cache/user_detail.md）")
    choice = input("  选择 [Enter 取消]: ").strip()
    if choice == "1":
        detail = generate_user_detail(cache.resume)
        path = cache.write_user_detail_file(detail)
        open_editor(path, "打开编辑器确认用户画像", "profile_edit")
        cache.save_user_detail(path.read_text(encoding="utf-8"))
        runtime_state.log(f"用户画像已重新生成，长度 {len(cache.user_detail)} 字", source="config")
    elif choice == "2":
        path = cache.write_user_detail_file()
        open_editor(path, "打开编辑器编辑用户画像", "profile_edit")
        cache.save_user_detail(path.read_text(encoding="utf-8"))
        runtime_state.log(f"用户画像已手动编辑，长度 {len(cache.user_detail)} 字", source="config")


def edit_session_settings() -> None:
    """修改本轮轮次设置：岗位标签 + 打招呼上限。"""
    cache.load()
    print("[轮次设置] 当前配置:")
    print(f"  岗位标签: {'、'.join(cache.tags) if cache.tags else '(空)'}")
    print(f"  打招呼上限: {Config.session_greet_limit}")
    print()
    print("[1] 修改岗位搜索标签")
    print("[2] 修改本次打招呼上限")
    choice = input("  选择 [Enter 取消]: ").strip()

    if choice == "1":
        edit_tags()
    elif choice == "2":
        while True:
            raw = ask("本次最多打招呼数量", str(Config.session_greet_limit))
            try:
                limit = int(raw)
            except ValueError:
                print("[配置] 请输入整数。")
                continue
            if limit <= 0:
                print("[配置] 本次最多打招呼数量必须大于 0。")
                continue
            break
        Config.save({"session_greet_limit": limit})
        runtime_state.emit(
            "session_limit_updated",
            f"打招呼上限调整为 {limit}",
            source="config",
        )
        print(f"[配置] 本次最多打招呼数量已更新为: {limit}")
    elif choice:
        print("[配置] 无效选择，已取消。")


def edit_tags() -> None:
    """重新生成或手动编辑岗位搜索标签。"""
    from core import generate_tags

    cache.load()
    if not cache.resume.strip():
        print("[错误] 请先上传或保存简历（输入 resume 命令）")
        return
    print("[1] 重新从简历生成岗位标签")
    print("[2] 手动编辑标签文件（data/cache/tags.txt）")
    choice = input("  选择 [Enter 取消]: ").strip()
    if choice == "1":
        tags = generate_tags(cache.resume)
        path = cache.write_tags_file(tags)
        open_editor(path, "打开编辑器确认岗位标签", "tags_edit")
        cache.save_tags(path.read_text(encoding="utf-8"))
        runtime_state.log(f"岗位标签已重新生成: {'、'.join(cache.tags)}", source="config")
    elif choice == "2":
        path = cache.write_tags_file()
        open_editor(path, "打开编辑器编辑岗位标签", "tags_edit")
        cache.save_tags(path.read_text(encoding="utf-8"))
        runtime_state.log(f"岗位标签已手动编辑: {'、'.join(cache.tags)}", source="config")


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
        from core import generate_tags

        try:
            generated_tags = generate_tags(cache.resume)
            cache.write_tags_file(generated_tags)
            cache.load()  # 重新加载以获取刚生成的标签
            runtime_state.emit(
                "tags_generated",
                f"岗位标签为空，已仅基于简历补齐标签: {'、'.join(cache.tags)}",
                source="config",
            )
        except Exception as exc:
            print(f"[配置] 自动生成岗位标签失败: {exc}。请先输入 tags 命令人工处理。")
            runtime_state.emit(
                "session_prepare_failed",
                f"自动生成岗位标签失败: {exc}",
                source="config",
                level="error",
            )
            return False

    if not cache.tags:
        print("[配置] 岗位标签为空，请先输入 tags 命令人工处理。")
        runtime_state.emit("session_prepare_failed", "岗位标签为空，本轮未启动，请先使用 tags 命令处理", source="config", level="error")
        return False

    limit = Config.session_greet_limit  # 直接使用已有配置，不再交互询问

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


def edit_greeting() -> None:
    """重新生成或手动编辑打招呼用语。"""
    print("[1] 重新生成打招呼用语")
    print("[2] 手动输入话术")
    choice = input("  选择 [Enter 取消]: ").strip()
    if choice == "1":
        style = "default"
        styles = ["简洁版", "热情版", "技术突出版", "业务匹配版"]
        print("  可选风格: " + " / ".join(f"[{i+1}] {s}" for i, s in enumerate(styles)))
        style_choice = input(f"  选择风格 [Enter=default]: ").strip()
        if style_choice.isdigit() and 1 <= int(style_choice) <= len(styles):
            style = styles[int(style_choice) - 1]
        draft = greeting_service.generate_greeting(style)
        print(f"\n[模型输出] 打招呼草稿 ({style})：")
        print(draft["content"])
        if ask_bool("是否启用这条话术", True):
            greeting_service.save_greeting(draft["content"], f"CLI {style}")
            return
        print("已取消，话术未更改。")
    elif choice == "2":
        content = ask("请输入打招呼用语（不含姓名、手机号等隐私信息）")
        if content.strip():
            greeting_service.save_greeting(content.strip(), "CLI 手动话术")
            print("[配置] 打招呼用语已保存。")
        else:
            print("[配置] 已取消。")


def ensure_greeting() -> None:
    greeting = greeting_service.get_greeting()
    if greeting.get("confirmed") and ask_bool("检测到已有打招呼用语，是否继续使用", True):
        runtime_state.emit("greeting_ready", "继续使用已确认打招呼用语", source="config")
        return
    edit_greeting()


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


def _ensure_model_warmup() -> None:
    """启动时执行一次模型预热检测，结果写入 runtime_state 缓存。"""
    from model_stream import model_warmup_check

    warmup = model_warmup_check()
    runtime_state.model_warmup.update(warmup)
    if warmup.get("status") == "ready":
        print(f"[预热] 模型连通性检查: {warmup['model']} ... OK ({warmup.get('latency_seconds', 0)}s)")
    else:
        print(f"[预热] 模型连通性检查: {warmup['model']} ... 失败 ({warmup.get('error', '未知')})")


def print_status_panel() -> None:
    """显示格式化的系统状态面板（读取缓存的预热结果，不重复检测）。"""
    from model_stream import model_warmup_check

    cache.load()
    greeting = greeting_service.get_greeting()

    # 使用缓存的预热结果；首次（unknown）则执行一次检测
    warmup = runtime_state.model_warmup
    if warmup.get("status") == "unknown":
        warmup = model_warmup_check()
        runtime_state.model_warmup.update(warmup)
    model_ok = warmup.get("status") == "ready"
    model_status = f"✓ 已连接 ({warmup.get('latency_seconds', 0)}s)" if model_ok else f"✗ 未连接: {warmup.get('error', '未知')}"
    resume_ok = bool(cache.resume.strip())
    profile_ok = cache.cache_status().get("profile_generated", False)
    greeting_ok = greeting.get("confirmed", False)
    script = runtime_state.script_snapshot()
    script_ok = script.get("connected", False)
    control = runtime_state.control

    scoring_think = "开启" if not Config.disable_model_thinking else "关闭"
    greeting_think = "开启" if not Config.disable_model_thinking else "关闭"
    model_label = f"{Config.think_model} ({Config.model_provider})"

    def _icon(ok: bool) -> str:
        return "✓" if ok else "○"

    panel = f"""
╔══════════════════════════════════════════════════════════════╗
║              Job Seeker 状态面板                              ║
╠══════════════════════════════════════════════════════════════╣
║  服务地址    http://{Config.server_host}:{Config.server_port:<45}║
║  脚本地址    http://{Config.server_host}:{Config.server_port}/web_script.user.js{' ' * (30 - len(str(Config.server_port)))}║
╠══════════════════════════════════════════════════════════════╣
║  模型        {model_label:<48}║
║  模型状态    {model_status:<48}║
║  思考模式    评分: {scoring_think:<6} │ 画像/标签: {scoring_think:<6} │ 打招呼: {greeting_think:<6}{' ' * 8}║
║  评分阈值    {Config.score_threshold}分 / 本次上限 {Config.session_greet_limit}{' ' * 30}║
║  评分令牌    关思考 {Config.job_score_num_predict_think_off} / 开思考 {Config.job_score_num_predict_think_on}{' ' * 18}║
║  温度/top_p  {Config.model_temperature} / {Config.model_top_p}{' ' * 38}║
╠══════════════════════════════════════════════════════════════╣
║  简历        {_icon(resume_ok)} {'已保存' if resume_ok else '未准备'}{' ' * 42}║
║  用户画像    {_icon(profile_ok)} {'已生成' if profile_ok else '未生成'}{' ' * 42}║
║  打招呼语    {_icon(greeting_ok)} {'已确认' if greeting_ok else '未确认'}{' ' * 42}║
╠══════════════════════════════════════════════════════════════╣
║  脚本连接    {_icon(script_ok)} {'已连接' if script_ok else '等待中...'}{' ' * 42}║
║  控制状态    {'▶ running' if control == 'running' else '⏸ ' + control}{' ' * 40}║
╚══════════════════════════════════════════════════════════════╝"""

    # 精简版（compact 日志模式下使用单行格式）
    if Config.log_verbosity == "compact":
        panel = f"""
┌──────────────────────────────────────────────────────────────┐
│  Job Seeker  v2026.07                                        │
│  {model_label} │ 评分思考: {scoring_think} │ 画像/标签: {scoring_think} │ 打招呼: {greeting_think} │ 阈值: {Config.score_threshold}分 │ 上限: {Config.session_greet_limit}  │
│  模型: {model_status[:50]} │ 评分令牌: {Config.job_score_num_predict_think_off}/{Config.job_score_num_predict_think_on} │
│  简历: {_icon(resume_ok)} 画像: {_icon(profile_ok)} 话术: {_icon(greeting_ok)} │ 脚本: {_icon(script_ok)} │ {control} │
└──────────────────────────────────────────────────────────────┘"""

    print(panel, flush=True)


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
    print(
        f"- 模型参数: temp={Config.model_temperature} / top_p={Config.model_top_p} / "
        f"repeat_penalty={Config.model_repeat_penalty} / repeat_last_n={Config.model_repeat_last_n} / "
        f"freq_penalty={Config.model_frequency_penalty} / presence_penalty={Config.model_presence_penalty}"
    )
    print(f"- 简历: {'已保存' if cache.resume.strip() else '未准备'}")
    print(f"- 画像: {'已生成' if cache.cache_status()['profile_generated'] else '未生成'}")
    print(f"- 用户详情: {'已确认' if cache.user_detail.strip() else '未确认'}")
    print(f"- 话术: {greeting.get('active_content', '')[:80]}")


def script_install_url() -> str:
    return f"http://{Config.server_host}:{Config.server_port}/web_script.user.js"


def api_health_url() -> str:
    return f"http://{Config.server_host}:{Config.server_port}/health"


def browser_open_stamp_path(name: str) -> Path:
    # Keep this in data/cache to match the PowerShell launchers.
    return Path(Config.tags_name).parent / f"browser_open_{name}.stamp"


def should_open_browser_page(name: str, cooldown_seconds: int = BROWSER_OPEN_COOLDOWN_SECONDS) -> bool:
    path = browser_open_stamp_path(name)
    now = time.time()
    try:
        if path.exists() and now - path.stat().st_mtime < cooldown_seconds:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(now), encoding="utf-8")
    except OSError:
        return True
    return True


def wait_for_api_ready(timeout_seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(api_health_url(), timeout=1.0) as response:
                if 200 <= response.status < 300:
                    return True
        except (OSError, URLError):
            time.sleep(0.5)
    return False


def show_startup_next_steps() -> None:
    print("\n[启动] 下一步:")
    print(f"  1. 确认油猴脚本已安装或更新: {script_install_url()}")
    print("  2. 刷新 BOSS 搜索页，等待 CLI 显示脚本就绪")
    print("  3. 输入 start，确认本轮岗位标签和本次打招呼上限后开始")


def show_autorun_next_steps() -> None:
    print("\n[启动] 自动运行模式")
    print(f"  1. 已尝试打开油猴脚本安装/更新页: {script_install_url()}")
    print("  2. 已尝试打开 BOSS 搜索页")
    print("  3. 等待油猴脚本心跳，脚本在线后自动开始运行")


def maybe_open_startup_pages(*, always_open_userscript: bool = False) -> None:
    """每次启动自动打开 BOSS 搜索页；脚本安装页按模式和冷却策略打开。"""
    if not wait_for_api_ready():
        print("[启动] 本地 API 未在限定时间内就绪，已跳过自动打开。")
        return
    # 每次启动都打开 BOSS 搜索页
    if should_open_browser_page("boss_search"):
        try:
            webbrowser.open(BOSS_SEARCH_URL, new=2)
            print("[启动] 已打开 BOSS 搜索页。")
        except Exception as exc:
            print(f"[启动] 打开 BOSS 搜索页失败: {exc}")
    else:
        print("[启动] 60 秒内已打开过 BOSS 搜索页，本次跳过自动打开。")
    if (always_open_userscript or CONFIG_WAS_MISSING) and should_open_browser_page("userscript"):
        try:
            webbrowser.open(script_install_url(), new=2)
            if always_open_userscript:
                print("[启动] 已打开脚本安装/更新页。")
            else:
                print("[启动] 首次运行，已打开脚本安装页（后续输入 script 命令可重新打开）。")
        except Exception as exc:
            print(f"[启动] 打开脚本安装页失败: {exc}")


def wait_for_script_ready(timeout_seconds: float = 120.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        script = runtime_state.script_snapshot()
        if script.get("connected"):
            return True
        time.sleep(1)
    return False


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
    url = script_install_url()
    print("[脚本] 篡改猴安装/更新")
    print(f"- 安装地址: {url}")
    print(f"- 元数据版本: {meta_version}")
    print(f"- 运行版本: {runtime_version}")
    print(f"- 需要 @connect: {', '.join(build_script_connect_hosts(url))}")
    print("- 用法: 在浏览器打开安装地址，按篡改猴提示安装或更新，然后刷新 BOSS 搜索页。")
    print("- 验证: CLI 应显示脚本就绪，并且 status/doctor 中的脚本版本等于运行版本。")
    try:
        webbrowser.open(url, new=2)
        print("- 已尝试在浏览器中打开安装地址。")
    except Exception as exc:
        print(f"- 自动打开失败: {exc}")


def show_status() -> None:
    print_status_panel()
    # 补充脚本会话细节（面板中已包含基本连接状态，这里追加会话计数和版本）
    detail = runtime_state.script_snapshot().get("detail") or {}
    if detail.get("sessionGreetLimit") is not None:
        print(f"  会话详情: 本轮 {detail.get('sessionGreetCount', 0)}/{detail.get('sessionGreetLimit')} | "
              f"脚本版本 {detail.get('version', '-')} | "
              f"会话ID {detail.get('localSessionRunId') or detail.get('runId') or '-'}")
    if not runtime_state.script_snapshot().get("connected"):
        print("  提示: 请打开或刷新 BOSS 搜索页，并确认油猴脚本已启用。")


def show_control_result(command: str) -> None:
    global SESSION_PREPARED
    new_run = command == "resume" and (not SESSION_PREPARED or runtime_state.control == "stopped")
    if new_run:
        if not prepare_session_start(force=True):
            return
    runtime_state.set_control(command, new_run=new_run)
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
    unsupported: list[dict[str, Any]] = []
    for action in actions:
        if action["action_type"] in CLI_CONFIRM_ACTIONS:
            handle_pending_action(action)
            handled += 1
        else:
            unsupported.append(action)
    if not actions:
        print("[确认] 当前无待确认动作。")
    elif handled == 0:
        print(f"[确认] 有 {len(actions)} 个待处理动作，但没有当前 CLI 可确认的动作。")
    if unsupported:
        print("[确认] 以下 pending 动作不支持在 CLI 中确认，仅展示供排查：")
        for action in unsupported:
            print(f"- #{action.get('id')} {action.get('action_type')} / {action.get('company') or '-'} / {action.get('title') or '-'}")


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
    print(
        f"- 模型参数: temp={Config.model_temperature} / top_p={Config.model_top_p} / "
        f"repeat_penalty={Config.model_repeat_penalty} / freq_penalty={Config.model_frequency_penalty}"
    )
    script = runtime_state.script_snapshot()
    state = "在线" if script.get("connected") else ("心跳过期" if script.get("stale") else "离线")
    print(f"- 油猴脚本: {state}")
    print(f"  页面/状态/动作: {script.get('page')} / {script.get('status')} / {script.get('current_action') or '空闲'}")
    if script.get("heartbeat_age_seconds") is not None:
        print(f"  最近心跳: {script.get('heartbeat_age_seconds')} 秒前")
    detail = script.get("detail") or {}
    if detail.get("version"):
        print(f"  版本/阈值: {detail.get('version')} / {detail.get('threshold') or '-'}")
    if detail:
        print(
            f"  运行标识: 后端 {runtime_state.run_id} / "
            f"脚本 {detail.get('localSessionRunId') or detail.get('runId') or '-'} / "
            f"脚本后端 {detail.get('backendRunId') or '-'}"
        )
        print(
            f"  本轮计数: {detail.get('sessionGreetCount', 0)} / "
            f"{detail.get('sessionGreetLimit') or Config.session_greet_limit} / "
            f"ended={detail.get('sessionEnded')}"
        )
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


def block_autorun(message: str, *, detail: dict[str, Any] | None = None, next_action: str = "") -> bool:
    runtime_state.set_control("pause")
    runtime_state.set_task("blocked")
    runtime_state.set_autorun_blocked(message, next_action)
    runtime_state.emit("autorun_blocked", message, source="startup", level="error", detail=detail or {})
    return False


def ensure_autorun_ollama_model() -> bool:
    status = runtime_state.ollama_status()
    if status.get("available") and status.get("model_available", True):
        return True
    if not status.get("available"):
        print(f"[模型] Ollama 服务不可用: {status.get('error') or '未知错误'}")
        return False
    models = set(status.get("models") or [])
    if Config.think_model != DEFAULT_AUTORUN_OLLAMA_MODEL or DEFAULT_AUTORUN_OLLAMA_MODEL not in models:
        print(f"[模型] 当前模型不可用: {Config.think_model}")
        print(f"[模型] 自动准备默认模型: {DEFAULT_AUTORUN_OLLAMA_MODEL}")
    if DEFAULT_AUTORUN_OLLAMA_MODEL not in models:
        ollama_exe = shutil.which("ollama")
        if not ollama_exe:
            print("[模型] 未找到 ollama 命令，无法自动下载模型。")
            return False
        try:
            result = subprocess.run(
                [ollama_exe, "pull", DEFAULT_AUTORUN_OLLAMA_MODEL],
                timeout=OLLAMA_PULL_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print(f"[模型] 下载默认模型超时（{OLLAMA_PULL_TIMEOUT_SECONDS} 秒），请稍后重试或手动运行: ollama pull {DEFAULT_AUTORUN_OLLAMA_MODEL}")
            return False
        if result.returncode != 0:
            print(f"[模型] 下载默认模型失败，退出码: {result.returncode}")
            return False
    Config.save(
        {
            "model_provider": "ollama",
            "think_model": DEFAULT_AUTORUN_OLLAMA_MODEL,
            "disable_model_thinking": True,
        }
    )
    runtime_state.emit(
        "autorun_model_ready",
        f"自动运行模型已设置为 {DEFAULT_AUTORUN_OLLAMA_MODEL}",
        source="startup",
        detail={"model": DEFAULT_AUTORUN_OLLAMA_MODEL},
    )
    status = runtime_state.ollama_status()
    if not status.get("available") or not status.get("model_available", True):
        print(f"[模型] 默认模型仍不可用: {status.get('error') or DEFAULT_AUTORUN_OLLAMA_MODEL}")
        return False
    return True


def model_ready_for_autorun() -> bool:
    status = runtime_state.ollama_status()
    if Config.model_provider == "openai" and not Config.openai_api_key:
        print("[模型] OpenAI API Key 未配置，请先运行人工启动器 config。")
        return False
    if Config.model_provider == "ollama":
        return ensure_autorun_ollama_model()
    if not status.get("available"):
        print(f"[模型] 模型服务不可用: {status.get('error') or '未知错误'}")
        return False
    return True


def auto_prepare_saved_configuration() -> bool:
    cache.load()
    if not cache.resume.strip():
        print("[配置] 未找到已保存简历。请先运行 start_job_seeker.bat 完成人工配置。")
        return block_autorun("未找到已保存简历，自动运行已暂停", next_action="运行 start_job_seeker.bat 配置简历")
    if not model_ready_for_autorun():
        return block_autorun(
            "模型配置不可用，自动运行已暂停",
            detail={"provider": Config.model_provider, "model": Config.think_model},
            next_action="检查 Ollama/OpenAI 配置后重启自动模式",
        )

    status = cache.cache_status()
    if not status["profile_generated"]:
        print("[配置] 缺少画像/标签/用户详情，正在用已配置模型自动生成...")
        try:
            profile = cache.generate_profile()
            if not profile.get("tags") or not profile.get("user_detail"):
                raise ValueError("模型未生成有效画像、标签或用户详情")
        except Exception as exc:
            print(f"[配置] 自动生成画像失败: {exc}")
            return block_autorun(f"自动生成画像失败: {exc}", next_action="运行人工启动器 profile 检查画像")

    greeting = greeting_service.get_greeting()
    if not greeting.get("confirmed"):
        print("[配置] 缺少打招呼话术，正在用已配置模型自动生成...")
        try:
            draft = greeting_service.generate_greeting("自动运行")
            greeting_service.save_greeting(draft["content"], "自动运行生成话术")
        except Exception as exc:
            print(f"[配置] 自动生成打招呼话术失败: {exc}")
            return block_autorun(f"自动生成打招呼话术失败: {exc}", next_action="运行人工启动器 greeting 确认话术")

    cache.load()
    if not cache.tags:
        print("[配置] 岗位标签为空。请先运行人工启动器 tags。")
        return block_autorun("岗位标签为空，自动运行已暂停", next_action="运行人工启动器 tags 配置岗位标签")
    runtime_state.emit(
        "autorun_config_ready",
        f"自动运行配置就绪: 标签 {len(cache.tags)} 个 / 本次上限 {Config.session_greet_limit}",
        source="startup",
        detail={"tags": cache.tags, "session_greet_limit": Config.session_greet_limit},
    )
    print(f"[配置] 自动运行将使用岗位标签: {'、'.join(cache.tags)}")
    print(f"[配置] 本次最多打招呼数量: {Config.session_greet_limit}")
    return True


def keep_process_alive() -> None:
    print("\n[运行] 自动运行中。关闭窗口或按 Ctrl+C 可停止本地服务。")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        runtime_state.set_control("stop")
        runtime_state.emit("autorun_exit", "自动运行已由用户中断", source="startup")


def show_help() -> None:
    print(
        """
可用命令:
  status        显示系统状态
  config        重新配置基础参数
  resume        重新上传/编辑简历
  profile       重新生成/编辑用户画像
  session       修改本轮轮次设置（岗位标签 / 打招呼上限）
  tags          重新生成/编辑岗位搜索标签
  greeting      重新生成/编辑打招呼用语
  start         开始或继续运行
  resume-run    start 的兼容别名
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
        elif command == "profile":
            edit_profile()
            print_status_panel()
        elif command == "session":
            edit_session_settings()
        elif command == "tags":
            edit_tags()
        elif command == "greeting":
            edit_greeting()
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


def run_cli(app, shutdown_callback: Callable[[], None] | None = None) -> None:
    database.init_db()
    cache.load()
    start_event_printer()
    runtime_state.emit("cli_start", "Job Seeker CLI 启动", source="startup")
    run_initialization()
    server = start_api_server(app)
    wait_for_api_ready()
    _ensure_model_warmup()
    print_status_panel()
    maybe_open_startup_pages()
    show_startup_next_steps()
    try:
        command_loop()
    except KeyboardInterrupt:
        print("\n[退出] 正在关闭服务…")
    finally:
        server.should_exit = True
        if shutdown_callback:
            shutdown_callback()
        print("[退出] 服务已关闭")


def run_autorun(app, shutdown_callback: Callable[[], None] | None = None) -> int:
    database.init_db()
    cache.load()
    start_event_printer()
    runtime_state.emit("autorun_start", "Job Seeker 自动运行启动", source="startup")
    server = start_api_server(app)

    def shutdown_autorun() -> None:
        server.should_exit = True
        if shutdown_callback:
            shutdown_callback()

    wait_for_api_ready()
    maybe_open_startup_pages(always_open_userscript=True)
    show_autorun_next_steps()
    if not auto_prepare_saved_configuration():
        print("[启动] 自动运行未开始，但本地服务会保持运行，方便查看 /status 和 /logs。")
        try:
            keep_process_alive()
        finally:
            shutdown_autorun()
        return 1
    _ensure_model_warmup()
    print_status_panel()
    print("[脚本] 等待油猴脚本连接，最长等待 120 秒...")
    if not wait_for_script_ready(120):
        block_autorun("油猴脚本未连接，自动运行已暂停", next_action="安装/更新油猴脚本，登录 BOSS 并刷新搜索页")
        print("[脚本] 油猴脚本未连接。请确认已安装/启用脚本、BOSS 已登录，并刷新搜索页。")
        if should_open_browser_page("userscript"):
            try:
                webbrowser.open(script_install_url(), new=2)
                print("[脚本] 已再次打开油猴脚本安装/更新页。")
            except Exception as exc:
                print(f"[脚本] 打开油猴脚本安装/更新页失败: {exc}")
        try:
            keep_process_alive()
        finally:
            shutdown_autorun()
        return 2
    runtime_state.set_control("resume", new_run=True)
    print("[控制] 脚本已连接，自动化已开始运行。")
    try:
        keep_process_alive()
    finally:
        shutdown_autorun()
    return 0
