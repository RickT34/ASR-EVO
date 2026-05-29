# ASR-EVO

ASR-EVO 是一个 macOS 优先的轻量级听写助手：通过外部工具触发录音，将语音发送给 ASR API 转写，再把转写文本交给 LLM 按当前提示词润色，最后插入到当前光标位置。

它适合中文听写、会议记录、工作聊天、邮件草稿、技术记录等需要“先口述、再整理”的场景。项目保持 Python-only，尽量贴近 macOS 原生交互，同时把平台相关代码和核心流水线分开，方便以后扩展到其他桌面系统。

## 它强在哪

很多听写工具只做“语音 -> 原文输入”。ASR-EVO 的重点是“语音 -> 可直接使用的文本”。

它把听写拆成两段：ASR 负责听清你说了什么，LLM 负责根据当前应用、历史上下文和你选择的提示词，把文本整理成你真正想发出去或记下来的形式。你可以在微信里用“工作聊天”，在邮件里用“邮件”，在 Obsidian 里用“技术记录”或“会议纪要”；一旦在某个应用里选过风格，之后会自动记住。

典型优势：

- **按应用自动切换风格**：同一段口述，在聊天、邮件、会议记录里需要完全不同的输出。
- **可改的提示词文件**：每个风格都是本地 `.md` 文件，不需要改代码。
- **带上下文润色**：模型能看到同一应用最近几分钟的听写内容，减少指代不清和前后风格不一致。
- **历史可回看**：远程 API 或插入失败时，原始转写仍会保存，减少“说了一大段结果丢了”的挫败感。
- **尽量不打扰剪贴板**：默认短暂使用剪贴板粘贴，再恢复原内容。

## 使用例子

口述：

```text
嗯你帮我跟进一下那个报价单，然后今天下午三点之前最好能给我一个版本，如果来不及的话也先同步一下卡在哪里
```

使用 `情景/工作聊天` 后：

```text
请帮忙跟进报价单，今天下午2点前提供一版；如来不及，请同步当前卡点。
```

适合微信、飞书、Slack、企业微信等短消息场景。它会去掉口头填充词，保留语气和意图，不会擅自加过度客套。

## 功能

- macOS 状态栏托盘应用，无主窗口
- 标准本机控制接口，可由 skhd、Hyprland、脚本或其他外部工具触发开始/停止/切换
- 语音转文本走 API，目前默认使用阿里云百炼 DashScope Qwen ASR
- 文本后处理走 OpenAI-compatible Chat Completions API，默认使用 `qwen-plus`
- 提示词完全文件化，支持子文件夹分类并在托盘中显示为子菜单
- 在不同应用中切换提示词后，会自动把该提示词绑定到当前应用
- LLM 可读取同一应用内最近听写上下文，默认 TTL 为 10 分钟
- 本地 SQLite 历史记录，托盘中可查看统计并复制原始转写或润色结果
- 默认使用临时剪贴板粘贴并恢复原剪贴板，尽量贴合主流 macOS 输入体验

## 截止当前版本

当前版本是 `0.1.0`。它已经可作为日常自用版本试用，但还没有打包成 `.app` 或发布到 Homebrew。运行方式是从源码启动 Python 托盘进程。

## 系统要求

- macOS
- Python 3.11+
- 可用的麦克风
- macOS 辅助功能权限和麦克风权限
- DashScope API Key，或兼容当前接口的服务端

## 快速开始

```bash
git clone <your-repo-url>
cd ASR-EVO
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
cp config.example.toml config.toml
cp .env.example .env
```

编辑 `.env`：

```bash
DASHSCOPE_API_KEY=sk-...
```

启动：

```bash
.venv/bin/asr-evo
```

首次运行时，macOS 会请求麦克风权限。文本插入需要给运行该进程的终端或 Python 解释器授予“辅助功能”权限。

ASR-EVO 不内置按键侦听。托盘进程启动后，外部工具通过 `asr-evo-control` 发送控制命令：

```bash
.venv/bin/asr-evo-control start
.venv/bin/asr-evo-control stop
.venv/bin/asr-evo-control toggle
.venv/bin/asr-evo-control status
```

常见用法：

1. 先运行 `.venv/bin/asr-evo`，让状态栏托盘进程保持常驻。
2. 把光标放到任意文本输入框。
3. 用外部快捷键工具绑定 `.venv/bin/asr-evo-control toggle`，或分别绑定 `start` / `stop`。
4. 停止录音后等待转写、润色和插入。

macOS `skhd` 示例：

```text
cmd + shift - space : /path/to/ASR-EVO/.venv/bin/asr-evo-control toggle
```

Hyprland 示例：

```text
bind = SUPER SHIFT, SPACE, exec, /path/to/ASR-EVO/.venv/bin/asr-evo-control toggle
```

## 配置

配置文件是 `config.toml`。修改后点击托盘主菜单中的“重新加载配置”，或重启应用。

常用项：

```toml
[control]
port = 8765

[asr]
model = "qwen3-asr-flash"
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

[llm]
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
model = "qwen-plus"

[style]
mode = "通用润色"
prompts_dir = "prompts"
app_styles = {}

[context]
enabled = true
ttl_seconds = 600
max_items = 20
max_chars = 6000
scope = "app"

[review]
enabled = true

[audio]
input_device = ""

[debug]
dump_remote_requests = false
include_large_request_values = false
max_request_value_chars = 4000
```

