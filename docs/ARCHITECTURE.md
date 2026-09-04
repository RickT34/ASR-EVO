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
    openai_provider.py      # OpenAI SDK-backed chat completions adapters
    factory.py              # config -> provider instances
  postprocess/
    prompts.py              # message construction for LLM post-processing
    styles.py               # prompt-file registry
  platforms/
    macos/
      runtime.py            # orchestrates macOS services and core pipeline
      tray.py               # NSStatusItem menu
      hotkey.py             # Quartz global hotkey registration
      inserter.py           # pasteboard/accessibility/unicode insertion
      frontmost.py          # frontmost app detection
      permissions.py        # macOS permission checks
    windows/
      runtime.py            # orchestrates Windows services and core pipeline
      tray.py               # pystray notification-area menu
      hotkey.py             # pynput global hotkey registration
      inserter.py           # clipboard/keyboard text insertion
      frontmost.py          # foreground window detection
  storage/
    history.py              # SQLite history, audio archive, and statistics
```

## Core Flow

```text
global hotkey -----------------------------+
                                           |
asr-evo-control start|stop|toggle          |
  -> DictationControlServer                |
  +----------------------------------------+
                                           v
                     DesktopDictationController.start_dictation()
  -> DictationPipeline.run_once()
     -> Recorder.record_until_stopped()
     -> ASRProvider.transcribe(audio)
     -> ContextStore.render_for_prompt(app)
     -> LLMProvider.polish(raw_text, context, prompt_instruction)
     -> TextReviewer.review(request, previewer, saver) when enabled
        -> previewer(style/prompt) may call LLMProvider.polish again
        -> saver(style/prompt) may update prompt files and app bindings
     -> TextInserter.insert(user_text)
     -> HistoryStore.add(record, audio)
        -> archive audio under data/recordings/
```

`DictationPipeline` transfers the recorded `AudioClip` to the controller instead of deleting it. Failures after recording are wrapped in `DictationPipelineError` with the audio and any raw transcript attached. `HistoryStore.add()` copies the audio into `data/recordings/`, commits its relative path and text metadata in SQLite, then removes the temporary recorder file. This also runs when ASR/LLM/insertion fails or the user cancels review, so every successfully completed recording remains recoverable.

When review is enabled, the controller sends `TextReviewer` the raw transcript, current polished text, selected prompt, available styles, and the rendered context. The reviewer UI may ask the controller-owned preview callback to re-run polishing with a different or edited prompt, or ask the save callback to persist the prompt file and current-app style binding; the UI does not call providers or write config files directly. Confirmed text is stored as `user_edited_text` and inserted. The last AI preview remains `final_text`, and the selected preview style is stored as `style`. If review is disabled, `user_edited_text` is initialized with the LLM-polished text. Polishing context always renders `user_edited_text`, so the field means "the text the user ultimately accepted".

History actions reuse the same provider and review services. “重新转写并润色” rebuilds an `AudioClip` from archived metadata, calls ASR, then LLM and the optional review UI. “重新润色” starts from the stored raw transcript. Both update the existing row and never invoke `TextInserter`. Audio export is a platform `FileExporter` boundary so native save dialogs remain outside core logic.

The localhost control path is intentionally small: commands are `start`, `stop`, `toggle`, and `status`, serialized as one JSON request per TCP connection. The server listens only on `127.0.0.1`. Both desktop runtimes also register the configured `[hotkey].toggle` global hotkey directly, either as a toggle or hold-to-record trigger. External tools may continue to use `asr-evo-control`.

## Prompt Styles

`StyleRegistry` recursively scans `prompts_dir` for non-empty `.md` files.

```text
prompts/通用润色.md        -> id: 通用润色, label: 通用润色, category: ()
prompts/情景/邮件.md      -> id: 情景/邮件, label: 邮件, category: ("情景",)
```

The tray renders `category` as nested submenus. Runtime stores selected styles by id, so app bindings remain UI-independent:

```toml
[style.app_styles]
"com.apple.mail" = "情景/邮件"
```

## Runtime State

The desktop runtime owns long-lived platform services:

- `DictationControlServer`
- platform `StatusTray`
- `SoundDeviceRecorder`
- OpenAI SDK clients
- `ContextStore`
- `HistoryStore`
- macOS `MacOSHotkeyListener` when enabled
- Windows `WindowsHotkeyListener` when enabled

The AppKit main thread runs the tray and platform UI work. The control server and async provider calls run on a dedicated asyncio loop thread; incoming control commands are dispatched back to the main thread before they touch frontmost-app or tray state. `DesktopDictationController` prevents overlapping dictation runs by switching state synchronously before scheduling the pipeline.

On macOS, a Quartz event tap attached to the AppKit main run loop owns global key capture. On Windows, `pystray` owns the notification-area event loop and `pynput` owns global key capture. Both toggle and hold-to-record hotkeys call the same `DesktopDictationController` actions used by the control endpoint; platform code must not duplicate prompt selection, persistence, or review rules. The `asr-evow` GUI entry point uses the same runtime without opening a console window.

Config reload is two-phase for runtime-sensitive fields. For example, when `[control].port` or `[hotkey]` changes, `MacOSDictationRuntime` starts the replacement service before stopping the previous one or allowing the controller to save `config.toml`. If the new port or hotkey is unavailable, the old runtime state and persisted config stay intact.

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
- `FileExporter`
- `PermissionChecker`
- `AppLifecycle`
- `HistoryRepository`

`DictationPipeline` only needs the narrow `TrayUI` state/error surface. `DesktopDictationController` additionally uses `StatusTray` for desktop menu state such as styles, input devices, stats, and history. Runtime-only presentation such as the control endpoint label stays in the platform tray implementation, not in the core controller protocol.

Windows support implements these ports with `pystray`, `pynput`, Tk clipboard access, and `pywin32` foreground-window detection while keeping the dictation pipeline unchanged. Future Linux support should follow the same rule: platform code may replace `StatusTray` with another desktop status surface as long as the same application-level operations are available.

## Configuration Philosophy

`config.toml` exposes only user-facing knobs:

- control port
- macOS and Windows global hotkeys
- ASR/LLM model and base URL
- prompt directory, default style, app bindings
- context enabled/TTL/max items/max chars/scope
- review confirmation enabled
- audio input device selection
- status bar labels and macOS symbol names

Internal choices such as storage path, insertion mode, ASR language and audio sample rate are currently constants in `config.py`. They can be promoted to config later if real users need them.

## Data and Privacy

Local files intentionally ignored by Git:

- `.env`
- `config.toml`
- `data/`
- `*.sqlite3`

The app sends audio to the ASR provider and sends raw transcript/context/prompt instructions to the LLM provider. SQLite history stores raw, final, captured user-edited text, and relative audio paths locally. Original recordings live under `data/recordings/` and are retained until the user removes them.

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
