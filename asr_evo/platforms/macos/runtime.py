from __future__ import annotations

import asyncio
import concurrent.futures
import queue
import subprocess
import sys
import threading
from pathlib import Path

from asr_evo.audio.recorder import SoundDeviceRecorder
from asr_evo.config import (
    AUDIO_DEFAULTS,
    INSERT_DEFAULTS,
    STORAGE_DEFAULTS,
    AppConfig,
)
from asr_evo.core.control import ControlResult, DictationControlServer
from asr_evo.core.controller import (
    DesktopControllerDependencies,
    DesktopDictationController,
)
from asr_evo.core.ports import (
    AppLifecycle,
    Clipboard,
    FileOpener,
)
from asr_evo.core.tray_proxy import UnboundStatusTray
from asr_evo.platforms.macos.frontmost import MacOSFrontmostAppProvider
from asr_evo.platforms.macos.inserter import MacOSTextInserter
from asr_evo.platforms.macos.permissions import MacOSPermissions
from asr_evo.platforms.macos.tray import MacOSStatusTray
from asr_evo.providers.factory import create_providers, provider_config_changed
from asr_evo.storage.history import HistoryStore
from asr_evo.ui.text_review import TkTextReviewer

MAIN_THREAD_TIMEOUT_SECONDS = 2


class MacOSDictationRuntime:
    def __init__(self, config: AppConfig) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("The macOS runtime can only run on macOS")

        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._run_loop, name="asr-evo-async", daemon=True)
        tray = UnboundStatusTray()
        asr_provider, llm_provider = create_providers(config)
        dependencies = DesktopControllerDependencies(
            tray=tray,
            recorder=SoundDeviceRecorder(
                sample_rate=AUDIO_DEFAULTS.sample_rate,
                channels=AUDIO_DEFAULTS.channels,
                input_device=config.audio.input_device,
            ),
            asr_provider=asr_provider,
            llm_provider=llm_provider,
            inserter=MacOSTextInserter(
                mode=INSERT_DEFAULTS.mode,
                fallback=INSERT_DEFAULTS.fallback,
                restore_delay_ms=INSERT_DEFAULTS.restore_delay_ms,
            ),
            text_reviewer=TkTextReviewer(),
            app_provider=MacOSFrontmostAppProvider(),
            history_store=HistoryStore(STORAGE_DEFAULTS.database_path),
            context_store=config.context.store(),
            clipboard=MacOSClipboard(),
            file_opener=MacOSFileOpener(),
            permissions=MacOSPermissions(),
            lifecycle=MacOSAppLifecycle(),
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
        self.tray = MacOSStatusTray(
            control_label=self.control_server.address,
            status_config=config.status,
            styles=self.controller.styles.all(),
            selected_style_id=self.controller.style_bindings.current_style_id,
            actions=self.controller.tray_actions(),
        )
        tray.bind(self.tray)
        self.tray.set_review_enabled(config.review.enabled)
        self.controller.initialize_tray()

    def run(self) -> None:
        from AppKit import NSApp, NSApplication, NSApplicationActivationPolicyAccessory

        self.loop_thread.start()
        self.control_server.start(self.loop)
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        self.controller.check_permissions()
        if self.controller.state.current_error is None:
            self.tray.set_state("idle")
        NSApp.run()

    def _handle_control_command(self, command: str) -> ControlResult:
        if command == "status":
            return ControlResult(ok=True, state=self.controller.state.state.value)
        if command == "stop":
            return self._stop_recording_from_control_thread()
        if command == "toggle" and self.controller.state.state.value == "recording":
            return self._stop_recording_from_control_thread()
        try:
            return call_on_main_thread(self.controller.handle_control_command, command)
        except concurrent.futures.TimeoutError:
            return ControlResult(
                ok=False,
                state=self.controller.state.state.value,
                error="main thread did not handle the control command in time",
            )

    def _stop_recording_from_control_thread(self) -> ControlResult:
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
        if provider_config_changed(self.controller.config, config):
            self.controller.replace_providers(*create_providers(config))

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()


class MacOSFileOpener(FileOpener):
    def open_path(self, path: Path) -> None:
        subprocess.run(["open", str(path)], check=False)


class MacOSClipboard(Clipboard):
    def copy_text(self, text: str) -> None:
        from AppKit import NSPasteboard, NSPasteboardTypeString

        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(text, NSPasteboardTypeString)


class MacOSAppLifecycle(AppLifecycle):
    def quit(self) -> None:
        from AppKit import NSApp

        NSApp.terminate_(None)


def call_on_main_thread(callback, *args):
    if threading.current_thread() is threading.main_thread():
        return callback(*args)

    from PyObjCTools import AppHelper

    result_queue: queue.Queue = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            result_queue.put((True, callback(*args)))
        except Exception as exc:
            result_queue.put((False, exc))

    AppHelper.callAfter(run)
    try:
        ok, result = result_queue.get(timeout=MAIN_THREAD_TIMEOUT_SECONDS)
    except queue.Empty as exc:
        raise concurrent.futures.TimeoutError from exc
    if ok:
        return result
    raise result
