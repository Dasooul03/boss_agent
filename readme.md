# Job Seeker

Job Seeker 是一个本地运行的 AI 求职助手。它同时面向两类使用者：

- 人工用户：通过命令行控制台完成初始化、确认简历/画像/话术、查看日志、启动或暂停自动化。
- Agent 用户：通过稳定 JSON CLI、HTTP API 或 MCP 工具读取状态、诊断问题、调整安全配置、启动或停止流程。

项目默认只在本机运行：

```text
http://127.0.0.1:33333
```

## 项目组成

- `main.py`：FastAPI 服务入口、人工 CLI 入口、agent/MCP 入口。
- `cli_console.py`：人工命令行控制台。
- `agent_cli.py`：Hermes、OpenClaw 等 agent 调用的 JSON CLI。
- `agent_service.py`：统一 agent 契约、readiness、diagnose、安全配置白名单。
- `mcp_server.py`：MCP 薄适配层，只包装同一套 agent 能力。
- `web_script.js`：BOSS 直聘页面中的油猴脚本。
- `core.py` / `model_stream.py`：模型调用、岗位评分、流式输出、重试与重复检测。
- `database.py`：SQLite 历史、动作和事件记录。
- `data/`：本地个人数据目录，不应提交到仓库。

## 安装

建议使用独立虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

默认模型是 Ollama 的 `qwen3:4b`：

```powershell
ollama pull qwen3:4b
```

也可以在人工 CLI 的 `config` 向导中选择 `openai`，接入 OpenAI-compatible Chat Completions API。API Key 只保存在本地 `data/config.json`，状态输出会脱敏。

## 5 分钟人工启动

最简单方式是双击：

```text
start_job_seeker.bat
```

启动器会：

1. 切换到项目目录并设置 UTF-8 控制台。
2. 优先使用 `.venv\Scripts\python.exe`。
3. 检查 Python 依赖、端口占用和模型服务配置。
4. 启动人工 CLI。
5. API 就绪后尝试打开油猴脚本安装页和 BOSS 搜索页。

也可以手动启动：

```powershell
python main.py
```

首次启动或缺少配置时，CLI 会引导你完成：

1. 配置模型来源、模型名称、端口、岗位评分阈值和本轮打招呼上限。
2. 输入 PDF 简历路径。
3. 提取 PDF 文本并生成 `data/resume/resume.md`。
4. 打开编辑器，由人工确认简历内容。
5. 生成岗位标签和用户画像。
6. 打开编辑器，由人工确认岗位标签和用户画像。
7. 生成打招呼草稿，由人工确认启用。
8. 进入待启动状态。

然后在 CLI 中输入：

```text
script
start
```

`script` 会显示油猴脚本安装/更新地址。安装或更新脚本后，刷新 BOSS 搜索页，等 CLI 显示脚本心跳，再输入 `start` 开始。

## 人工 CLI 命令

```text
status        显示系统状态和 agent 卡点
config        重新配置基础参数
resume        重新上传或编辑简历
tags          编辑岗位搜索标签
greeting      重新生成并确认打招呼用语
start         开始或继续运行
pause         暂停运行
stop          停止自动化
actions       处理待确认动作
history       显示最近历史
logs          显示最近日志
script        显示油猴脚本安装/更新地址
doctor        检查依赖、模型服务、油猴连接和 agent 就绪状态
help          显示帮助
quit          退出 CLI
```

人工 CLI 会展示服务启动、脚本心跳、页面动作、岗位详情、模型评分、推荐结果、打招呼状态、SQLite 落库和错误恢复信息。默认日志模式为 `compact`；排查问题时可以在 `config` 中改为 `debug`。

## Agent 快速开始

Agent 推荐使用非交互模式：

```powershell
python main.py serve
```

然后在另一个终端调用：

```powershell
python main.py agent diagnose --json
```

常用命令：

