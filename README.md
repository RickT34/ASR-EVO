# ASR-EVO

ASR-EVO is a macOS-first dictation assistant. Press a global hotkey, speak, send the audio to an ASR provider, pass the transcript through an LLM with recent context, then insert the final text at the current cursor position.

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

## Context Memory

History is stored in memory by default. Records are filtered by both time and scope:

- `ttl_seconds`: records older than this are ignored, default `600`.
- `scope = "app"`: only records from the same frontmost app are used.
- `scope = "window"`: future stricter mode for same app and same window title.
- `scope = "time"`: use recent records across apps.
- `max_items` and `max_chars`: cap prompt size for speed and cost control.

This keeps frequent dictation fast and avoids sending unrelated history to the LLM.

## macOS Insertion Strategy

The default insertion path is native and avoids overwriting the clipboard:

1. Try Accessibility focused-element insertion.
2. Fall back to CGEvent Unicode typing.
3. Clipboard restore can be added later as an explicit compatibility mode, not the default.

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

The live Aliyun ASR transport is intentionally isolated in `asr_evo/providers/aliyun_asr.py`; it should be completed and verified with real DashScope credentials before enabling production transcription.
