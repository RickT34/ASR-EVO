from __future__ import annotations

import asyncio
import concurrent.futures
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from asr_evo.config import (
    AUDIO_CHANNELS,
    AUDIO_SAMPLE_RATE,
    CONTEXT_MAX_CHARS,
    CONTEXT_SCOPE,
    INSERT_FALLBACK,
    INSERT_MODE,
    INSERT_RESTORE_DELAY_MS,
    STORAGE_DATABASE_PATH,
    AppConfig,
)
from asr_evo.core.context import ContextStore
from asr_evo.core.errors import ErrorFeedback, feedback_from_exception
from asr_evo.core.pipeline import (
    DictationDependencies,
    DictationOptions,
    DictationPipeline,
    DictationPipelineError,
)
from asr_evo.core.ports import AppContext
from asr_evo.core.state import DictationState
from asr_evo.core.style_binding import StyleBindingService
from asr_evo.postprocess.styles import StyleRegistry
from asr_evo.platforms.macos.frontmost import MacOSFrontmostAppProvider
from asr_evo.platforms.macos.hotkey import MacOSHotkeyService
from asr_evo.platforms.macos.inserter import MacOSTextInserter
from asr_evo.platforms.macos.permissions import MacOSPermissions
from asr_evo.platforms.macos.recorder import SoundDeviceRecorder
from asr_evo.platforms.macos.tray import MacOSStatusTray
from asr_evo.providers.factory import create_asr_provider, create_llm_provider
from asr_evo.storage.history import HistoryStore


@dataclass
class RuntimeState:
    state: DictationState = DictationState.IDLE
    current_error: ErrorFeedback | None = None


