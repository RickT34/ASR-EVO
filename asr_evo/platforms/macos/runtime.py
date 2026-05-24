from __future__ import annotations

import asyncio
import concurrent.futures
import subprocess
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
        self.tray = MacOSStatusTray(
            hotkey_label=config.hotkey.toggle,
            status_config=config.status,
            styles=self.styles.all(),
            selected_style_id=self.current_style_id,
            on_toggle=self.toggle_dictation,
            on_select_style=self.select_style,
            on_reload_styles=self.reload_styles,
            on_set_context_ttl=self.set_context_ttl,
            on_set_context_items=self.set_context_items,
            on_set_hotkey_preset=self.set_hotkey_preset,
            on_new_prompt=self.new_prompt_template,
            on_delete_prompt=self.delete_current_prompt,
            on_reveal_prompts=self.reveal_prompts_dir,
            on_reload_config=self.reload_config,
            on_refresh_stats=self.refresh_menu_summaries,
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
        self.tray.set_styles(self.styles.all(), self.current_style_id)
        self.tray.set_state(self.state.state.value, f"style: {self.styles.get(style_id).label}")

    def reload_styles(self) -> None:
        self.styles.reload()
        if not self.styles.has(self.current_style_id):
            self.current_style_id = "polished"
        self.tray.set_styles(self.styles.all(), self.current_style_id)
        self.update_prompt_preview()
        self.tray.set_state(self.state.state.value, "已重新加载提示词")

    def set_context_ttl(self, seconds: int) -> None:
        config = self.config.model_copy(deep=True)
        config.context.ttl_seconds = seconds
        self.apply_config(config, persist=True)

    def set_context_items(self, count: int) -> None:
        config = self.config.model_copy(deep=True)
        config.context.max_items = count
        self.apply_config(config, persist=True)

    def set_hotkey_preset(self, hotkey: str, mode: str) -> None:
        config = self.config.model_copy(deep=True)
        config.hotkey.toggle = hotkey
        config.hotkey.mode = mode
        self.apply_config(config, persist=True)

    def new_prompt_template(self) -> None:
        prompts_dir = self.styles.prompts_dir
        prompts_dir.mkdir(parents=True, exist_ok=True)
        path = prompts_dir / "新提示词.txt"
        index = 1
        while path.exists():
            index += 1
            path = prompts_dir / f"新提示词 {index}.txt"
        path.write_text(
            "请将听写内容整理为自然、清楚的中文。\n"
            "保留专有名词、技术术语和代码标识符。\n"
            "只输出最终文本。\n",
            encoding="utf-8",
        )
        self.reload_styles()
        self.tray.set_state(self.state.state.value, f"已创建：{path.name}")

    def delete_current_prompt(self) -> None:
        from pathlib import Path

        style = self.styles.get(self.current_style_id)
        if style.source == "built-in":
            self.tray.set_state(self.state.state.value, "内置提示词不能删除")
            return
        path = Path(style.source)
        if path.exists():
            path.unlink()
        self.current_style_id = "polished"
        self.reload_styles()
        self.tray.set_state(self.state.state.value, f"已删除：{style.label}")

    def reveal_prompts_dir(self) -> None:
        self.styles.prompts_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(self.styles.prompts_dir)], check=False)

    def reload_config(self) -> None:
        self.apply_config(AppConfig.load(), persist=False)
        self.tray.set_state(self.state.state.value, "已重新加载配置")

    def update_prompt_preview(self) -> None:
        style = self.styles.get(self.current_style_id)
        self.tray.set_prompt_preview(label=style.label, prompt=style.prompt)
        self.tray.set_delete_prompt_enabled(style.source != "built-in")

    def apply_config(self, config: AppConfig, *, persist: bool = False) -> None:
        old_config = self.config
        self.config = config
        if persist:
            config.save()
        self.context_store.ttl = timedelta(seconds=config.context.ttl_seconds)
        self.context_store.max_items = config.context.max_items
        self.context_store.max_chars = config.context.max_chars
        self.context_store.scope = config.context.scope.value
        self.styles = StyleRegistry(prompts_dir=config.style.prompts_dir)
        if not self.styles.has(self.current_style_id):
            self.current_style_id = config.style.mode if self.styles.has(config.style.mode) else "polished"
        self.tray.set_styles(self.styles.all(), self.current_style_id)
        self.update_prompt_preview()
        self.tray.set_status_config(config.status)
        if (
            old_config.hotkey.toggle != config.hotkey.toggle
            or old_config.hotkey.mode != config.hotkey.mode
        ):
            self.hotkey.stop()
            self.hotkey = self._create_hotkey(config)
            self.hotkey.start()
            self.tray.hotkey_item.setTitle_(f"快捷键：{config.hotkey.toggle} ({config.hotkey.mode})")
        if not config.storage.enabled:
            self.history_store = None
        elif (
            self.history_store is None
            or old_config.storage.database_path != config.storage.database_path
        ):
            self.history_store = HistoryStore(config.storage.database_path)
        self.refresh_menu_summaries()

    def _create_hotkey(self, config: AppConfig) -> MacOSHotkeyService:
        hotkey = MacOSHotkeyService(config.hotkey.toggle, mode=config.hotkey.mode)
        if config.hotkey.mode == "hold":
            hotkey.on_press_release(self.start_dictation, self.stop_dictation)
        else:
            hotkey.on_toggle(self.toggle_dictation)
        return hotkey

    def refresh_menu_summaries(self) -> None:
        self.tray.set_settings_summary(
            hotkey=self.config.hotkey.toggle,
            hotkey_mode=self.config.hotkey.mode,
            ttl_seconds=self.config.context.ttl_seconds,
            max_items=self.config.context.max_items,
            storage_enabled=self.config.storage.enabled,
            database_path=self.config.storage.database_path,
        )
        if self.history_store is not None:
            self.tray.set_stats(
                totals=self.history_store.totals(),
                app_stats=self.history_store.stats_by_app(),
            )
        else:
            self.tray.set_stats(
                totals={"count": 0, "total_chars": 0, "total_audio_seconds": 0},
                app_stats=[],
            )
        self.update_prompt_preview()

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
                self.refresh_menu_summaries()
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
