# ASR-EVO

ASR-EVO 是一个 macOS 优先的听写助手。按下全局快捷键后开始录音，将音频发送给 ASR API，再把转写文本交给 LLM 按当前风格润色，最后插入到当前光标位置。

The current codebase is the first architecture slice: core pipeline, context memory, provider boundaries, and macOS adapter skeletons.

## Design

```text
asr_evo/
  core/                 # platform-neutral pipeline, ports, state, context memory
  providers/            # ASR and LLM adapters
  postprocess/          # LLM prompt styles
  platforms/
    macos/              # native macOS hotkey, recorder, inserter, permissions, tray
    base/               # extension points for future Windows/Linux adapters
```

## 上下文与历史

短期上下文保存在内存里，用于下一次 LLM 润色。默认只使用同一前台应用内的近期记录：

- `ttl_seconds`: 超过这个时间的记录会被忽略，默认 `600`。
- `max_items`: 最多保留多少条上下文记录，默认 `20`。

长期历史会持久化到 SQLite，默认路径是 `data/asr_evo.sqlite3`。托盘菜单中的 `听写统计` 可以查看听写次数、累计字数、累计音频秒数和按应用统计；`历史记录` 可以查看最近记录，并选择复制原始转写或 AI 润色结果到剪贴板。若 ASR 已成功但后续远程 API 或插入失败，原始转写也会进入历史记录。

## 润色风格

托盘菜单有 `润色风格与提示词` 子菜单。默认风格也是普通提示词文件，位于 `prompts/`：

- `exact.txt`：忠实轻修，尽量保留原话，只修正明显听写问题。
- `polished.txt`：通用润色，整理成自然清楚、可直接使用的中文。
- `concise.txt`：简洁压缩，删去冗余口语，保留关键信息。
- `工作聊天.txt`：适合 Slack、飞书、企业微信、微信等短消息。
- `邮件.txt`：整理成可直接发送的邮件正文。
- `会议纪要.txt`：整理讨论结论、决定、行动项和待确认事项。
- `技术记录.txt`：保留代码、命令、路径、指标和技术术语。

所有风格都从提示词目录加载：

```toml
[style]
mode = "polished"
prompts_dir = "prompts"
app_styles = {}
```

把 `.txt` 或 `.md` 文件放到 `prompts/`。每个非空文件都会成为托盘菜单里的一个风格；例如 `工作聊天.txt` 会显示为 `工作聊天.txt`，风格 id 是 `工作聊天`。默认文件 `exact.txt`、`polished.txt`、`concise.txt` 的风格 id 分别是 `exact`、`polished`、`concise`。`README.md`、空文件和隐藏文件不会被加载为风格。

`润色风格与提示词` 菜单支持：

- 切换风格，并自动绑定到当前应用
- 清除当前应用绑定
- 显示当前应用是否已绑定，以及绑定到哪个提示词文件
- 打开提示词文件夹

提示词文件的新增、删除、改名和内容编辑都在文件夹中完成。修改后点击主菜单 `重新加载配置`，或重启应用。

按应用绑定会写入 `app_styles`。在某个应用里切换风格时，程序会自动把该应用绑定到所选风格。例如下面配置会让 TextEdit 自动使用 `polished.txt`，让某个自定义会议提示词自动用于 Obsidian：

```toml
[style]
mode = "polished"
prompts_dir = "prompts"
app_styles = { "com.apple.TextEdit" = "polished", "md.obsidian" = "会议纪要" }
```

开始听写时，程序会根据当前前台应用自动切换到对应风格。

## 配置

具体设置请点击主菜单的 `打开配置文件`，编辑带注释的 `config.toml`。保存后点击主菜单的 `重新加载配置` 才会生效。API Key 仍建议写在 `.env`。

状态栏图标和状态文字也可在 `config.toml` 中定制：

```toml
[status]
idle_icon = "ASR"
recording_icon = "REC ASR"
transcribing_icon = "... ASR"
polishing_icon = "TXT ASR"
inserting_icon = "INS ASR"
error_icon = "! ASR"
idle_text = "空闲"
recording_text = "正在录音，再按快捷键停止"
transcribing_text = "正在转写"
polishing_text = "正在润色"
inserting_text = "正在插入"
error_text = "错误"
```

快捷键支持两种模式：

```toml
[hotkey]
toggle = "cmd+shift+space"
mode = "toggle"
```

如果想按住地球仪键听写、松开停止，改成：

```toml
[hotkey]
toggle = "globe"
mode = "hold"
```

`globe` 和 `fn` 等价。由于 macOS 会把地球仪键作为 Fn 标志处理，具体行为还取决于系统设置中的“按下地球仪键”配置；如果系统抢占了该键，需要在系统设置里关闭或调整相关快捷功能。

## macOS Insertion Strategy

The default insertion path uses temporary pasteboard insertion with restoration:

1. Snapshot the current pasteboard items and data types.
2. Put the final text on the pasteboard.
3. Send `Cmd+V`, letting the target app handle placeholder text, selection, cursor position, rich text, and input method state.
4. Restore the original pasteboard only if the user did not change it during the short insertion window.

Direct Accessibility value mutation remains available as `mode = "accessibility"`, but it is not the default because many apps expose placeholder text through Accessibility or reset selection after `AXValue` changes.

macOS will require Microphone and Accessibility permissions.

## Configuration

Copy the examples:

```bash
cp config.example.toml config.toml
cp .env.example .env
```

Set:

```bash
DASHSCOPE_API_KEY=sk-...
```

The default LLM endpoint is Aliyun Bailian/DashScope OpenAI-compatible mode:

```toml
[llm]
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
model = "qwen-plus"
```

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
```

## 启动

首次运行先创建本地配置：

```bash
cp config.example.toml config.toml
cp .env.example .env
```

把 DashScope key 写入 `.env`：

```bash
DASHSCOPE_API_KEY=sk-...
```

启动托盘应用：

```bash
.venv/bin/asr-evo
```

默认快捷键是 `cmd+shift+space`。

1. 把光标放到任意文本输入框。
2. 按 `cmd+shift+space` 开始录音。
3. 再按一次 `cmd+shift+space` 停止录音。
4. 等待转写、润色和插入。

macOS 会需要辅助功能权限。第一次录音时，终端/Python runtime 也可能请求麦克风权限。

You can test provider credentials with an existing audio file before using the hotkey:

```bash
.venv/bin/asr-evo-transcribe /path/to/audio.wav
```

You can test only the macOS insertion layer by focusing a text field and running:

```bash
.venv/bin/asr-evo-insert-test "hello from ASR-EVO"
```

You can explicitly try other insertion modes:

```bash
.venv/bin/asr-evo-insert-test "hello from ASR-EVO" --mode accessibility
.venv/bin/asr-evo-insert-test "hello from ASR-EVO" --mode unicode_events
```
