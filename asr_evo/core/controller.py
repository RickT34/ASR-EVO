from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from asr_evo.config import AppConfig
from asr_evo.core.context import ContextStore
from asr_evo.core.control import CONTROL_COMMANDS, ControlResult
from asr_evo.core.errors import ErrorFeedback, PermissionDeniedError, feedback_from_exception
from asr_evo.core.pipeline import (
    DictationDependencies,
    DictationOptions,
    DictationPipeline,
    DictationPipelineError,
)
from asr_evo.core.ports import (
    AppContext,
    AppLifecycle,
    ASRProvider,
    Clipboard,
    DesktopRecorder,
    FileOpener,
    FrontmostAppProvider,
    HistoryRepository,
    LLMProvider,
    PermissionChecker,
    StatusTray,
    TextInserter,
    TextReviewer,
)
from asr_evo.core.state import DictationState
from asr_evo.core.style_binding import StyleBindingService
from asr_evo.postprocess.styles import StyleRegistry
from asr_evo.ui.menu import TrayMenuActions


@dataclass
class RuntimeState:
    state: DictationState = DictationState.IDLE
    current_error: ErrorFeedback | None = None


@dataclass(frozen=True)
class DesktopControllerDependencies:
    tray: StatusTray
    recorder: DesktopRecorder
    asr_provider: ASRProvider
    llm_provider: LLMProvider
    inserter: TextInserter
    text_reviewer: TextReviewer
    app_provider: FrontmostAppProvider
    history_store: HistoryRepository
    context_store: ContextStore
    clipboard: Clipboard
    file_opener: FileOpener
    permissions: PermissionChecker
    lifecycle: AppLifecycle
    config_loader: Callable[[], AppConfig] = AppConfig.load
    config_path: Path = Path("config.toml")
    on_config_applied: Callable[[AppConfig], None] | None = None


