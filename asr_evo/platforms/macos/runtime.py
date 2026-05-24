from __future__ import annotations

import asyncio
import concurrent.futures
import sys
import threading
from dataclasses import dataclass
from datetime import timedelta

from asr_evo.config import AppConfig
from asr_evo.core.context import ContextStore
from asr_evo.core.pipeline import DictationPipeline
from asr_evo.core.state import DictationState
from asr_evo.postprocess.styles import StyleRegistry
from asr_evo.platforms.macos.frontmost import MacOSFrontmostAppProvider
from asr_evo.platforms.macos.hotkey import MacOSHotkeyService
from asr_evo.platforms.macos.inserter import MacOSTextInserter
from asr_evo.platforms.macos.permissions import MacOSPermissions
from asr_evo.platforms.macos.recorder import SoundDeviceRecorder
from asr_evo.platforms.macos.tray import MacOSStatusTray
from asr_evo.platforms.macos.windows import HistoryWindow, SettingsWindow
from asr_evo.providers.factory import create_asr_provider, create_llm_provider
from asr_evo.storage.history import HistoryStore


@dataclass
class RuntimeState:
    state: DictationState = DictationState.IDLE
    task: asyncio.Future | None = None


class MacOSDictationRuntime:
    def __init__(self, config: AppConfig) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("The macOS runtime can only run on macOS")

        self.config = config
        self.state = RuntimeState()
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._run_loop, name="asr-evo-async", daemon=True)
        self.styles = StyleRegistry(prompts_dir=config.style.prompts_dir)
        self.current_style_id = (
            config.style.mode if self.styles.has(config.style.mode) else "polished"
        )

        self.recorder = SoundDeviceRecorder(
            sample_rate=config.audio.sample_rate,
            channels=config.audio.channels,
        )
        self.context_store = ContextStore(
            ttl_seconds=config.context.ttl_seconds,
            max_items=config.context.max_items,
            max_chars=config.context.max_chars,
            scope=config.context.scope.value,
        )
        self.asr_provider = create_asr_provider(self.config)
        self.llm_provider = create_llm_provider(self.config)
        self.history_store = (
            HistoryStore(config.storage.database_path) if config.storage.enabled else None
        )
        self.settings_window = None
        self.history_window = None
        self.tray = MacOSStatusTray(
            hotkey_label=config.hotkey.toggle,
            styles=self.styles.all(),
            selected_style_id=self.current_style_id,
            on_toggle=self.toggle_dictation,
            on_select_style=self.select_style,
            on_reload_styles=self.reload_styles,
            on_open_settings=self.open_settings,
            on_open_history=self.open_history,
            on_quit=self.quit,
        )
        self.tray_proxy = _StateTrackingTray(self)
        self.hotkey = MacOSHotkeyService(config.hotkey.toggle)
        self.hotkey.on_toggle(self.toggle_dictation)
        self.permissions = MacOSPermissions()

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
            self.recorder.stop()
            return
        if self.state.state != DictationState.IDLE:
            self.tray.set_state(self.state.state.value, "busy")
            return

        self.state.state = DictationState.RECORDING
        self.tray.set_state(DictationState.RECORDING.value)
        future = asyncio.run_coroutine_threadsafe(self._run_pipeline(), self.loop)
        self.state.task = future

    def select_style(self, style_id: str) -> None:
        if not self.styles.has(style_id):
            self.reload_styles()
            if not self.styles.has(style_id):
                self.tray.set_state(DictationState.ERROR.value, f"style not found: {style_id}")
                return
        self.current_style_id = style_id
        self.tray.set_styles(self.styles.all(), self.current_style_id)
        self.tray.set_state(self.state.state.value, f"style: {self.styles.get(style_id).label}")

    def reload_styles(self) -> None:
        self.styles.reload()
        if not self.styles.has(self.current_style_id):
            self.current_style_id = "polished"
        self.tray.set_styles(self.styles.all(), self.current_style_id)

    def open_settings(self) -> None:
        self.settings_window = SettingsWindow(
            config=self.config,
            on_saved=self.apply_config,
        )
        self.settings_window.show()

    def open_history(self) -> None:
        if self.history_store is None:
            self.tray.set_state(self.state.state.value, "历史存储未启用")
            return
        self.history_window = HistoryWindow(self.history_store)
        self.history_window.show()

    def apply_config(self, config: AppConfig) -> None:
        self.config = config
        self.context_store.ttl = timedelta(seconds=config.context.ttl_seconds)
        self.context_store.max_items = config.context.max_items
        self.context_store.max_chars = config.context.max_chars
        self.context_store.scope = config.context.scope.value
        self.styles = StyleRegistry(prompts_dir=config.style.prompts_dir)
        if not self.styles.has(self.current_style_id):
            self.current_style_id = config.style.mode if self.styles.has(config.style.mode) else "polished"
        self.tray.set_styles(self.styles.all(), self.current_style_id)
        if config.storage.enabled and self.history_store is None:
            self.history_store = HistoryStore(config.storage.database_path)

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
            style = self.styles.get(self.current_style_id)
            pipeline = DictationPipeline(
                recorder=self.recorder,
                asr=self.asr_provider,
                llm=self.llm_provider,
                inserter=MacOSTextInserter(
                    mode=self.config.insert.mode,
                    fallback=self.config.insert.fallback,
                    restore_delay_ms=self.config.insert.restore_delay_ms,
                ),
                app_provider=MacOSFrontmostAppProvider(),
                context_store=self.context_store,
                tray=self.tray_proxy,
                style=style.id,
                custom_prompt=self.config.style.custom_prompt or style.prompt,
                context_enabled=self.config.context.enabled,
            )
            result = await pipeline.run_once()
            if self.history_store is not None:
                self.history_store.add(result.record, audio_seconds=result.audio_seconds)
        except Exception as exc:
            self.tray_proxy.set_state(DictationState.ERROR.value, str(exc))
        finally:
            if self.state.state != DictationState.ERROR:
                self.tray_proxy.set_state(DictationState.IDLE.value)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _update_permission_state(self) -> None:
        if not self.permissions.accessibility_trusted(prompt=True):
            self.tray_proxy.set_state(DictationState.ERROR.value, "grant Accessibility permission")

    async def _close_clients(self) -> None:
        await self.asr_provider.aclose()
        await self.llm_provider.aclose()


class _StateTrackingTray:
    def __init__(self, runtime: MacOSDictationRuntime) -> None:
        self.runtime = runtime

    def set_state(self, state: str, detail: str = "") -> None:
        try:
            self.runtime.state.state = DictationState(state)
        except ValueError:
            pass
        self.runtime.tray.set_state(state, detail)
