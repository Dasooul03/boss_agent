# Job Seeker

> 当前版本只做岗位分析和打招呼流程。普通 BOSS 聊天页不会再自动检查官方附件简历请求卡片，也不会自动发送简历附件；简历文件仍用于画像、标签、评分和话术生成。
> 旧数据库中可能仍保留 `resume_sent` 一类历史字段，但当前版本不会再产生发送简历附件动作。

Job Seeker 是一个本机运行的 BOSS 直聘辅助工具。它由本地 Python 后端、命令行控制台和 Tampermonkey 油猴脚本组成，用于读取岗位、调用模型评分、记录历史，并在人工确认过配置后自动执行打招呼流程。

当前版本只保留两条清晰入口：

- `start_job_seeker.bat`：人工模式，用来首次配置、编辑简历、确认画像、调整标签、查看日志和排查问题。
- `start_job_seeker_auto.bat`：自动模式，读取已有配置后直接启动，适合让 Hermes/Codex/其他 agent 打开这个脚本。

项目不再提供 MCP 或 JSON Agent 控制入口。`python main.py agent` 和 `python main.py mcp` 会明确提示不支持。Agent 后续只需要启动自动模式，并通过 `/status`、`/logs` 观察状态。

## 工作原理

1. Python 后端启动本地 API，默认地址是 `http://127.0.0.1:33333`。
2. Tampermonkey 脚本在 BOSS 搜索页中连接本地 API。
3. 脚本读取岗位列表，后台打开岗位详情页，不抢前台焦点。
4. 后端用已保存的简历画像和模型配置计算岗位匹配度。
5. 达到分数阈值且没有历史重复时，脚本进入聊天页发送已确认的话术。
6. 所有岗位、动作、错误和日志都会写入本地 `data/`。

安全边界保持不变：系统不会绕过登录、验证码、Tampermonkey 安装确认或平台风控。遇到这些情况会暂停并提示人工处理。

## 快速开始

### 1. 安装环境

需要 Python 3.10+，以及 Ollama 或 OpenAI 兼容接口。

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
```

如果使用 Ollama：

```powershell
ollama pull qwen3:4b
ollama serve
```

### 2. 首次使用人工模式

双击：

```text
start_job_seeker.bat
```

或在项目目录运行：

```powershell
python main.py
```

首次进入后按 CLI 提示完成配置。建议先完成这些内容：

- 模型来源、模型地址、模型名称。
- 简历 PDF 或简历正文。
- 简历画像、岗位搜索标签。
- 打招呼话术。
- 本轮打招呼上限和评分阈值。

### 3. 安装油猴脚本

人工模式启动后，在 CLI 里输入：

```text
script
```

复制显示的脚本地址到浏览器地址栏，例如：

```text
http://127.0.0.1:33333/web_script.user.js
```

注意：复制地址时不要带引号、句号、逗号或其他多余标点。Tampermonkey 会打开安装或更新页面，需要人工点击确认。项目更新后建议先重新打开这个地址更新油猴脚本，再刷新 BOSS 搜索页测试，避免浏览器还在运行旧脚本。

### 4. 打开 BOSS 搜索页

在同一个浏览器中打开：

```text
https://www.zhipin.com/web/geek/job
```

确保已经登录 BOSS 直聘。如果出现验证码、登录过期或访问异常，需要先人工处理。

### 5. 开始运行

回到人工 CLI，输入：

```text
start
```

系统会让你确认本轮岗位搜索标签和打招呼上限，然后脚本开始执行。

## 自动模式

自动模式适合在已经完成一次人工配置后使用。

双击：

```text
start_job_seeker_auto.bat
```

或运行：

```powershell
python main.py autorun
```

自动模式会执行以下流程：

1. 读取 `data/config.json` 和 `data/cache/` 中的已有配置。
2. 检查简历是否存在。缺简历时不会启动，需要回到人工模式配置。
3. 如果已有简历但缺画像、标签或话术，会尝试用当前模型自动生成。
4. 启动本地 API。
5. 打开油猴脚本安装页和 BOSS 搜索页。
6. 等待油猴脚本心跳，最多等待 120 秒。
7. 脚本在线后自动开始运行，不需要再输入 `start`。

自动模式不会询问问题，也不会打开标签编辑器。它使用当前保存的配置，所以首次配置、修改标签、修改话术、换模型时仍建议用人工模式。

为了避免连续双击启动器或 agent 重复启动时打开一堆页面，启动器会记录最近一次自动打开浏览器的时间。60 秒内重复启动时，会跳过重复打开油猴脚本页或 BOSS 搜索页。浏览器打开冷却记录统一保存在 `data/cache/browser_open_*.stamp`。

## Agent 使用建议

Agent 不需要调用 MCP 或业务 API。推荐流程很简单：

1. 启动 `start_job_seeker_auto.bat`。
2. 等待窗口输出，判断是否启动成功。
3. 用 `GET http://127.0.0.1:33333/status` 观察控制状态、脚本心跳、计数和配置状态。
4. 用 `GET http://127.0.0.1:33333/logs` 查看最近日志。
5. 如果状态提示登录、验证码、油猴安装、模型不可用或简历缺失，让用户接管。