```powershell
python main.py agent status --json
python main.py agent diagnose --json
python main.py agent configure --set session_greet_limit=20 --set score_threshold=75 --json
python main.py agent configure --tags "Python后端,FastAPI,AI应用" --json
python main.py agent start --json
python main.py agent pause --json
python main.py agent stop --json
python main.py agent wait --until ready --timeout 120 --json
python main.py agent wait --until script_online --timeout 120 --json
python main.py agent logs --level error --json
python main.py agent history --limit 20 --json
python main.py agent actions --json
```

退出码约定：

- `0`：命令成功。
- `1`：运行错误或启动条件不满足。
- `2`：参数或配置错误。
- `3`：等待超时。

如果端口上跑的是旧服务，agent 命令会提示当前服务不支持 `/agent` 契约。此时先关闭旧进程，再重新运行 `python main.py serve` 或 `python main.py`。

## Agent JSON 契约

所有 agent 命令返回统一 JSON envelope：

```json
{
  "ok": true,
  "ready": false,
  "control": "paused",
  "run_id": "run-xxxxxxxxxxxx",
  "readiness": {},
  "missing_requirements": ["script_offline"],
  "human_required": true,
  "next_action": "refresh_boss_page",
  "suggested_command": "python main.py agent wait --until script_online --timeout 120 --json",
  "script": {},
  "model": {},
  "session": {},
  "last_error": "",
  "data": {}
}
```

关键字段：

- `ok`：当前命令是否执行成功。
- `ready`：当前保存状态是否满足 agent 启动条件。
- `control`：后端控制状态，可能是 `paused`、`running`、`stopped`。
- `run_id`：当前后端运行轮次标识，用于聚合日志、心跳和历史。
- `readiness`：完整就绪检查结果。
- `missing_requirements`：机器可读缺失项。
- `human_required`：是否需要人工接管。
- `next_action`：推荐下一步语义动作。
- `suggested_command`：推荐下一条命令或人工动作。
- `script`：油猴脚本连接、页面、动作、心跳和脚本详情。
- `model`：模型服务状态。
- `session`：本轮打招呼计数、上限和脚本 run id。
- `last_error`：最近错误。
- `data`：完整原始状态和命令结果。

常见 `missing_requirements`：

- `resume_missing`：简历尚未保存或确认，需要人工 CLI。
- `profile_missing`：用户画像尚未生成或确认，需要人工 CLI。
- `greeting_missing`：打招呼话术尚未确认，需要人工 CLI。
- `script_offline`：油猴脚本未连接或心跳过期，需要刷新 BOSS 页面。
- `openai_api_key_missing`：OpenAI 模式缺少 API Key，需要人工配置。
- `model_unavailable`：模型服务不可用，需要人工检查 Ollama 或 API 配置。

`diagnose` 是 agent 首选命令。它会一次性返回 readiness、最近错误、建议命令和完整状态。

## Agent 安全配置

`agent configure` 只允许写非密钥运行/模型配置和岗位标签。

允许字段包括：

- `tags` / `job_tags`
- `score_threshold`
- `session_greet_limit`
- `log_verbosity`
- `skip_contacted_companies`
- `max_contacts_per_company`
- `job_detail_max_chars`
- `model_provider`
- `ollama_host`
- `openai_api_base`
- `think_model`
- `disable_model_thinking`
- `show_model_reasoning`
- `external_model_profile`
- `model_temperature`
- `model_top_p`
- `model_repeat_penalty`
- `model_repeat_last_n`
- `model_frequency_penalty`
- `model_presence_penalty`

明确拒绝 agent 写入：

- API Key
- 简历正文
- 用户画像正文
- 打招呼话术正文
- SQLite 历史
- 动作审批结果
- 数据库内容

这样 agent 可以配置和启动流程，但不会替代人工确认隐私内容。

## MCP 使用

安装 `requirements.txt` 中的 `mcp` 依赖后，可以启动 MCP 薄适配层：

```powershell
python main.py mcp
```