class DesktopDictationController:
    def __init__(
        self,
        *,
        config: AppConfig,
        dependencies: DesktopControllerDependencies,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.config = config
        self.dependencies = dependencies
        self.loop = loop
        self.state = RuntimeState()
        self.styles = StyleRegistry(prompts_dir=config.style.prompts_dir)
        self.style_bindings = StyleBindingService(config=config, styles=self.styles)

    def tray_actions(self) -> TrayMenuActions:
        return TrayMenuActions(
            toggle_review=self.toggle_review,
            select_style=self.select_style,
            reveal_prompts=self.reveal_prompts_dir,
            reload_config=self.reload_config,
            open_config=self.open_config_file,
            refresh_input_devices=self.refresh_input_devices,
            select_input_device=self.select_input_device,
            clear_app_style=self.clear_current_app_style,
            refresh_app_binding=self.sync_style_for_current_app,
            refresh_stats=self.refresh_menu_summaries,
            copy_history_raw=self.copy_history_raw,
            copy_history_final=self.copy_history_final,
            copy_history_user_edit=self.copy_history_user_edit,
            copy_error=self.copy_current_error,
            clear_error=self.clear_error,
            quit=self.quit,
        )

    def initialize_tray(self) -> None:
        self._sync_style_menu()
        self.refresh_input_devices()
        self.refresh_menu_summaries()

    def check_permissions(self) -> None:
        if not self.dependencies.permissions.accessibility_trusted(prompt=True):
            error_factory = getattr(self.dependencies.permissions, "accessibility_error", None)
            if error_factory is None:
                self._show_error(
                    PermissionDeniedError("当前进程没有控制键盘或插入文本所需的系统权限。")
                )
            else:
                self._show_error(error_factory())

    def toggle_dictation(self) -> None:
        if self.state.state == DictationState.RECORDING:
            self.stop_dictation()
            return
        self.start_dictation()

    def start_dictation(self) -> None:
        if self.state.state == DictationState.ERROR:
            self.clear_error()
        if self.state.state != DictationState.IDLE:
            self.dependencies.tray.set_state(self.state.state.value, "busy")
            return

        self.sync_style_for_current_app()
        self.state.state = DictationState.RECORDING
        self.dependencies.tray.set_state(DictationState.RECORDING.value)
        asyncio.run_coroutine_threadsafe(self.run_pipeline_once(), self.loop)

    def stop_dictation(self) -> None:
        if self.state.state == DictationState.RECORDING:
            self.dependencies.recorder.stop()

    def handle_control_command(self, command: str) -> ControlResult:
        if command not in CONTROL_COMMANDS:
            return ControlResult(
                ok=False,
                state=self.state.state.value,
                error=f"unsupported command: {command}",
            )
        if command == "start":
            self.start_dictation()
        elif command == "stop":
            self.stop_dictation()
        elif command == "toggle":
            self.toggle_dictation()
        return ControlResult(ok=True, state=self.state.state.value)

    def select_style(self, style_id: str) -> None:
        if not self.style_bindings.select(style_id):
            self._show_error(RuntimeError(f"style not found: {style_id}"))
            return
        self.bind_current_style_to_app(show_state=False)
        self._sync_style_menu()
        self.update_app_binding_summary(self.style_bindings.last_target_app)
        self.dependencies.tray.set_state(
            self.state.state.value,
            f"style: {self.styles.get(style_id).label}",
        )

    def reload_styles(self) -> None:
        self.style_bindings.reload_styles()
        self._sync_style_menu()
        self.update_app_binding_summary()
        self.dependencies.tray.set_state(self.state.state.value, "已重新加载提示词")

    def reveal_prompts_dir(self) -> None:
        self.styles.prompts_dir.mkdir(parents=True, exist_ok=True)
        self.dependencies.file_opener.open_path(self.styles.prompts_dir)

    def open_config_file(self) -> None:
        if not self.dependencies.config_path.exists():
            self.config.save(self.dependencies.config_path)
        self.dependencies.file_opener.open_path(self.dependencies.config_path)
        self.dependencies.tray.set_state(self.state.state.value, "已打开配置文件")

    def toggle_review(self) -> None:
        enabled = not self.config.review.enabled
        self.apply_config(
            self.config.model_copy(update={"review": self.config.review.model_copy(update={"enabled": enabled})}),
            persist=True,
        )
        detail = "已开启插入前确认" if enabled else "已关闭插入前确认"
        self.dependencies.tray.set_state(self.state.state.value, detail)

    def reload_config(self) -> None:
        self.apply_config(self.dependencies.config_loader(), persist=False)
        self.dependencies.tray.set_state(self.state.state.value, "已重新加载配置")

    def refresh_input_devices(self) -> None:
        devices = self.dependencies.recorder.input_devices()
        self.dependencies.tray.set_input_devices(devices, self.dependencies.recorder.input_device)

    def select_input_device(self, device_id: str) -> None:
        updated_audio = self.config.audio.model_copy(update={"input_device": device_id})
        self.apply_config(self.config.model_copy(update={"audio": updated_audio}), persist=True)
        self.dependencies.tray.set_state(
            self.state.state.value,
            f"输入来源：{self.dependencies.recorder.current_input_label()}",
        )

    def bind_current_style_to_app(self, *, show_state: bool = True) -> None:
        update = self.style_bindings.bind_current_style(self.dependencies.app_provider.current_app())
        if update.config is None:
            if show_state:
                self.dependencies.tray.set_state(self.state.state.value, "未识别当前应用")
            return
        self.apply_config(update.config, persist=True)
        style = self.styles.get(self.style_bindings.current_style_id)
        self.update_app_binding_summary(update.app)
        if show_state:
            self.dependencies.tray.set_state(
                self.state.state.value,
                f"{update.app.app_name or update.app.bundle_id} -> {style.label}",
            )

    def clear_current_app_style(self) -> None:
        update = self.style_bindings.clear_current_app_style(
            self.dependencies.app_provider.current_app()
        )
        if update.config is None:
            self.dependencies.tray.set_state(self.state.state.value, "未识别当前应用")
            return
        self.apply_config(update.config, persist=True)
        self.style_bindings.current_style_id = self.style_bindings.default_style_id()
        self._sync_style_menu()
        self.update_app_binding_summary(update.app)
        detail = "已清除当前应用绑定" if update.removed else "当前应用没有绑定"
        self.dependencies.tray.set_state(self.state.state.value, detail)

    def sync_style_for_current_app(self) -> None:
        sync = self.style_bindings.sync_for_app(self.dependencies.app_provider.current_app())
        if sync.warning:
            self.dependencies.tray.set_state(self.state.state.value, sync.warning)
        self._sync_style_menu()
        self.dependencies.tray.set_app_binding_summary(sync.summary)

    def copy_history_raw(self, record_id: str) -> None:
        self.copy_history_text(record_id, "raw_text", "已复制原始转写")

    def copy_history_final(self, record_id: str) -> None:
        self.copy_history_text(record_id, "final_text", "已复制润色结果")

    def copy_history_user_edit(self, record_id: str) -> None:
        self.copy_history_text(record_id, "user_edited_text", "已复制用户修订")

    def copy_history_text(self, record_id: str, field: str, detail: str) -> None:
        record = self.dependencies.history_store.get(record_id)
        if record is None:
            self.dependencies.tray.set_state(self.state.state.value, "历史记录不存在")
            return
        self.dependencies.clipboard.copy_text(str(record.get(field, "")))
        self.dependencies.tray.set_state(self.state.state.value, detail)

    def copy_current_error(self) -> None:
        if self.state.current_error is None:
            self.dependencies.tray.set_state(self.state.state.value, "暂无错误详情")
            return
        self.dependencies.clipboard.copy_text(self.state.current_error.copy_text())
        self.dependencies.tray.set_state(self.state.state.value, "已复制错误详情")

    def clear_error(self) -> None:
        self.state.current_error = None
        self.dependencies.tray.set_error_feedback(None)
        if self.state.state == DictationState.ERROR:
            self.state.state = DictationState.IDLE
            self.dependencies.tray.set_state(DictationState.IDLE.value)

    def update_app_binding_summary(self, app: AppContext | None = None) -> None:
        app = app or self.dependencies.app_provider.current_app()
        self.dependencies.tray.set_app_binding_summary(self.style_bindings.summary_for(app))

    def apply_config(self, config: AppConfig, *, persist: bool = False) -> None:
        if self.dependencies.on_config_applied is not None:
            self.dependencies.on_config_applied(config)
        self.config = config
        if persist:
            config.save(self.dependencies.config_path)
        self.dependencies.context_store.ttl = timedelta(seconds=config.context.ttl_seconds)
        self.dependencies.context_store.max_items = config.context.max_items
        self.dependencies.context_store.max_chars = config.context.max_chars
        self.dependencies.context_store.scope = config.context.scope
        self.styles = StyleRegistry(prompts_dir=config.style.prompts_dir)
        self.style_bindings.configure(config, styles=self.styles)
        self._sync_style_menu()
        self.update_app_binding_summary()
        self.dependencies.tray.set_status_config(config.status)
        self.dependencies.tray.set_review_enabled(config.review.enabled)
        self.dependencies.recorder.set_input_device(config.audio.input_device)
        self.refresh_input_devices()
        self.refresh_menu_summaries()

    def refresh_menu_summaries(self) -> None:
        self.dependencies.tray.set_stats(
            totals=self.dependencies.history_store.totals(),
            app_stats=self.dependencies.history_store.stats_by_app(),
        )
        self.dependencies.tray.set_history_records(self.dependencies.history_store.recent(limit=10))
        self.update_app_binding_summary()

    def quit(self) -> None:
        if self.state.state == DictationState.RECORDING:
            self.dependencies.recorder.stop()
        future = asyncio.run_coroutine_threadsafe(self.close_clients(), self.loop)
        try:
            future.result(timeout=2)
        except (TimeoutError, concurrent.futures.TimeoutError):
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.dependencies.lifecycle.quit()

    async def run_pipeline_once(self) -> None:
        try:
            style = self.styles.get(self.style_bindings.current_style_id)
            pipeline = DictationPipeline(
                dependencies=DictationDependencies(
                    recorder=self.dependencies.recorder,
                    asr=self.dependencies.asr_provider,
                    llm=self.dependencies.llm_provider,
                    app_provider=self.dependencies.app_provider,
                    context_store=self.dependencies.context_store,
                    tray=_StateTrackingTray(self),
                    history_store=self.dependencies.history_store,
                ),
                options=DictationOptions(
                    style=style.id,
                    prompt_instruction=style.prompt,
                    context_enabled=self.config.context.enabled,
                ),
            )
            result = await pipeline.run_once()
            user_text = await self._review_text(result.final_text)
            if user_text is None:
                _StateTrackingTray(self).set_state(DictationState.IDLE.value, "已取消插入")
                return
            _StateTrackingTray(self).set_state(DictationState.INSERTING.value)
            result = result.with_user_text(user_text)
            await self.dependencies.inserter.insert(user_text)
            self.dependencies.history_store.add(result.record, audio_seconds=result.audio_seconds)
            self.refresh_menu_summaries()
        except DictationPipelineError as exc:
            if exc.record is not None:
                self.dependencies.history_store.add(exc.record, audio_seconds=exc.audio_seconds)
                self.refresh_menu_summaries()
            self._show_error(exc, raw_text_saved=exc.record is not None)
        except Exception as exc:
            self._show_error(exc)
        finally:
            if self.state.state != DictationState.ERROR:
                _StateTrackingTray(self).set_state(DictationState.IDLE.value)

    async def close_clients(self) -> None:
        await _maybe_aclose(self.dependencies.asr_provider)
        await _maybe_aclose(self.dependencies.llm_provider)

    def _sync_style_menu(self) -> None:
        self.dependencies.tray.set_styles(self.styles.all(), self.style_bindings.current_style_id)

    def _show_error(self, exc: Exception, *, raw_text_saved: bool = False) -> None:
        feedback = feedback_from_exception(exc, raw_text_saved=raw_text_saved)
        self.state.current_error = feedback
        _StateTrackingTray(self).set_error_feedback(feedback)
        _StateTrackingTray(self).set_state(DictationState.ERROR.value, feedback.tooltip)

    async def _review_text(self, text: str) -> str | None:
        if not self.config.review.enabled:
            return text
        _StateTrackingTray(self).set_state(DictationState.REVIEWING.value)
        return await self.dependencies.text_reviewer.review(text)


class _StateTrackingTray:
    def __init__(self, controller: DesktopDictationController) -> None:
        self.controller = controller

    def set_state(self, state: str, detail: str = "") -> None:
        try:
            self.controller.state.state = DictationState(state)
        except ValueError:
            pass
        self.controller.dependencies.tray.set_state(state, detail)

    def set_error_feedback(self, feedback: ErrorFeedback | None) -> None:
        self.controller.state.current_error = feedback
        self.controller.dependencies.tray.set_error_feedback(feedback)


async def _maybe_aclose(client: Any) -> None:
    close = getattr(client, "aclose", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result