`/status` 的模型思考字段说明：

- `scoring_thinking`：岗位评分是否允许思考。
- `profile_tags_thinking`：简历画像和岗位标签生成是否允许思考。
- `greeting_thinking`：打招呼话术始终允许思考。
- `non_scoring_thinking`：兼容旧字段，表示画像/标签类非评分任务是否允许思考。

Agent 不应该直接写入 API Key、简历正文、画像正文、打招呼话术或动作审批结果。需要改这些内容时，让用户进入人工模式处理。

状态面板中的模型连通性会做一次轻量预热检测：Ollama 会读取流式首个响应，OpenAI 兼容接口会发送一次极短的 `/chat/completions` 请求。预热失败只代表当前配置或网络不可用，不会绕过后续人工排查。

## 常用 CLI 命令

| 命令 | 作用 |
| --- | --- |
| `status` | 查看当前状态、脚本连接、运行控制和配置完成度 |
| `config` | 修改模型、端口、阈值、日志模式等基础配置 |
| `resume` | 上传或编辑简历 |
| `profile` | 重新生成或编辑简历画像 |
| `session` | 修改本轮标签和打招呼上限 |
| `tags` | 重新生成或编辑岗位搜索标签 |
| `greeting` | 重新生成或编辑打招呼话术 |
| `start` | 人工确认后开始或继续运行 |
| `pause` | 暂停运行 |
| `stop` | 停止自动化 |
| `actions` | 处理待确认动作 |
| `history` | 查看最近岗位历史 |
| `logs` | 查看最近日志 |
| `script` | 显示油猴脚本安装地址 |
| `doctor` | 检查依赖、模型、端口和脚本连接 |
| `help` | 显示帮助 |
| `quit` | 退出 CLI |

## 配置说明

配置文件位于：

```text
data/config.json
```

如果 `data/config.json` 被手动改坏，启动时会打印 `[警告] 配置文件损坏，已使用默认配置`，然后按默认配置继续运行。建议先备份损坏文件，再用人工模式重新保存配置。

