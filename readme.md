# Job Seeker

Job Seeker 是一个本机运行的 BOSS 直聘辅助工具：Python/FastAPI 后端负责配置、模型评分、历史记录和控制状态，Tampermonkey 脚本负责在浏览器页面中读取岗位、打开详情页、发送已确认的话术。

项目现在保留两个入口：

- `start_job_seeker.bat`：人工启动器，进入 CLI，可配置、确认、编辑和排查。
- `start_job_seeker_auto.bat`：自动运行启动器，读取已有配置，打开浏览器页面，脚本连上后直接开始。

## 项目组成

- `main.py`：FastAPI 服务和启动入口。
- `cli_console.py`：人工 CLI 和自动运行模式。
- `web_script.js`：BOSS 页面里的 Tampermonkey 脚本。
- `core.py` / `model_stream.py`：模型调用和岗位评分。
- `cache.py` / `greeting_service.py`：简历画像、岗位标签、打招呼话术缓存。
- `database.py`：SQLite 历史、动作和事件记录。
- `scripts/start_job_seeker.ps1`：人工启动器脚本。
- `scripts/start_job_seeker_auto.ps1`：自动运行启动器脚本。

个人数据保存在 `data/`，包括配置、简历缓存、画像、话术和 SQLite 数据库。

## 安装

推荐使用项目内虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
```

如果使用 Ollama，先确认 Ollama 已启动，并已拉取配置中的模型，例如：

```powershell
ollama list
```

## 人工启动器

双击：

```text
start_job_seeker.bat
```

它会：

1. 检查 Python 依赖。
2. 启动本地 FastAPI 服务。
3. 打开油猴脚本安装/更新页。
4. 打开 BOSS 搜索页。
5. 进入 `job-seeker>` CLI。

常用命令：

```text
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
script        显示油猴脚本安装/更新地址
doctor        检查依赖、模型服务和油猴连接
help          显示帮助
quit          退出 CLI
```

人工 `start` 会打开编辑器确认本轮岗位标签，并询问本次最多打招呼数量。

## 自动运行启动器

双击：

```text
start_job_seeker_auto.bat
```

它不会进入交互确认流程，而是直接使用已有配置：

1. 检查依赖、端口和模型服务。
2. 自动补齐已有简历对应的画像、用户详情、岗位标签和打招呼话术。
3. 启动本地 API。
4. 打开油猴脚本安装/更新页和 BOSS 搜索页。
5. 等待油猴脚本心跳。
6. 脚本在线后自动开始运行。

自动运行模式不会凭空生成简历。如果没有已保存简历，它会暂停并提示你先使用人工启动器配置。

如果模型不可用、OpenAI API Key 缺失、Ollama 不通、油猴脚本离线、BOSS 未登录、出现验证码或平台风控，也会暂停并提示人工处理。

## 油猴脚本

安装/更新地址：

```text
http://127.0.0.1:33333/web_script.user.js
```

使用流程：

1. 通过 Tampermonkey 安装或更新脚本。
2. 登录 BOSS 直聘。
3. 打开搜索页：`https://www.zhipin.com/web/geek/job`
4. 保持本地后端窗口运行。

脚本会后台打开岗位详情页和聊天页，仍保持 `GM_openInTab(... active:false ...)`，不会故意抢焦点。

## 运行过程

主要链路：

1. 启动器启动本地 FastAPI 服务。
2. 浏览器脚本上报 `/script/heartbeat`。
3. 后端返回 `paused`、`running` 或 `stopped` 控制状态。
4. 脚本按岗位标签搜索职位。
5. 脚本读取职位列表，后台打开详情页。
6. 详情页把岗位信息提交到 `/jobs/analyze`。
7. 后端读取已确认用户画像和话术，调用模型评分。
8. 达到阈值且未触发历史/公司限制时，脚本打开聊天页并发送已确认话术。
9. 职位、动作、日志和错误写入 SQLite。

## HTTP API

人工 CLI 和油猴脚本使用这些本地接口：

- `GET /health`
- `GET /status`
- `GET /web_script.user.js`
- `POST /script/heartbeat`
- `POST /control`
- `POST /jobs/analyze`
- `GET /jobs/recent`
- `GET /tags`
- `GET /get-introduce`
- `GET /logs`
- `GET /events`
- `GET /history`
- `POST /actions`
- `GET /actions/pending`
- `POST /resume/profile/generate`
- `POST /greeting/generate`

项目不再提供 MCP 或 `python main.py agent ...` 入口。需要自动化时，请使用 `start_job_seeker_auto.bat`。

## 常见排查

### 33333 端口被占用

```powershell
netstat -ano | findstr :33333
taskkill /PID <PID> /F
```

### 脚本离线

- 确认 Tampermonkey 已启用。
- 打开安装地址重新安装/更新脚本。
- 刷新 BOSS 搜索页。
- 确认本地窗口仍在运行。

### 模型不可用

- Ollama 模式：确认 Ollama 已启动，且 `data/config.json` 中的模型存在于 `ollama list`。
- OpenAI 模式：确认 API base、API Key 和模型名正确。
- 可在人工 CLI 中运行 `doctor` 查看当前模型连接状态。

### 自动运行没有开始

自动运行模式只会在以下条件都满足时开始：

- 已保存简历。
- 已有或可自动生成画像、岗位标签、用户详情。
- 已有或可自动生成打招呼话术。
- 模型服务可用。
- 油猴脚本已连接。

缺少其中任一项时，窗口会打印原因，并保持安全暂停。

## 验证

```powershell
$files = Get-ChildItem -Path . -Filter *.py -File | ForEach-Object { $_.FullName }
.\.venv\Scripts\python.exe -m py_compile $files
node --check web_script.js
```

## 致谢与来源

本项目基于 [goodjobs](https://github.com/gbcdby/goodjobs) 修改和再发布，原作者为嘎嘣脆的贝爷。

原项目采用 MIT License。本仓库保留原作者版权声明，并对当前版本的修改部分增加 Chatbot-Zhou 的修改版权声明。
