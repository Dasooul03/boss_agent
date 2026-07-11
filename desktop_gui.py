"""Native Tk desktop window for BossAgent while FastAPI stays available to Tampermonkey."""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from typing import Any, Callable

import greeting_service
import resume_service
from cache import cache
from config import Config
from runtime_state import runtime_state


def run_desktop(app: Any, shutdown_callback: Callable[[], None] | None = None) -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    import uvicorn

    Config.load()
    cache.load()
    server = uvicorn.Server(uvicorn.Config(
        app, host=Config.server_host, port=int(Config.server_port), log_config=None, access_log=False,
    ))
    threading.Thread(target=server.run, daemon=True, name="bossagent-api").start()

    root = tk.Tk()
    root.title("BossAgent")
    root.minsize(920, 650)
    root.configure(bg="#f5f7fb")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TNotebook", background="#f5f7fb", borderwidth=0)
    style.configure("TFrame", background="#ffffff")
    style.configure("TLabel", background="#ffffff", foreground="#172033")
    style.configure("Title.TLabel", font=("Microsoft YaHei", 18, "bold"), background="#f5f7fb")
    style.configure("Hint.TLabel", foreground="#64748b")

    header = ttk.Frame(root, padding=(20, 16))
    header.pack(fill="x")
    ttk.Label(header, text="BossAgent", style="Title.TLabel").pack(side="left")
    status_var = tk.StringVar(value="本地服务正在启动…")
    ttk.Label(header, textvariable=status_var, style="Hint.TLabel").pack(side="left", padx=16)
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=18, pady=(0, 18))

    def form_row(parent: Any, row: int, label: str, variable: tk.Variable, *, width: int = 34) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=6)
        ttk.Entry(parent, textvariable=variable, width=width).grid(row=row, column=1, sticky="ew", pady=6)

    def open_url(path: str) -> None:
        webbrowser.open(f"http://{Config.server_host}:{Config.server_port}{path}", new=2)

    # Dashboard
    dashboard = ttk.Frame(notebook, padding=20)
    notebook.add(dashboard, text="运行")
    ttk.Label(dashboard, text="自动化控制", font=("Microsoft YaHei", 14, "bold")).pack(anchor="w")
    ttk.Label(dashboard, text="桌面程序负责配置和控制；油猴通过同一台电脑上的本地 API 连接。", style="Hint.TLabel").pack(anchor="w", pady=(4, 16))
    controls = ttk.Frame(dashboard)
    controls.pack(anchor="w", pady=8)
    ttk.Button(controls, text="开始 / 继续", command=lambda: runtime_state.set_control("resume", new_run=True)).pack(side="left", padx=(0, 8))
    ttk.Button(controls, text="暂停", command=lambda: runtime_state.set_control("pause")).pack(side="left", padx=8)
    ttk.Button(controls, text="停止", command=lambda: runtime_state.set_control("stop")).pack(side="left", padx=8)
    ttk.Button(controls, text="安装 / 更新油猴脚本", command=lambda: open_url("/web_script.user.js")).pack(side="left", padx=8)
    ttk.Button(controls, text="打开 BOSS", command=lambda: webbrowser.open("https://www.zhipin.com/web/geek/job", new=2)).pack(side="left", padx=8)
    info = tk.Text(dashboard, height=20, wrap="word", state="disabled", bg="#f8fafc", relief="flat")
    info.pack(fill="both", expand=True, pady=(18, 0))

    # Settings
    settings = ttk.Frame(notebook, padding=20)
    notebook.add(settings, text="投递设置")
    settings.columnconfigure(1, weight=1)
    threshold = tk.StringVar(value=str(Config.score_threshold))
    limit = tk.StringVar(value=str(Config.session_greet_limit))
    delay = tk.StringVar(value=str(Config.action_delay_ms))
    target_roles = tk.StringVar(value=", ".join(getattr(Config, "job_filter_target_roles", [])))
    cities = tk.StringVar(value=", ".join(getattr(Config, "job_filter_cities", [])))
    employment = tk.StringVar(value=Config.job_filter_employment_type)
    scheduled = tk.BooleanVar(value=bool(Config.run_schedule_enabled))
    form_row(settings, 0, "评分阈值", threshold)
    form_row(settings, 1, "黄金时段目标上限", limit)
    form_row(settings, 2, "操作等待（毫秒）", delay)
    form_row(settings, 3, "目标岗位意图（语义匹配）", target_roles)
    form_row(settings, 4, "期望城市（逗号分隔）", cities)
    ttk.Label(settings, text="岗位类型").grid(row=5, column=0, sticky="w", pady=6)
    ttk.Combobox(settings, textvariable=employment, values=("any", "full_time", "internship"), state="readonly", width=31).grid(row=5, column=1, sticky="w", pady=6)
    ttk.Checkbutton(settings, text="仅在工作日 09:00–11:00、14:00–16:00 自动运行", variable=scheduled).grid(row=6, column=1, sticky="w", pady=8)

    def save_settings() -> None:
        try:
            Config.save({
                "score_threshold": int(threshold.get()), "session_greet_limit": int(limit.get()),
                "action_delay_ms": int(delay.get()), "job_filter_target_roles": split_terms(target_roles.get()),
                "job_filter_cities": split_terms(cities.get()), "job_filter_employment_type": employment.get(),
                "run_schedule_enabled": scheduled.get(),
            })
            messagebox.showinfo("BossAgent", "投递设置已保存")
        except ValueError:
            messagebox.showerror("BossAgent", "阈值、上限和等待时间必须是整数")
    ttk.Button(settings, text="保存设置", command=save_settings).grid(row=7, column=1, sticky="w", pady=12)

    # Resume and profile
    resume_tab = ttk.Frame(notebook, padding=20)
    notebook.add(resume_tab, text="简历与画像")
    ttk.Label(resume_tab, text="简历 Markdown").pack(anchor="w")
    resume_text = tk.Text(resume_tab, height=13, wrap="word")
    resume_text.pack(fill="both", expand=True, pady=(5, 8))
    resume_text.insert("1.0", cache.resume)
    tags = tk.StringVar(value=", ".join(cache.tags))
    ttk.Label(resume_tab, text="搜索标签（逗号分隔）").pack(anchor="w")
    ttk.Entry(resume_tab, textvariable=tags).pack(fill="x", pady=(4, 8))
    resume_controls = ttk.Frame(resume_tab)
    resume_controls.pack(anchor="w")

    def save_resume() -> None:
        resume_service.save_resume(resume_text.get("1.0", "end").strip())
        messagebox.showinfo("BossAgent", "简历已保存")
    def upload_pdf() -> None:
        path = filedialog.askopenfilename(filetypes=[("PDF 简历", "*.pdf")])
        if path:
            resume_service.upload_pdf(Path(path).name, Path(path).read_bytes())
            resume_text.delete("1.0", "end"); resume_text.insert("1.0", cache.resume)
            messagebox.showinfo("BossAgent", "PDF 已提取")
    def save_tags() -> None:
        cache.save_tags("\n".join(split_terms(tags.get())))
        messagebox.showinfo("BossAgent", "标签已保存")
    ttk.Button(resume_controls, text="保存简历", command=save_resume).pack(side="left", padx=(0, 8))
    ttk.Button(resume_controls, text="上传 PDF", command=upload_pdf).pack(side="left", padx=8)
    ttk.Button(resume_controls, text="保存标签", command=save_tags).pack(side="left", padx=8)

    # Greeting
    greeting_tab = ttk.Frame(notebook, padding=20)
    notebook.add(greeting_tab, text="打招呼话术")
    greeting = greeting_service.get_greeting()
    greeting_name = tk.StringVar(value=(greeting.get("active") or {}).get("name", "默认话术"))
    ttk.Label(greeting_tab, text="名称").pack(anchor="w")
    ttk.Entry(greeting_tab, textvariable=greeting_name).pack(fill="x", pady=(4, 8))
    ttk.Label(greeting_tab, text="话术").pack(anchor="w")
    greeting_text = tk.Text(greeting_tab, height=16, wrap="word")
    greeting_text.pack(fill="both", expand=True, pady=(4, 8))
    greeting_text.insert("1.0", greeting.get("active_content", ""))
    def save_greeting() -> None:
        greeting_service.save_greeting(greeting_text.get("1.0", "end").strip(), greeting_name.get() or "默认话术")
        messagebox.showinfo("BossAgent", "话术已启用")
    ttk.Button(greeting_tab, text="保存并启用", command=save_greeting).pack(anchor="w")

    def refresh_status() -> None:
        cache.load()
        script = runtime_state.script_snapshot()
        greeting_ready = greeting_service.get_greeting().get("confirmed", False)
        content = (
            f"控制状态：{runtime_state.control}\n"
            f"脚本连接：{'已连接' if script.get('connected') else '未连接'}\n"
            f"脚本页面：{script.get('page')} / {script.get('status')}\n"
            f"当前动作：{script.get('current_action') or '空闲'}\n\n"
            f"简历：{'已准备' if cache.resume.strip() else '未准备'}\n"
            f"画像：{'已生成' if cache.cache_status()['profile_generated'] else '未生成'}\n"
            f"话术：{'已启用' if greeting_ready else '未启用'}\n"
            f"当前本地地址：http://{Config.server_host}:{Config.server_port}\n\n"
            "如果油猴未连接，请点击“安装 / 更新油猴脚本”，在 Tampermonkey 页面点击更新，再刷新 BOSS 搜索页。"
        )
        status_var.set(f"服务运行中 · 油猴{'已连接' if script.get('connected') else '等待连接'}")
        info.configure(state="normal"); info.delete("1.0", "end"); info.insert("1.0", content); info.configure(state="disabled")
        root.after(2500, refresh_status)

    def close() -> None:
        server.should_exit = True
        if shutdown_callback:
            shutdown_callback()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.after(400, refresh_status)
    root.mainloop()
    return 0


def split_terms(value: str) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in value.replace("，", ",").split(",") if item.strip()))
