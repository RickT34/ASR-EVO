from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path

from asr_evo.audio.recorder import SoundDeviceRecorder
from asr_evo.config import AUDIO_DEFAULTS, INSERT_DEFAULTS, STORAGE_DEFAULTS, AppConfig
from asr_evo.core.control import ControlResult, DictationControlServer
from asr_evo.core.controller import DesktopControllerDependencies, DesktopDictationController
from asr_evo.core.ports import AppLifecycle, FileOpener
from asr_evo.core.tray_proxy import UnboundStatusTray
from asr_evo.platforms.windows.frontmost import WindowsFrontmostAppProvider
from asr_evo.platforms.windows.hotkey import WindowsHotkeyListener
from asr_evo.platforms.windows.inserter import WindowsClipboard, WindowsTextInserter
from asr_evo.platforms.windows.permissions import WindowsPermissions
from asr_evo.platforms.windows.tray import WindowsStatusTray
from asr_evo.providers.factory import create_asr_provider, create_llm_provider
from asr_evo.storage.history import HistoryStore
from asr_evo.ui.text_review import TkTextReviewer


class WindowsDictationRuntime:
    def __init__(self, config: AppConfig) -> None:
        if sys.platform != "win32":
            raise RuntimeError("The Windows runtime can only run on Windows")

        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._run_loop, name="asr-evo-async", daemon=True)
        self._controller_lock = threading.RLock()
        self.lifecycle = WindowsAppLifecycle()
        tray = UnboundStatusTray()
        dependencies = DesktopControllerDependencies(
            tray=tray,
            recorder=SoundDeviceRecorder(
                sample_rate=AUDIO_DEFAULTS.sample_rate,
                channels=AUDIO_DEFAULTS.channels,
                input_device=config.audio.input_device,
            ),
            asr_provider=create_asr_provider(config),
            llm_provider=create_llm_provider(config),
            inserter=WindowsTextInserter(restore_delay_ms=INSERT_DEFAULTS.restore_delay_ms),
            text_reviewer=TkTextReviewer(),
            app_provider=WindowsFrontmostAppProvider(),
            history_store=HistoryStore(STORAGE_DEFAULTS.database_path),
            context_store=config.context.store(),
            clipboard=WindowsClipboard(),
            file_opener=WindowsFileOpener(),
            permissions=WindowsPermissions(),
            lifecycle=self.lifecycle,
            on_config_applied=self.apply_config,
        )
        self.controller = DesktopDictationController(
            config=config,
            dependencies=dependencies,
            loop=self.loop,
        )
        self.control_server = DictationControlServer(
            port=config.control.port,
            handler=self._handle_control_command,
        )
        self.tray = WindowsStatusTray(
            control_label=self.control_server.address,
            status_config=config.status,
            styles=self.controller.styles.all(),
            selected_style_id=self.controller.style_bindings.current_style_id,
            actions=self.controller.tray_actions(),
        )
        self.lifecycle.bind(self.tray.stop)
        tray.bind(self.tray)
        self.tray.set_review_enabled(config.review.enabled)
        self.hotkey = WindowsHotkeyListener(config.hotkey, self._toggle_from_hotkey)
        self.controller.initialize_tray()

    def run(self) -> None:
        self.loop_thread.start()
        self.control_server.start(self.loop)
        self.hotkey.start()
        self.controller.check_permissions()
        if self.controller.state.current_error is None:
            self.tray.set_state("idle")
        try:
            self.tray.run()
        finally:
            self.hotkey.stop()
            if self.loop.is_running():
                self.loop.call_soon_threadsafe(self.loop.stop)
            self.loop_thread.join(timeout=2)

    def _handle_control_command(self, command: str) -> ControlResult:
        with self._controller_lock:
            if command == "status":
                return ControlResult(ok=True, state=self.controller.state.state.value)
            if command == "stop":
                return self._stop_recording()
            if command == "toggle" and self.controller.state.state.value == "recording":
                return self._stop_recording()
            return self.controller.handle_control_command(command)

    def _toggle_from_hotkey(self) -> None:
        with self._controller_lock:
            self.controller.toggle_dictation()

    def _stop_recording(self) -> ControlResult:
        if self.controller.state.state.value == "recording":
            self.controller.dependencies.recorder.stop()
        return ControlResult(ok=True, state=self.controller.state.state.value)

    def apply_config(self, config: AppConfig) -> None:
        if self.control_server.port != config.control.port:
            next_server = DictationControlServer(
                port=config.control.port,
                handler=self._handle_control_command,
            )
            next_server.start(self.loop)
            self.control_server.stop(self.loop)
            self.control_server = next_server
            self.tray.set_control_label(self.control_server.address)
        self.hotkey.apply_config(config.hotkey)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()


class WindowsFileOpener(FileOpener):
    def open_path(self, path: Path) -> None:
        os.startfile(path)  # type: ignore[attr-defined]


class WindowsAppLifecycle(AppLifecycle):
    def __init__(self) -> None:
        self._quit = None

    def bind(self, quit_callback) -> None:
        self._quit = quit_callback

    def quit(self) -> None:
        if self._quit is not None:
            self._quit()
