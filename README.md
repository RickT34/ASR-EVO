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

短期上下文保存在内存里，用于下一次 LLM 润色。记录会按时间和作用域过滤：

- `ttl_seconds`: records older than this are ignored, default `600`.
- `scope = "app"`: only records from the same frontmost app are used.
- `scope = "window"`: future stricter mode for same app and same window title.
- `scope = "time"`: use recent records across apps.
- `max_items` and `max_chars`: cap prompt size for speed and cost control.

长期历史会持久化到 SQLite，默认路径是 `data/asr_evo.sqlite3`。托盘菜单中的 `听写历史与统计` 可以查看最近听写、各应用听写次数、累计字数和累计音频秒数。

## 润色风格

托盘菜单有 `润色风格` 子菜单。内置风格是：

- `精确保留`：尽量保留原表达，只修明显识别错误、标点和格式。
- `书面润色`：整理为自然清楚的书面中文。
- `简洁整理`：删去口语冗余，保留关键信息。

自定义风格从提示词目录加载：

```toml
[style]
mode = "polished"
custom_prompt = ""
prompts_dir = "prompts"
```

把 `.txt` 或 `.md` 文件放到 `prompts/`。每个非空文件都会成为托盘菜单里的一个风格；例如 `工作聊天.txt` 会显示为 `工作聊天`。

如果 `custom_prompt` 非空，它会作为全局强制提示词，覆盖托盘中的风格选择。想使用托盘切换，就保持 `custom_prompt = ""`。

## 设置界面

托盘菜单中的 `设置` 可以配置：

- DashScope API Key
- 快捷键
- 上下文 TTL 秒数
- 历史上下文条数
- 上下文字符上限
- 提示词目录
- 历史数据库路径

保存后会写入 `config.toml` 和 `.env`。部分设置对下一次听写立即生效；如果修改 API endpoint/model 这类 provider 初始化参数，建议重启应用。

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
provider = "openai_compat"
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