MCP 面向 stdio client。Hermes 等 MCP client 可以在需要时启动这个命令，用完关闭连接；MCP 进程退出时，它内嵌启动的 API 也会一起退出。

`python main.py mcp` 会先检查本地 API 是否已经可用：

- 如果当前端口已经有新版 `/agent/*` API，它会复用现有服务。
- 如果没有 API，它会在同一个进程内启动一个后台 FastAPI 服务。
- 如果端口被旧服务占用，MCP 工具会返回旧服务不支持 `/agent` 契约的错误，需先关闭旧进程。

对于只读状态、诊断、配置这类短任务，agent 可以按需启动 MCP，用完即退出。对于已经启动浏览器自动化的长任务，agent 应保持 MCP 连接，至少等到 `jobseeker_wait` 返回完成、暂停或停止后再退出。

MCP 工具只包装同一套 `/agent/*` 能力，不复制业务逻辑：

- `jobseeker_status`
- `jobseeker_diagnose`
- `jobseeker_configure`
- `jobseeker_start`
- `jobseeker_pause`
- `jobseeker_stop`
- `jobseeker_wait`
- `jobseeker_logs`
- `jobseeker_history`

如果未安装 MCP 依赖，`python main.py mcp` 会以退出码 `2` 给出提示；此时仍可继续使用 `python main.py agent ...`。

## HTTP API

原有人工和脚本 API 保持兼容：

- `GET /status`
- `GET /config`
- `POST /config`
- `POST /script/heartbeat`
- `POST /control`
- `POST /jobs/analyze`
- `POST /actions`
- `GET /actions/pending`
- `GET /history`
- `GET /tags`
- `GET /get-introduce`
- `GET /web_script.user.js`

Agent API：

- `GET /agent/status`
- `GET /agent/diagnose`
- `POST /agent/configure`
- `POST /agent/start`
- `POST /agent/pause`
- `POST /agent/stop`
- `GET /agent/logs`
- `GET /agent/history`
- `GET /agent/actions`

## 自动化运行过程

运行时的主要链路是：

1. 人工 CLI 或 agent 启动本地 FastAPI 服务。
2. 油猴脚本在 BOSS 页面上报 `/script/heartbeat`。
3. 后端返回 `control`，脚本根据 `paused`、`running`、`stopped` 决定是否行动。
4. 脚本按岗位标签搜索职位。
5. 脚本读取职位列表，打开详情页。
6. 脚本把职位信息提交到 `/jobs/analyze`。
7. 后端读取已确认用户画像和话术，调用模型评分。
8. 模型返回学历专业、技术栈、项目经验三项评分。
9. 后端按权重计算总匹配度并返回推荐动作。
10. 达到阈值且未触发历史/公司限制时，脚本打开聊天页并发送已确认话术。
11. 动作、职位、事件和错误写入 SQLite。
12. 达到本轮上限、遇到平台限制或用户暂停时停止继续动作。

## 岗位评分逻辑

岗位分析当前使用单次三项评分：

- 学历专业
- 技术栈
- 项目经验

模型必须返回标准三项分数。系统再计算加权匹配度：

- 技术栈：50%
- 项目经验：35%
- 学历专业：15%

当总分大于等于 `score_threshold` 时推荐 `greet`，否则推荐 `skip`。

模型调用支持：

- Ollama
- OpenAI-compatible API
- 流式输出
- 思考内容隐藏或显示
- 180 秒单次超时
- 最多 3 次重试
- 重复循环检测
- OpenAI 不支持参数时自动移除该参数重试
- 岗位评分拿到标准三项结果后提前停止读取

## 油猴脚本

推荐在人工 CLI 输入：

```text
script
```

复制显示的安装地址到浏览器打开，例如：

```text
http://127.0.0.1:33333/web_script.user.js
```

通过本地地址安装时，后端会按当前端口和主机动态写入：

- `serverHost`
- `@updateURL`
- `@downloadURL`
- `@connect`

脚本头部必须保留本地连接权限：

