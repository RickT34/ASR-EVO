from __future__ import annotations

import asyncio
import signal
import threading
from dataclasses import replace

from asr_evo.audio.recorder import SoundDeviceRecorder
from asr_evo.config import AUDIO_DEFAULTS, STORAGE_DEFAULTS, AppConfig
from asr_evo.core.control import ControlResult, DictationControlServer
from asr_evo.core.controller import DesktopControllerDependencies, DesktopDictationController
from asr_evo.core.tray_proxy import UnboundStatusTray
from asr_evo.platforms.linux.desktop import LinuxDesktop, LinuxTextInserter
from asr_evo.platforms.linux.tray import LinuxStatusTray
from asr_evo.providers.factory import create_streaming_asr_provider, create_providers, provider_config_changed
from asr_evo.storage.history import HistoryStore
from asr_evo.ui.file_export import TkFileExporter
from asr_evo.ui.popup_menu import show_popup_menu
from asr_evo.ui.text_review import TkTextReviewer
from asr_evo.ui.microphone_test import show_microphone_test


class LinuxDictationRuntime:
    def __init__(self, config: AppConfig) -> None:
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._lock = threading.RLock()
        self._menu_future = None
        self.desktop = LinuxDesktop()
        self.inserter = LinuxTextInserter(self.desktop, config.linux)
        tray = UnboundStatusTray()
        asr, llm = create_providers(config)
        self.controller = DesktopDictationController(
            config=config,
            loop=self.loop,
            dependencies=DesktopControllerDependencies(
                tray=tray,
                recorder=SoundDeviceRecorder(
                    sample_rate=AUDIO_DEFAULTS.sample_rate,
                    channels=AUDIO_DEFAULTS.channels,
                    input_device=config.audio.input_device,
                    processing=config.audio.processing_options(),
                ),
                asr_provider=asr,
                llm_provider=llm,
                inserter=self.inserter,
                text_reviewer=TkTextReviewer(),
                microphone_tester=show_microphone_test,
                streaming_asr_factory=lambda: create_streaming_asr_provider(self.controller.config),
                app_provider=self.desktop,
                history_store=HistoryStore(STORAGE_DEFAULTS.database_path),
                context_store=config.context.store(),
                clipboard=self.desktop,
                file_opener=self.desktop,
                file_exporter=TkFileExporter(),
                permissions=self.desktop,
                lifecycle=self,
                on_config_applied=self.apply_config,
            ),
        )
        self.control_server = DictationControlServer(
            port=config.control.port,
            handler=self._handle_control_command,
        )
        self.tray = LinuxStatusTray(
            mode=config.linux.tray,
            control_label=self.control_server.address,
            status_config=config.status,
            styles=self.controller.styles.all(),
            selected_style_id=self.controller.style_bindings.current_style_id,
            actions=replace(self.controller.tray_actions(), quit=self.quit),
            on_toggle=lambda: self._handle_control_command("toggle"),
        )
        tray.bind(self.tray)
        self.tray.set_review_enabled(config.review.enabled)

    def run(self) -> None:
        self.loop_thread.start()
        previous_signals = {
            sig: signal.signal(sig, lambda *_: self.quit())
            for sig in (signal.SIGINT, signal.SIGTERM)
        }
        try:
            self.control_server.start(self.loop)
            self.controller.initialize_tray()
            self.controller.check_permissions()
            self.tray.run()
        finally:
            for sig, handler in previous_signals.items():
                signal.signal(sig, handler)
            try:
                asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop).result(timeout=15)
            finally:
                self.loop.call_soon_threadsafe(self.loop.stop)
                self.loop_thread.join(timeout=5)
                if not self.loop_thread.is_alive():
                    self.loop.close()

    async def _shutdown(self) -> None:
        await self.control_server.stop_async()
        self.controller.dependencies.recorder.stop()
        pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await self.controller.close_clients()

    def quit(self) -> None:
        self.tray.stop()

    def _handle_control_command(self, command: str) -> ControlResult:
        with self._lock:
            if command == "menu":
                if self._menu_future is None or self._menu_future.done():
                    menu = self.tray.popup_menu()
                    self._menu_future = asyncio.run_coroutine_threadsafe(
                        self._show_menu(menu),
                        self.loop,
                    )
                return ControlResult(ok=True, state=self.controller.state.state.value)
            if command in {"start", "toggle"} and self.controller.state.state.value in {
                "idle",
                "error",
            }:
                self.inserter.capture_target()
            result = self.controller.handle_control_command(command)
            return ControlResult(
                ok=result.ok,
                state=result.state,
                error=result.error,
                detail=self.tray.tooltip,
            )

    async def _show_menu(self, menu) -> None:
        try:
            await show_popup_menu(menu)
        except Exception as exc:
            self.controller._show_error(exc)

    def apply_config(self, config: AppConfig) -> None:
        if config.linux.tray != self.tray.mode:
            raise ValueError("Restart ASR-EVO to change linux.tray")
        if config.control.port != self.control_server.port:
            next_server = DictationControlServer(
                port=config.control.port,
                handler=self._handle_control_command,
            )
            next_server.start(self.loop)
            self.control_server.stop(self.loop)
            self.control_server = next_server
            self.tray.set_control_label(next_server.address)
        self.inserter.config = config.linux
        if provider_config_changed(self.controller.config, config):
            self.controller.replace_providers(*create_providers(config))

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