`audio.input_device` 为空时跟随系统默认输入设备；也可以直接在托盘菜单的“输入来源”里切换，选择会写回 `config.toml`。

控制接口固定只监听 `127.0.0.1`。如果你希望多个实例使用不同控制端口，可以显式配置：

```toml
[control]
port = 8766
```

按住录音、松开停止的行为交给外部工具表达：按下时执行 `asr-evo-control start`，松开时执行 `asr-evo-control stop`。

## 提示词

所有润色风格都是 `prompts_dir` 目录中的普通 `.md` 文件。文件名去掉扩展名后就是风格 id，也会作为托盘菜单里的显示名。

示例：

```text
prompts/
  通用润色.md         -> 通用润色
  忠实轻修.md         -> 忠实轻修
  情景/
    工作聊天.md       -> 情景/工作聊天
    邮件.md           -> 情景/邮件
```

子文件夹会显示为子菜单。`README.md`、空文件、隐藏文件和隐藏目录不会被加载。

在某个应用前台时选择一个提示词，ASR-EVO 会自动把这个风格绑定到该应用，并写入：

```toml
[style]
app_styles = { "com.apple.TextEdit" = "通用润色", "com.apple.mail" = "情景/邮件" }
```

没有绑定过的应用使用 `[style].mode` 指定的全局默认风格。

## 上下文和历史

润色上下文默认使用同一应用内最近 10 分钟的听写结果。程序会统一从本地 SQLite 历史记录读取上下文，再按 `[context]` 的范围、条数和字数限制传给 LLM，帮助模型理解上下文。

长期历史保存在本地 SQLite，默认路径是 `data/asr_evo.sqlite3`。托盘菜单中的“听写统计”可以查看累计次数、字数、音频秒数和按应用统计；“历史记录”可以复制原始转写或 AI 润色结果。

默认会在插入前让用户确认润色结果：`[review].enabled = true` 时，润色文本会先显示在可编辑文本框中；用户点击“确定”或按 `Cmd+Enter` / `Ctrl+Enter` 后，确认文本会写入 `user_edited_text` 并插入到当前光标处。如果取消，则不会插入，也不会保存这条历史记录。后续润色上下文统一使用 `user_edited_text`，因此字段语义始终是“用户最终采用的文本”。如果关闭 `[review].enabled`，程序会直接插入 AI 润色结果，并把它同时写入 `user_edited_text`。

这个开关也可以在托盘菜单中通过“插入前确认文本”随时切换，选择会立即生效并写回 `config.toml`。

如果 ASR 已成功，但后续 LLM 或插入失败，原始转写也会写入历史，方便更换配置或重启后手动取回。

## 隐私边界

ASR-EVO 不把 API Key 写入配置文件，默认从 `.env` 的 `DASHSCOPE_API_KEY` 读取。

需要注意：

- 录音音频会发送给 ASR provider。
- 原始转写、历史上下文和提示词会发送给 LLM provider。
- 听写历史保存在本地 SQLite，包含原始转写、润色结果和可采集到的用户修订。
- 默认插入方式会短暂使用系统剪贴板，并在短延迟后恢复原内容。

`.env`、`config.toml` 和 `data/` 已被 `.gitignore` 排除。发布或提交代码前请确认没有把个人配置、API Key 或历史数据库加入 Git。

## 调试远程请求

如果需要看清楚发给 ASR/LLM 远程 API 的请求内容，可以临时开启调试快照：

```toml
[debug]
dump_remote_requests = true
```

请求快照会打印到 `stderr`，包含 method、URL、header 和 JSON payload。`Authorization` 会自动显示为 `<redacted>`；音频 base64 默认只显示字节数和字符数，避免终端输出过长。

也可以只在命令行测试时开启：

```bash
.venv/bin/asr-evo-transcribe /path/to/audio.wav --dump-remote-requests
```

确实需要查看完整大字段时，再临时打开：

```toml
[debug]
include_large_request_values = true
```

## 插入策略

默认插入方式是 `pasteboard_restore`：

1. 快照当前剪贴板内容。
2. 将最终文本放入剪贴板。
3. 发送 `Cmd+V`，让目标应用自己处理选区、占位文字、输入法和光标位置。
4. 如果用户在短时间窗口内没有改动剪贴板，则恢复原剪贴板。

这种策略比直接改 Accessibility `AXValue` 更接近主流输入法、听写工具和文本扩展工具的行为。后者容易把灰色占位文字一起插入，或导致光标跳到文本开头。

## 命令行工具

测试 ASR/LLM 凭据：

```bash
.venv/bin/asr-evo-transcribe /path/to/audio.wav
```

只测试 macOS 插入层：

```bash
.venv/bin/asr-evo-insert-test "hello from ASR-EVO"
```

尝试其他插入模式：

```bash
.venv/bin/asr-evo-insert-test "hello from ASR-EVO" --mode accessibility
.venv/bin/asr-evo-insert-test "hello from ASR-EVO" --mode unicode_events
```

控制正在运行的托盘进程：

```bash
.venv/bin/asr-evo-control toggle
.venv/bin/asr-evo-control status --json
```

## 开发

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest
```

项目结构和扩展点见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 开源许可

MIT License。见 [LICENSE](LICENSE)。