常用字段如下：

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `server_host` | `127.0.0.1` | 本地 API 监听地址 |
| `server_port` | `33333` | 本地 API 端口 |
| `model_provider` | `ollama` | `ollama` 或 `openai` |
| `ollama_host` | `http://127.0.0.1:11434` | Ollama 地址 |
| `openai_api_base` | `https://api.openai.com/v1` | OpenAI 兼容接口地址 |
| `openai_api_key` | 空 | OpenAI 兼容接口密钥 |
| `think_model` | `qwen3:4b` | 模型名称 |
| `score_threshold` | `70` | 达到多少分才打招呼 |
| `session_greet_limit` | `50` | 单轮最多打招呼数量 |
| `max_contacts_per_company` | `1` | 同一公司最多联系次数 |
| `skip_contacted_companies` | `true` | 跳过已联系公司 |
| `job_detail_max_chars` | `1600` | 传给模型的岗位描述最大字符数 |
| `log_verbosity` | `compact` | 日志详细度：`compact`、`normal`、`debug` |
| `disable_model_thinking` | `true` | 岗位评分时是否关闭模型思考 |
| `show_model_reasoning` | `false` | 是否在日志中展示模型思考内容 |
| `external_model_profile` | `generic` | OpenAI 模型适配类型：`generic`、`qwen`、`deepseek`、`doubao` |
| `job_score_num_predict_think_off` | `-1` | 评分关闭思考时的生成长度，`-1` 表示不限制 |
| `job_score_num_predict_think_on` | `-1` | 评分开启思考时的生成长度，`-1` 表示不限制 |
| `model_temperature` | `0.2` | 模型温度 |
| `model_top_p` | `0.8` | top_p 采样参数 |
| `model_repeat_penalty` | `1.18` | Ollama 重复惩罚 |
| `model_repeat_last_n` | `128` | Ollama 重复检查窗口 |
| `model_frequency_penalty` | `0.3` | OpenAI 兼容频率惩罚 |
| `model_presence_penalty` | `0.1` | OpenAI 兼容存在惩罚 |

### 评分 token 设置

`job_score_num_predict_think_off` 和 `job_score_num_predict_think_on` 现在会真实用于岗位评分：

- 第一次评分使用当前 `disable_model_thinking` 设置，并选择对应 token 预算。
- 第二、三次评分会强制关闭思考，并使用 `job_score_num_predict_think_off`。
- `-1` 表示不限制生成长度。
- 空字符串或非法字符串会自动回退到默认值，不会导致启动崩溃。
- 模型输出 JSON 或三行 `学历专业: 90` 格式都可以被解析。

如果使用 `qwen3:1.7b`、`qwen3:4b` 这类小模型，建议：

```json
{
  "disable_model_thinking": true,
  "job_score_num_predict_think_off": 200,
  "job_score_num_predict_think_on": 2048
}
```

评分任务只需要三个分数，不需要长推理。小模型开启思考时容易把输出预算消耗在 reasoning 中，导致正文为空、格式错误或评分全为 0。

CLI 配置向导中，端口、阈值、上限、岗位描述长度等整数项会持续提示直到输入合法数字，不会因为误输入字母而退出。

## 文件位置小提示

- 简历 PDF 建议放在 `data/resume/`，例如 `data/resume/resume.pdf`。
- CLI 提示输入文件路径时，路径不需要加引号。
- 如果路径里有空格，直接粘贴完整路径即可；如果失败，再把文件移动到 `data/resume/` 后输入简单路径。
- `data/` 保存个人数据、配置、缓存和数据库，通常不要提交到版本管理。
- `data/cache/tags.txt` 是岗位搜索标签。
- `data/cache/greeting.json` 是打招呼话术缓存。
- `data/cache/profile.json` 和 `data/cache/user_detail.md` 是简历画像相关缓存。

## 常见问题

### 端口 33333 被占用

查询占用进程：

```powershell
netstat -ano | findstr :33333
```

结束进程：

```powershell
taskkill /PID <PID> /F
```

也可以在人工模式中运行 `config`，改用其他端口。端口变更后需要重新安装或更新油猴脚本。

### 油猴脚本离线

检查这些点：

- 本地 CLI 或自动启动器窗口仍在运行。
- Tampermonkey 已启用。
- 脚本已安装或更新到当前地址。
- BOSS 搜索页已经刷新。
- 浏览器地址是 `https://www.zhipin.com/web/geek/job` 或其搜索结果页。

### 自动模式没有启动

自动模式需要这些条件：

- 已有简历。
- 模型可用。
- 能生成或读取画像、标签和话术。
- 油猴脚本能连接本地 API。
- BOSS 已登录且没有验证码或风控页面。