class MacOSDictationRuntime:
    def __init__(self, config: AppConfig) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("The macOS runtime can only run on macOS")

        self.config = config
        self.state = RuntimeState()
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._run_loop, name="asr-evo-async", daemon=True)
        self.styles = StyleRegistry(prompts_dir=config.style.prompts_dir)
        self.style_bindings = StyleBindingService(config=config, styles=self.styles)

        self.recorder = SoundDeviceRecorder(
            sample_rate=AUDIO_SAMPLE_RATE,
            channels=AUDIO_CHANNELS,
            input_device=config.audio.input_device,
        )
        self.context_store = ContextStore(
            ttl_seconds=config.context.ttl_seconds,
            max_items=config.context.max_items,
            max_chars=CONTEXT_MAX_CHARS,
            scope=CONTEXT_SCOPE,
        )
        self.asr_provider = create_asr_provider(self.config)
        self.llm_provider = create_llm_provider(self.config)
        self.app_provider = MacOSFrontmostAppProvider()
        self.history_store = HistoryStore(STORAGE_DATABASE_PATH)
        self.tray = MacOSStatusTray(
            hotkey_label=config.hotkey.toggle,
            status_config=config.status,
            styles=self.styles.all(),
            selected_style_id=self.style_bindings.current_style_id,
            on_select_style=self.select_style,
            on_reveal_prompts=self.reveal_prompts_dir,
            on_reload_config=self.reload_config,
            on_open_config=self.open_config_file,
            on_refresh_input_devices=self.refresh_input_devices,
            on_select_input_device=self.select_input_device,
            on_clear_app_style=self.clear_current_app_style,
            on_refresh_app_binding=self.sync_style_for_current_app,
            on_refresh_stats=self.refresh_menu_summaries,
            on_copy_history_raw=self.copy_history_raw,
            on_copy_history_final=self.copy_history_final,
            on_copy_error=self.copy_current_error,
            on_clear_error=self.clear_error,
            on_quit=self.quit,
        )
        self.tray_proxy = _StateTrackingTray(self)
        self.hotkey = self._create_hotkey(config)
        self.permissions = MacOSPermissions()
        self.refresh_input_devices()
        self.refresh_menu_summaries()

    def run(self) -> None:
        from AppKit import NSApp, NSApplication, NSApplicationActivationPolicyAccessory

        self.loop_thread.start()
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        self._update_permission_state()
        self.hotkey.start()
        if self.state.state != DictationState.ERROR:
            self.tray.set_state(DictationState.IDLE.value)
        NSApp.run()

    def toggle_dictation(self) -> None:
        if self.state.state == DictationState.RECORDING:
            self.stop_dictation()
            return
        self.start_dictation()

    def start_dictation(self) -> None:
        if self.state.state == DictationState.ERROR:
            self.clear_error()
        if self.state.state != DictationState.IDLE:
            self.tray.set_state(self.state.state.value, "busy")
            return

        self.sync_style_for_current_app()
        self.state.state = DictationState.RECORDING
        self.tray.set_state(DictationState.RECORDING.value)
        asyncio.run_coroutine_threadsafe(self._run_pipeline(), self.loop)

    def stop_dictation(self) -> None:
        if self.state.state == DictationState.RECORDING:
            self.recorder.stop()

    def select_style(self, style_id: str) -> None:
        if not self.style_bindings.select(style_id):
            self._show_error(RuntimeError(f"style not found: {style_id}"))
            return
        self.bind_current_style_to_app(show_state=False)
        self._sync_style_menu()
        self.update_app_binding_summary(self.style_bindings.last_target_app)
        self.tray.set_state(self.state.state.value, f"style: {self.styles.get(style_id).label}")

    def reload_styles(self) -> None:
        self.style_bindings.reload_styles()
        self._sync_style_menu()
        self.update_app_binding_summary()
        self.tray.set_state(self.state.state.value, "已重新加载提示词")

    def reveal_prompts_dir(self) -> None:
        self.styles.prompts_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(self.styles.prompts_dir)], check=False)

    def open_config_file(self) -> None:
        path = Path("config.toml")
        if not path.exists():
            self.config.save(path)
        subprocess.run(["open", str(path)], check=False)
        self.tray.set_state(self.state.state.value, "已打开配置文件")

    def reload_config(self) -> None:
        self.apply_config(AppConfig.load(), persist=False)
        self.tray.set_state(self.state.state.value, "已重新加载配置")

    def refresh_input_devices(self) -> None:
        devices = self.recorder.input_devices()
        self.tray.set_input_devices(devices, self.recorder.input_device)

    def select_input_device(self, device_id: str) -> None:
        updated_audio = self.config.audio.model_copy(update={"input_device": device_id})
        self.apply_config(self.config.model_copy(update={"audio": updated_audio}), persist=True)
        self.tray.set_state(
            self.state.state.value,
            f"输入来源：{self.recorder.current_input_label()}",
        )

    def bind_current_style_to_app(self, *, show_state: bool = True) -> None:
        update = self.style_bindings.bind_current_style(self.app_provider.current_app())
        if update.config is None:
            if show_state:
                self.tray.set_state(self.state.state.value, "未识别当前应用")
            return
        self.apply_config(update.config, persist=True)
        style = self.styles.get(self.style_bindings.current_style_id)
        self.update_app_binding_summary(update.app)
        if show_state:
            self.tray.set_state(
                self.state.state.value,
                f"{update.app.app_name or update.app.bundle_id} -> {style.label}",
            )

    def clear_current_app_style(self) -> None:
        update = self.style_bindings.clear_current_app_style(self.app_provider.current_app())
        if update.config is None:
            self.tray.set_state(self.state.state.value, "未识别当前应用")
            return
        self.apply_config(update.config, persist=True)
        self.style_bindings.current_style_id = self.style_bindings.default_style_id()
        self._sync_style_menu()
        self.update_app_binding_summary(update.app)
        detail = "已清除当前应用绑定" if update.removed else "当前应用没有绑定"
        self.tray.set_state(self.state.state.value, detail)

    def sync_style_for_current_app(self) -> None:
        sync = self.style_bindings.sync_for_app(self.app_provider.current_app())
        if sync.warning:
            self.tray.set_state(self.state.state.value, sync.warning)
        self._sync_style_menu()
        self.tray.set_app_binding_summary(sync.summary)

    def copy_history_raw(self, record_id: str) -> None:
        self.copy_history_text(record_id, "raw_text", "已复制原始转写")

    def copy_history_final(self, record_id: str) -> None:
        self.copy_history_text(record_id, "final_text", "已复制润色结果")

    def copy_history_text(self, record_id: str, field: str, detail: str) -> None:
        record = self.history_store.get(record_id)
        if record is None:
            self.tray.set_state(self.state.state.value, "历史记录不存在")
            return
        self._copy_to_pasteboard(str(record.get(field, "")))
        self.tray.set_state(self.state.state.value, detail)

    def copy_current_error(self) -> None:
        if self.state.current_error is None:
            self.tray.set_state(self.state.state.value, "暂无错误详情")
            return
        self._copy_to_pasteboard(self.state.current_error.copy_text())
        self.tray.set_state(self.state.state.value, "已复制错误详情")

    def clear_error(self) -> None:
        self.state.current_error = None
        self.tray.set_error_feedback(None)
        if self.state.state == DictationState.ERROR:
            self.state.state = DictationState.IDLE
            self.tray.set_state(DictationState.IDLE.value)

    def update_app_binding_summary(self, app: AppContext | None = None) -> None:
        app = app or self.app_provider.current_app()
        self.tray.set_app_binding_summary(self.style_bindings.summary_for(app))

    def apply_config(self, config: AppConfig, *, persist: bool = False) -> None:
        old_config = self.config
        self.config = config
        if persist:
            config.save()
        self.context_store.ttl = timedelta(seconds=config.context.ttl_seconds)
        self.context_store.max_items = config.context.max_items
        self.context_store.max_chars = CONTEXT_MAX_CHARS
        self.context_store.scope = CONTEXT_SCOPE
        self.styles = StyleRegistry(prompts_dir=config.style.prompts_dir)
        self.style_bindings.configure(config, styles=self.styles)
        self._sync_style_menu()
        self.update_app_binding_summary()
        self.tray.set_status_config(config.status)
        self.recorder.set_input_device(config.audio.input_device)
        self.refresh_input_devices()
        if (
            old_config.hotkey.toggle != config.hotkey.toggle
            or old_config.hotkey.mode != config.hotkey.mode
        ):
            self.hotkey.stop()
            self.hotkey = self._create_hotkey(config)
            self.hotkey.start()
            self.tray.hotkey_item.setTitle_(f"快捷键：{config.hotkey.toggle} ({config.hotkey.mode})")
        self.refresh_menu_summaries()

    def _create_hotkey(self, config: AppConfig) -> MacOSHotkeyService:
        hotkey = MacOSHotkeyService(config.hotkey.toggle, mode=config.hotkey.mode)
        if config.hotkey.mode == "hold":
            hotkey.on_press_release(self.start_dictation, self.stop_dictation)
        else:
            hotkey.on_toggle(self.toggle_dictation)
        return hotkey

    def refresh_menu_summaries(self) -> None:
        self.tray.set_stats(
            totals=self.history_store.totals(),
            app_stats=self.history_store.stats_by_app(),
        )
        self.tray.set_history_records(self.history_store.recent(limit=10))
        self.update_app_binding_summary()

    def _sync_style_menu(self) -> None:
        self.tray.set_styles(self.styles.all(), self.style_bindings.current_style_id)

    def quit(self) -> None:
        from AppKit import NSApp

        self.hotkey.stop()
        if self.state.state == DictationState.RECORDING:
            self.recorder.stop()
        future = asyncio.run_coroutine_threadsafe(self._close_clients(), self.loop)
        try:
            future.result(timeout=2)
        except (TimeoutError, concurrent.futures.TimeoutError):
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        NSApp.terminate_(None)

    async def _run_pipeline(self) -> None:
        try:
            style = self.styles.get(self.style_bindings.current_style_id)
            pipeline = DictationPipeline(
                dependencies=DictationDependencies(
                    recorder=self.recorder,
                    asr=self.asr_provider,
                    llm=self.llm_provider,
                    inserter=MacOSTextInserter(
                        mode=INSERT_MODE,
                        fallback=INSERT_FALLBACK,
                        restore_delay_ms=INSERT_RESTORE_DELAY_MS,
                    ),
                    app_provider=self.app_provider,
                    context_store=self.context_store,
                    tray=self.tray_proxy,
                ),
                options=DictationOptions(
                    style=style.id,
                    prompt_instruction=style.prompt,
                    context_enabled=self.config.context.enabled,
                ),
            )
            result = await pipeline.run_once()
            self.history_store.add(result.record, audio_seconds=result.audio_seconds)
            self.refresh_menu_summaries()
        except DictationPipelineError as exc:
            if exc.record is not None:
                self.history_store.add(exc.record, audio_seconds=exc.audio_seconds)
                self.refresh_menu_summaries()
            self._show_error(exc, raw_text_saved=exc.record is not None)
        except Exception as exc:
            self._show_error(exc)
        finally:
            if self.state.state != DictationState.ERROR:
                self.tray_proxy.set_state(DictationState.IDLE.value)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _update_permission_state(self) -> None:
        if not self.permissions.accessibility_trusted(prompt=True):
            self._show_error(RuntimeError("grant Accessibility permission"))

    async def _close_clients(self) -> None:
        await self.asr_provider.aclose()
        await self.llm_provider.aclose()

    def _copy_to_pasteboard(self, text: str) -> None:
        from AppKit import NSPasteboard, NSPasteboardTypeString

        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(text, NSPasteboardTypeString)

    def _show_error(self, exc: Exception, *, raw_text_saved: bool = False) -> None:
        feedback = feedback_from_exception(exc, raw_text_saved=raw_text_saved)
        self.state.current_error = feedback
        self.tray_proxy.set_error_feedback(feedback)
        self.tray_proxy.set_state(DictationState.ERROR.value, feedback.tooltip)


class _StateTrackingTray:
    def __init__(self, runtime: MacOSDictationRuntime) -> None:
        self.runtime = runtime

    def set_state(self, state: str, detail: str = "") -> None:
        try:
            self.runtime.state.state = DictationState(state)
        except ValueError:
            pass
        self.runtime.tray.set_state(state, detail)

    def set_error_feedback(self, feedback: ErrorFeedback | None) -> None:
        self.runtime.state.current_error = feedback
        self.runtime.tray.set_error_feedback(feedback)
