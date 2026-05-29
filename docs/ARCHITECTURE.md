# Architecture

ASR-EVO 分成几层：核心流水线与桌面控制器、服务供应商适配器、音频适配器、UI presentation helper、平台适配器。核心层不依赖 macOS，也不依赖具体 ASR/LLM provider；平台层负责本机控制入口、文本插入、托盘菜单、权限、线程调度和应用生命周期。

## Directory Layout

```text
asr_evo/
  app.py                    # CLI entry point for the tray app
  config.py                 # TOML config model and hardcoded internal defaults
  core/
    ports.py                # Protocol interfaces used by the core pipeline
    controller.py           # desktop dictation controller wired through ports
    control.py              # localhost control protocol for external triggers
    pipeline.py             # one dictation lifecycle: record -> ASR -> LLM -> insert
    context.py              # history-backed context filtering and rendering
    state.py                # tray/runtime state enum
  audio/
    recorder.py             # sounddevice-based recorder adapter
  ui/
    menu.py                 # platform-neutral menu/status presentation helpers
  providers/
    aliyun_asr.py           # DashScope Qwen ASR adapter
    openai_compat_llm.py    # OpenAI-compatible chat completions adapter
    http_retry.py           # retry and provider error normalization
    factory.py              # config -> provider instances
  postprocess/
    prompts.py              # message construction for LLM post-processing
    styles.py               # prompt-file registry
  platforms/
    macos/
      runtime.py            # orchestrates macOS services and core pipeline
      tray.py               # NSStatusItem menu
      inserter.py           # pasteboard/accessibility/unicode insertion
      frontmost.py          # frontmost app detection
      permissions.py        # macOS permission checks
  storage/
    history.py              # SQLite history and statistics
```

## Core Flow

```text
external trigger
  -> asr-evo-control start|stop|toggle
  -> DictationControlServer
  -> DesktopDictationController.start_dictation()
  -> DictationPipeline.run_once()
     -> Recorder.record_until_stopped()
     -> ASRProvider.transcribe(audio)
     -> ContextStore.render_for_prompt(app)
     -> LLMProvider.polish(raw_text, context, prompt_instruction)
     -> TextReviewer.review(final_text) when enabled
     -> TextInserter.insert(user_text)
     -> HistoryStore.add(record)
```

`DictationPipeline` catches failures after ASR succeeds and wraps them in `DictationPipelineError` with the raw transcript attached. The runtime persists that partial record, so users do not lose text when LLM or insertion fails.

When review is enabled, the controller asks `TextReviewer` to show the polished text in an editable confirmation box before insertion. Confirmed text is stored as `user_edited_text` and inserted. If review is disabled, `user_edited_text` is initialized with the LLM-polished text. Polishing context always renders `user_edited_text`, so the field means "the text the user ultimately accepted".

The localhost control path is intentionally small: commands are `start`, `stop`, `toggle`, and `status`, serialized as one JSON request per TCP connection. The server listens only on `127.0.0.1`. External hotkey tools own key capture; ASR-EVO only owns the long-lived tray process and the local command endpoint.

## Prompt Styles

`StyleRegistry` recursively scans `prompts_dir` for non-empty `.md` files.

```text
prompts/通用润色.md        -> id: 通用润色, label: 通用润色, category: ()
prompts/情景/邮件.md      -> id: 情景/邮件, label: 邮件, category: ("情景",)
```

The tray renders `category` as nested submenus. Runtime stores selected styles by id, so app bindings remain UI-independent:

```toml
[style]
app_styles = { "com.apple.mail" = "情景/邮件" }
```

## Runtime State

The macOS runtime owns long-lived platform services:

- `DictationControlServer`
- `MacOSStatusTray`
- `SoundDeviceRecorder`
- provider HTTP clients
- `ContextStore`
- `HistoryStore`

The AppKit main thread runs the tray and platform UI work. The control server and async provider calls run on a dedicated asyncio loop thread; incoming control commands are dispatched back to the main thread before they touch frontmost-app or tray state. `DesktopDictationController` prevents overlapping dictation runs by switching state synchronously before scheduling the pipeline.

Config reload is two-phase for runtime-sensitive fields. For example, when `[control].port` changes, `MacOSDictationRuntime` binds the replacement `DictationControlServer` before the controller commits the new config or saves `config.toml`. If the new port is unavailable, the old runtime state and persisted config stay intact.

## Platform Boundaries

Core code talks to `Protocol`s in `core/ports.py`:

- `Recorder`
- `DesktopRecorder`
- `ASRProvider`
- `LLMProvider`
- `TextInserter`
- `TextReviewer`
- `FrontmostAppProvider`
- `TrayUI`
- `StatusTray`
- `Clipboard`
- `FileOpener`
- `PermissionChecker`
- `AppLifecycle`
- `HistoryRepository`

`DictationPipeline` only needs the narrow `TrayUI` state/error surface. `DesktopDictationController` additionally uses `StatusTray` for desktop menu state such as styles, input devices, stats, and history. Runtime-only presentation such as the control endpoint label stays in the platform tray implementation, not in the core controller protocol.

Future Windows/Linux support should implement these ports and keep the dictation pipeline unchanged. If a platform lacks a tray, it can replace `StatusTray` with another desktop status surface as long as the same application-level operations are available.

## Configuration Philosophy

`config.toml` exposes only user-facing knobs:

- control port
- ASR/LLM model and base URL
- prompt directory, default style, app bindings
- context enabled/TTL/max items/max chars/scope
- review confirmation enabled
- audio input device selection
- status bar labels

Internal choices such as storage path, insertion mode, ASR language and audio sample rate are currently constants in `config.py`. They can be promoted to config later if real users need them.

## Data and Privacy

Local files intentionally ignored by Git:

- `.env`
- `config.toml`
- `data/`
- `*.sqlite3`

The app sends audio to the ASR provider and sends raw transcript/context/prompt instructions to the LLM provider. SQLite history stores raw, final, and captured user-edited text locally.

## Release Checklist

Before tagging a release:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest
git status --short
```

Also verify:

- `.env`, `config.toml`, `data/` and `.DS_Store` are not tracked
- default prompt files exist and are useful in Chinese
- `config.example.toml` matches current config fields
- `README.md` quick start works on a clean clone
- `asr-evo-control start|stop|toggle|status` works against the running tray process
