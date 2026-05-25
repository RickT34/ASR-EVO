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
    STORAGE_ENABLED,
    AppConfig,
)
from asr_evo.core.context import ContextStore
from asr_evo.core.pipeline import DictationPipeline, DictationPipelineError
from asr_evo.core.ports import AppContext
from asr_evo.core.state import DictationState
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
        self.current_style_id = self._default_style_id()
        self._last_target_app = AppContext()

        self.recorder = SoundDeviceRecorder(
            sample_rate=AUDIO_SAMPLE_RATE,
            channels=AUDIO_CHANNELS,
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
        self.history_store = (
            HistoryStore(STORAGE_DATABASE_PATH) if STORAGE_ENABLED else None
        )
        self.tray = MacOSStatusTray(
            hotkey_label=config.hotkey.toggle,
            status_config=config.status,
            styles=self.styles.all(),
            selected_style_id=self.current_style_id,
            on_select_style=self.select_style,
            on_reveal_prompts=self.reveal_prompts_dir,
            on_reload_config=self.reload_config,
            on_open_config=self.open_config_file,
            on_clear_app_style=self.clear_current_app_style,
            on_refresh_app_binding=self.sync_style_for_current_app,
            on_refresh_stats=self.refresh_menu_summaries,
            on_copy_history_raw=self.copy_history_raw,
            on_copy_history_final=self.copy_history_final,
            on_quit=self.quit,
        )
        self.tray_proxy = _StateTrackingTray(self)
        self.hotkey = self._create_hotkey(config)
        self.permissions = MacOSPermissions()
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
        if self.state.state != DictationState.IDLE:
            self.tray.set_state(self.state.state.value, "busy")
            return

        self.sync_style_for_current_app()
        self.state.state = DictationState.RECORDING
        self.tray.set_state(DictationState.RECORDING.value)
        future = asyncio.run_coroutine_threadsafe(self._run_pipeline(), self.loop)
        self.state.task = future

    def stop_dictation(self) -> None:
        if self.state.state == DictationState.RECORDING:
            self.recorder.stop()

    def select_style(self, style_id: str) -> None:
        if not self.styles.has(style_id):
            self.reload_styles()
            if not self.styles.has(style_id):
                self.tray.set_state(DictationState.ERROR.value, f"style not found: {style_id}")
                return
        self.current_style_id = style_id
        self.bind_current_style_to_app(show_state=False)
        self.tray.set_styles(self.styles.all(), self.current_style_id)
        self.update_app_binding_summary(self._last_target_app)
        self.tray.set_state(self.state.state.value, f"style: {self.styles.get(style_id).label}")

    def reload_styles(self) -> None:
        self.styles.reload()
        if not self.styles.has(self.current_style_id):
            self.current_style_id = self._default_style_id()
        self.tray.set_styles(self.styles.all(), self.current_style_id)
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

    def bind_current_style_to_app(self, *, show_state: bool = True) -> None:
        app = self._target_app_context()
        if not app.bundle_id:
            if show_state:
                self.tray.set_state(self.state.state.value, "未识别当前应用")
            return
        config = self.config.model_copy(deep=True)
        config.style.app_styles[app.bundle_id] = self.current_style_id
        self.apply_config(config, persist=True)
        style = self.styles.get(self.current_style_id)
        self.update_app_binding_summary(app)
        if show_state:
            self.tray.set_state(self.state.state.value, f"{app.app_name or app.bundle_id} -> {style.label}")

    def clear_current_app_style(self) -> None:
        app = self._target_app_context()
        if not app.bundle_id:
            self.tray.set_state(self.state.state.value, "未识别当前应用")
            return
        config = self.config.model_copy(deep=True)
        removed = config.style.app_styles.pop(app.bundle_id, None)
        self.apply_config(config, persist=True)
        self.current_style_id = self._default_style_id()
        self.tray.set_styles(self.styles.all(), self.current_style_id)
        self.update_app_binding_summary(app)
        detail = "已清除当前应用绑定" if removed else "当前应用没有绑定"
        self.tray.set_state(self.state.state.value, detail)

    def sync_style_for_current_app(self) -> None:
        app = self._capture_current_app()
        if not app.bundle_id:
            self.current_style_id = self._default_style_id()
            self.tray.set_styles(self.styles.all(), self.current_style_id)
            self.update_app_binding_summary(app)
            return
        style_id = self.config.style.app_styles.get(app.bundle_id) or self._default_style_id()
        if not self.styles.has(style_id):
            self.tray.set_state(self.state.state.value, f"应用绑定的风格不存在：{style_id}")
            self.current_style_id = self._default_style_id()
            self.tray.set_styles(self.styles.all(), self.current_style_id)
            self.update_app_binding_summary(app)
            return
        if self.current_style_id != style_id:
            self.current_style_id = style_id
        self.tray.set_styles(self.styles.all(), self.current_style_id)
        self.update_app_binding_summary(app)

    def copy_history_raw(self, record_id: str) -> None:
        self.copy_history_text(record_id, "raw_text", "已复制原始转写")

    def copy_history_final(self, record_id: str) -> None:
        self.copy_history_text(record_id, "final_text", "已复制润色结果")

    def copy_history_text(self, record_id: str, field: str, detail: str) -> None:
        if self.history_store is None:
            self.tray.set_state(self.state.state.value, "持久化历史未开启")
            return
        record = self.history_store.get(record_id)
        if record is None:
            self.tray.set_state(self.state.state.value, "历史记录不存在")
            return
        self._copy_to_pasteboard(str(record.get(field, "")))
        self.tray.set_state(self.state.state.value, detail)

    def update_app_binding_summary(self, app: AppContext | None = None) -> None:
        app = app or self._capture_current_app()
        if not app.bundle_id:
            self.tray.set_app_binding_summary("当前应用绑定：未识别当前应用")
            return
        style_id = self.config.style.app_styles.get(app.bundle_id)
        app_name = app.app_name or app.bundle_id
        if not style_id:
            self.tray.set_app_binding_summary(f"当前应用绑定：{app_name} 未绑定")
            return
        if self.styles.has(style_id):
            label = self.styles.get(style_id).label
        else:
            label = f"{style_id}（不存在）"
        self.tray.set_app_binding_summary(f"当前应用绑定：{app_name} -> {label}")

    def _default_style_id(self) -> str:
        return self.config.style.mode if self.styles.has(self.config.style.mode) else self.styles.default_style_id()

    def _capture_current_app(self) -> AppContext:
        app = self.app_provider.current_app()
        if app.bundle_id:
            self._last_target_app = app
        return app

    def _target_app_context(self) -> AppContext:
        app = self.app_provider.current_app()
        if app.bundle_id:
            self._last_target_app = app
            return app
        return self._last_target_app

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
        if not self.styles.has(self.current_style_id):
            self.current_style_id = self._default_style_id()
        self.tray.set_styles(self.styles.all(), self.current_style_id)
        self.update_app_binding_summary()
        self.tray.set_status_config(config.status)
        if (
            old_config.hotkey.toggle != config.hotkey.toggle
            or old_config.hotkey.mode != config.hotkey.mode
        ):
            self.hotkey.stop()
            self.hotkey = self._create_hotkey(config)
            self.hotkey.start()
            self.tray.hotkey_item.setTitle_(f"快捷键：{config.hotkey.toggle} ({config.hotkey.mode})")
        if not STORAGE_ENABLED:
            self.history_store = None
        elif self.history_store is None:
            self.history_store = HistoryStore(STORAGE_DATABASE_PATH)
        self.refresh_menu_summaries()

    def _create_hotkey(self, config: AppConfig) -> MacOSHotkeyService:
        hotkey = MacOSHotkeyService(config.hotkey.toggle, mode=config.hotkey.mode)
        if config.hotkey.mode == "hold":
            hotkey.on_press_release(self.start_dictation, self.stop_dictation)
        else:
            hotkey.on_toggle(self.toggle_dictation)
        return hotkey

    def refresh_menu_summaries(self) -> None:
        if self.history_store is not None:
            self.tray.set_stats(
                totals=self.history_store.totals(),
                app_stats=self.history_store.stats_by_app(),
            )
            self.tray.set_history_records(self.history_store.recent(limit=10))
        else:
            self.tray.set_stats(
                totals={"count": 0, "total_chars": 0, "total_audio_seconds": 0},
                app_stats=[],
            )
            self.tray.set_history_records([])
        self.update_app_binding_summary()

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
                    mode=INSERT_MODE,
                    fallback=INSERT_FALLBACK,
                    restore_delay_ms=INSERT_RESTORE_DELAY_MS,
                ),
                app_provider=self.app_provider,
                context_store=self.context_store,
                tray=self.tray_proxy,
                style=style.id,
                prompt_instruction=style.prompt,
                context_enabled=self.config.context.enabled,
            )
            result = await pipeline.run_once()
            if self.history_store is not None:
                self.history_store.add(result.record, audio_seconds=result.audio_seconds)
                self.refresh_menu_summaries()
        except DictationPipelineError as exc:
            if self.history_store is not None and exc.record is not None:
                self.history_store.add(exc.record, audio_seconds=exc.audio_seconds)
                self.refresh_menu_summaries()
            self.tray_proxy.set_state(DictationState.ERROR.value, str(exc))
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

    def _copy_to_pasteboard(self, text: str) -> None:
        from AppKit import NSPasteboard, NSPasteboardTypeString

        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(text, NSPasteboardTypeString)


class _StateTrackingTray:
    def __init__(self, runtime: MacOSDictationRuntime) -> None:
        self.runtime = runtime

    def set_state(self, state: str, detail: str = "") -> None:
        try:
            self.runtime.state.state = DictationState(state)
        except ValueError:
            pass
        self.runtime.tray.set_state(state, detail)
