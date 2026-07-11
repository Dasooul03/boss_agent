# BossAgent

BOSS 直聘自动化投递助手。Python 后端 + 本地图形化控制台 + Agent CLI + Tampermonkey 脚本，自动分析岗位、模型评分、打招呼，**自动发送简历图片**。

---

## 程序有哪些功能？运行逻辑是什么？怎样使用？

### 自动打招呼 + 简历图片发送

自动开聊推荐职位列表中的岗位。按照你设置的求职标签、评分阈值和历史去重逻辑，筛选出匹配的职位，自动进入聊天页打招呼并发送简历图片。

#### 匹配步骤

1. Tampermonkey 脚本在 BOSS 搜索页连接本地后端
2. 脚本读取岗位列表，后台打开详情页获取完整描述
3. 后端用已保存的简历画像，调用大模型计算岗位匹配度（学历、技能、经验、行业、薪资、地点等多维度评分）
4. 达到分数阈值、且没有历史重复时，脚本进入聊天页
5. 发送已确认的话术 + 自动发送简历图片

#### 异常情况

- 遇到验证码、登录过期、风控页面时暂停，等待人工处理
- 模型偶发失败时跳过当前岗位，不会用不可靠分数决策
- 当天达到打招呼上限后停止本轮
- 页面异常、DOM 未加载时自动重试

#### 运行方式

### 图形化控制台（推荐给人工操作）

```text
python main.py gui
```

会打开原生 Windows 桌面窗口。可以在界面中配置简历、筛选、话术、黄金时段，并控制开始、暂停和停止；浏览器仅用于 BOSS 页面和油猴脚本安装。

### CLI 模式（给 agent / 终端自动化）

```text
python main.py cli
```

**自动模式**（后续运行用）：

```text
start_boss_agent_auto.bat
```

或 `python main.py autorun`。自动模式会读取已有配置，缺依赖自动安装，缺模型自动拉取，脚本上线后自动开始。

---

## For 有求职之外其他用途的朋友

本程序的目标是帮助求职者调研市场行情或寻找工作。如果有其它用途，请勿下载使用。

---

## 辅助功能介绍

### 大语言模型评分

支持 Ollama 或 OpenAI 兼容接口。用你已保存的简历画像（用户详情）作为基准，对每个岗位进行多维度评分：技术栈匹配度、项目经验匹配度、学历专业匹配度、行业经验匹配度、薪资地点匹配度等。

可单独控制评分时的模型思考开关、温度和 `num_predict` 预算。

### 简历图片生成

上传 PDF 简历后，自动提取文本、生成 Markdown 简历，并将 PDF 首页渲染为 JPG 图片。打招呼时自动发送此图片。

CLI 中可通过 `send-mode` 命令切换：`text`（只发话术）或 `image`（发话术 + 简历图片）。

### 手动/自动模式

- **人工模式**：首次配置用，交互式 CLI 引导完成模型、简历、画像、标签、话术、阈值等设置
- **自动模式**：读取已有配置后直接启动，适合日常使用或 agent 调度

自动模式会执行以下流程：

1. 读取 `data/config.json` 和 `data/cache/` 已有配置
2. 检查简历是否存在，缺简历时不会启动
3. 如果缺画像、标签或话术，尝试用当前模型自动生成
4. 启动本地 API，打开 BOSS 搜索页
5. 等待油猴脚本连接（最多 120 秒）
6. 脚本上线后自动开始运行

### CLI 控制台

| 命令 | 作用 |
|------|------|
| `status` | 查看状态面板：模型、简历、脚本连接、运行控制 |
| `config` | 修改模型、端口、阈值、日志模式等基础配置 |
| `resume` | 上传 PDF 或编辑简历 |
| `profile` | 生成或编辑简历画像 |
| `tags` | 生成或编辑岗位搜索标签 |
| `greeting` | 生成或编辑打招呼话术 |
| `send-mode` | 切换发送模式：`text`（话术）或 `image`（简历图片） |
| `start` | 开始或继续运行 |
| `pause` | 暂停运行 |
| `stop` | 停止运行 |
| `actions` | 处理待确认动作 |
| `history` | 查看最近处理的岗位 |
| `logs` | 查看运行日志 |
| `doctor` | 检查依赖、模型、端口、脚本连接 |

## 系统要求

- Python 3.10+
- Ollama（默认，推荐 `qwen3:1.7b` 或更高版本）或 OpenAI 兼容接口
- 浏览器 + Tampermonkey 扩展
- 支持 Windows、Linux、macOS

## 安装方式

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

如果使用 Ollama：

```powershell
ollama pull qwen3:1.7b
ollama serve
```

## 油猴脚本安装

启动后在 CLI 输入 `script`，复制显示的地址到浏览器安装：

```text
http://127.0.0.1:33333/web_script.user.js
```

## 配置说明

配置文件 `data/config.json` 也可在 CLI 中用 `config` 命令修改。

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `model_provider` | `ollama` | `ollama` 或 `openai` |
| `think_model` | `qwen3:1.7b` | 评分/画像/话术使用的模型 |
| `score_threshold` | `70` | 达到此分才打招呼 |
| `session_greet_limit` | `50` | 每轮最多打招呼次数 |
| `send_mode` | `text` | `text` 发送话术，`image` 发送简历图片 |
| `disable_model_thinking` | `true` | 评分是否关闭思考（小模型建议关闭） |

完整字段见 `config.py` 中的 `DEFAULT_CONFIG`。

## 项目结构

```text
├─ main.py                    # FastAPI 服务 + 启动入口
├─ cli_console.py             # CLI 控制台 + 自动模式
├─ core.py                    # 岗位评分 + 模型调用
├─ model_stream.py            # Ollama/OpenAI 流式调用
├─ greeting_service.py        # 打招呼话术生成
├─ resume_service.py          # 简历上传、提取、图片生成
├─ cache.py                   # 画像/标签/话术缓存
├─ database.py                # SQLite 历史记录
├─ config.py                  # 配置加载与保存
├─ runtime_state.py           # 运行状态管理
├─ prompts.py                 # 模型提示词
├─ web_script.js              # Tampermonkey 脚本
├─ start_boss_agent.bat       # 人工启动器
├─ start_boss_agent_auto.bat  # 自动启动器
└─ data/                      # 个人数据（已 gitignore）
```

## 使用必读及免责声明

- 本程序属于辅助工具，自动行为可能被平台风控监测到，使用即意味着你愿意接受账号被限制等风险，本程序概不负责
- 本程序仅将你的 Cookie 存储在本地，不会泄露给第三方
- BOSS 直聘网站经常改版，可能导致脚本失效，遇到问题请提 Issue
- 本程序没有内置任何付费功能，下载和使用完全免费
- 本程序不对你的求职过程与结果负责，请自行甄别职位信息

---

以上

祝你求职顺利，拿到满意的 Offer 🎉