```text
// @connect      127.0.0.1
// @connect      localhost
```

如果更新了 Python 后端文件，需要重启 `python main.py` 或 `python main.py serve`。如果只更新油猴脚本，需要在浏览器中重新安装或更新脚本，并刷新 BOSS 页面。

## 自动行为边界

系统只辅助岗位搜索、岗位评分和已确认话术的打招呼：

- 岗位达到阈值后可以自动打招呼。
- 不自动进行后续文字沟通。
- 不自动发送联系方式。
- 不自动发送作品集。
- 不绕过验证码、登录、风控或平台限制。
- 仅当 BOSS 官方附件简历请求卡片明确出现，且卡片内存在“同意”按钮时，脚本才会点击同意并记录历史。

安全验证、登录过期、访问异常、滑动/图形验证码、平台次数限制、关键输入框/按钮连续找不到时，脚本会刷新搜索页或暂停，并要求人工处理。

## 本地数据

运行数据保存在 `data/`：

- `data/config.json`：主配置和本地 API Key。
- `data/app.db`：SQLite 历史、动作和事件。
- `data/resume/original.pdf`：原始 PDF 简历。
- `data/resume/extracted.txt`：PDF 提取文本。
- `data/resume/resume.md`：人工确认后的简历。
- `data/cache/profile.json`：画像缓存。
- `data/cache/tags.txt`：岗位标签。
- `data/cache/user_detail.md`：用户画像详情。
- `data/cache/greeting.json`：打招呼话术。

这些文件包含个人数据，已通过 `.gitignore` 忽略，不建议提交。

## 常见排查

### Agent 命中旧服务

现象：`python main.py agent diagnose --json` 提示当前端口上的服务不支持 `/agent` 接口。

原因：33333 端口上可能还跑着旧版服务。

处理：

1. 关闭旧的 `python main.py` 或 `python main.py serve` 进程。
2. 重新启动当前代码：

```powershell
python main.py serve
```

### 油猴脚本离线

现象：`missing_requirements` 包含 `script_offline`，或 CLI 显示脚本离线/心跳过期。

处理：

1. 在 CLI 输入 `script`。
2. 重新安装或更新油猴脚本。
3. 刷新 BOSS 搜索页。
4. 等待 CLI 显示脚本心跳。

### 模型不可用

Ollama 模式：

```powershell
ollama serve
ollama pull qwen3:4b
python main.py
```

OpenAI-compatible 模式：

1. 在人工 CLI 中运行 `config`。
2. 填写 API Base、API Key 和模型名称。
3. 运行 `doctor` 检查。

### 打招呼没有发生

常见原因：

- 岗位评分低于阈值。
- 公司或职位已联系过。
- 本轮打招呼达到上限。
- 聊天入口缺失。
- 页面元素选择器变化。
- 浏览器拦截弹窗。
- 脚本心跳失联。

建议查看：

```powershell
python main.py agent logs --level error --json
```

或在人工 CLI 中输入：

```text
logs
history
doctor
```

### 平台限制或验证码

脚本不会绕过平台验证。遇到验证码、登录过期、访问异常、次数限制或风控页面时，系统会暂停或重试有限次数，并要求人工处理。

## 开发验证

Python 静态检查：

```powershell
$files = Get-ChildItem -File -Filter *.py | ForEach-Object { $_.FullName }
python -m py_compile $files
```

油猴脚本语法检查：

```powershell
node --check web_script.js
```

Agent API 快速检查：

```powershell
python main.py serve
python main.py agent diagnose --json
python main.py agent configure --set session_greet_limit=20 --json
python main.py agent start --json
```

## 致谢与来源

本项目基于 [goodjobs](https://github.com/gbcdby/goodjobs) 修改和再发布，原作者为嘎嘣脆的贝爷。

原项目采用 MIT License。本仓库保留原作者版权声明，并对当前版本的修改部分增加 Chatbot-Zhou 的修改版权声明。