缺少任一项时，自动模式会暂停并打印原因。此时建议打开 `start_job_seeker.bat`，用 `status`、`doctor`、`logs` 排查。

### 模型评分全是 0 或提示没有返回内容

优先检查：

1. `doctor` 中模型是否真实可用。
2. 小模型是否关闭了评分思考：`disable_model_thinking=true`。
3. `job_score_num_predict_think_off` 是否过小。建议先设为 `200` 到 `400`。
4. 如果开启思考，`job_score_num_predict_think_on` 建议至少 `2048`。
5. `log_verbosity` 可临时设为 `debug`，看模型原始输出摘要。

如果模型偶发失败，系统会安全跳过当前岗位，不会用不可靠分数自动打招呼。

### 长时间运行后重复打开很多页面

当前脚本包含运行锁、URL 冷却、近期处理历史和临时标签清理。仍出现大量页面时，通常是以下原因：

- 同时打开了多个旧版本搜索页。
- 油猴脚本没有更新。
- 后端服务重启后浏览器旧页面没有刷新。
- BOSS 页面出现异常、验证码或登录过期。

建议先 `stop`，关闭多余 BOSS 搜索页，重新安装脚本并刷新搜索页，再从 CLI 输入 `start`。

### 本轮刚开始就提示达到上限

系统会用后端 `run_id` 对齐脚本本地 session。若出现旧计数残留：

1. 确认油猴脚本已经更新。
2. 在人工 CLI 输入 `stop`。
3. 刷新 BOSS 搜索页。
4. 再输入 `start` 开启新一轮。

## 项目结构

```text
goodjobs-main/
├─ main.py                         # FastAPI 服务和启动入口
├─ cli_console.py                  # 人工 CLI 和自动模式控制
├─ core.py                         # 岗位评分和核心模型逻辑
├─ model_stream.py                 # Ollama/OpenAI 流式模型调用
├─ greeting_service.py             # 打招呼话术生成和保存
├─ resume_service.py               # 简历上传、提取和保存
├─ cache.py                        # 简历画像、标签和话术缓存
├─ database.py                     # SQLite 历史、动作、事件记录
├─ config.py                       # 配置加载、校验和保存
├─ runtime_state.py                # 运行状态、日志和控制状态
├─ prompts.py                      # 模型提示词
├─ schema.py                       # API 数据模型
├─ tools.py                        # 通用工具函数
├─ web_script.js                   # Tampermonkey 脚本
├─ requirements.txt                # Python 依赖
├─ start_job_seeker.bat            # 人工启动器
├─ start_job_seeker_auto.bat       # 自动启动器
├─ resume-example.md               # 简历示例文件
├─ LICENSE                         # MIT License
├─ scripts/
│  ├─ start_job_seeker.ps1         # 人工启动器 PowerShell 实现
│  └─ start_job_seeker_auto.ps1    # 自动启动器 PowerShell 实现
└─ data/                           # 个人数据目录，本地使用
   ├─ config.json
   ├─ app.db
   ├─ resume/
   └─ cache/
```

## 验证命令

开发或修改后可以运行：

```powershell
Get-ChildItem -Recurse -Filter *.py -File | Where-Object { $_.FullName -notlike '*\.venv\*' } | ForEach-Object { python -m py_compile $_.FullName }
node --check web_script.js
powershell -NoProfile -Command '$null = [scriptblock]::Create((Get-Content scripts/start_job_seeker.ps1 -Raw))'
powershell -NoProfile -Command '$null = [scriptblock]::Create((Get-Content scripts/start_job_seeker_auto.ps1 -Raw))'
```

这些命令只做静态检查，不会打开浏览器。

## 致谢

本项目基于 [goodjobs](https://github.com/gbcdby/goodjobs) 修改和再发布，原项目采用 MIT License。当前版本围绕本地人工配置、自动启动器和稳定运行做了进一步整理。
