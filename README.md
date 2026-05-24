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

## Style Switching

The menu bar app has a `Style` submenu. Built-in styles are:

- `Exact`: preserve wording, only fix obvious recognition errors and punctuation.
- `Polished`: rewrite into clear written Chinese without changing meaning.
- `Concise`: remove filler and keep the result compact.

Custom styles are loaded from the configured prompt directory:

```toml
[style]
mode = "polished"
custom_prompt = ""
prompts_dir = "prompts"
```

Put `.txt` or `.md` files into `prompts/`. Each non-empty file becomes a style in the tray menu; `work-chat.txt` appears as `Work Chat`.

If `custom_prompt` is non-empty, it acts as a global override for all style selections. Leave it empty to use the selected built-in or file-based style.

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

## Launch

Create local config files first:

```bash
cp config.example.toml config.toml
cp .env.example .env
```

Put your DashScope key in `.env`:

```bash
DASHSCOPE_API_KEY=sk-...
```

Start the menu bar app:

```bash
.venv/bin/asr-evo
```

The default hotkey is `cmd+shift+space`.

1. Put the cursor in any text field.
2. Press `cmd+shift+space` to start recording.
3. Press `cmd+shift+space` again to stop.
4. Wait for transcription, polishing, and native insertion.

macOS should ask for Accessibility permission. Microphone permission may be requested by the terminal/Python runtime the first time recording starts.

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
