from __future__ import annotations

import asyncio
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
from asr_evo.core.context import ContextStore
from asr_evo.core.controller import (
    DesktopControllerDependencies,
    DesktopDictationController,
)
from asr_evo.core.ports import (
    AppLifecycle,
    AppStatsSummary,
    Clipboard,
    FileOpener,
    InputDeviceSummary,
    StatusTray,
)
from asr_evo.postprocess.styles import StyleDefinition
from asr_evo.platforms.macos.frontmost import MacOSFrontmostAppProvider
from asr_evo.platforms.macos.inserter import MacOSTextInserter
from asr_evo.platforms.macos.permissions import MacOSPermissions
from asr_evo.platforms.macos.tray import MacOSStatusTray
from asr_evo.providers.factory import create_asr_provider, create_llm_provider
from asr_evo.storage.history import HistoryStore
from asr_evo.ui.text_review import TkTextReviewer


class MacOSDictationRuntime:
    def __init__(self, config: AppConfig) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("The macOS runtime can only run on macOS")

        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._run_loop, name="asr-evo-async", daemon=True)
        tray = _UnboundStatusTray()
        dependencies = DesktopControllerDependencies(
            tray=tray,
            recorder=SoundDeviceRecorder(
                sample_rate=AUDIO_DEFAULTS.sample_rate,
                channels=AUDIO_DEFAULTS.channels,
                input_device=config.audio.input_device,
            ),
            asr_provider=create_asr_provider(config),
            llm_provider=create_llm_provider(config),
            inserter=MacOSTextInserter(
                mode=INSERT_DEFAULTS.mode,
                fallback=INSERT_DEFAULTS.fallback,
                restore_delay_ms=INSERT_DEFAULTS.restore_delay_ms,
            ),
            text_reviewer=TkTextReviewer(),
            app_provider=MacOSFrontmostAppProvider(),
            history_store=HistoryStore(STORAGE_DEFAULTS.database_path),
            context_store=ContextStore(
                ttl_seconds=config.context.ttl_seconds,
                max_items=config.context.max_items,
                max_chars=config.context.max_chars,
                scope=config.context.scope,
            ),
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
        return call_on_main_thread(self.controller.handle_control_command, command)

    def apply_config(self, config: AppConfig) -> None:
        if self.control_server.port == config.control.port:
            return
        next_server = DictationControlServer(
            port=config.control.port,
            handler=self._handle_control_command,
        )
        next_server.start(self.loop)
        self.control_server.stop(self.loop)
        self.control_server = next_server
        self.tray.set_control_label(self.control_server.address)

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
    ok, result = result_queue.get(timeout=2)
    if ok:
        return result
    raise result


class _UnboundStatusTray(StatusTray):
    def __init__(self) -> None:
        self._tray: StatusTray | None = None

    def bind(self, tray: StatusTray) -> None:
        self._tray = tray

    def set_state(self, state: str, detail: str = "") -> None:
        self._bound().set_state(state, detail)

    def set_error_feedback(self, feedback) -> None:
        self._bound().set_error_feedback(feedback)

    def set_styles(self, styles: list[StyleDefinition], selected_style_id: str) -> None:
        self._bound().set_styles(styles, selected_style_id)

    def set_app_binding_summary(self, title: str) -> None:
        self._bound().set_app_binding_summary(title)

    def set_status_config(self, status_config: object) -> None:
        self._bound().set_status_config(status_config)

    def set_review_enabled(self, enabled: bool) -> None:
        self._bound().set_review_enabled(enabled)

    def set_input_devices(
        self,
        devices: list[InputDeviceSummary],
        selected_device_id: str,
    ) -> None:
        self._bound().set_input_devices(devices, selected_device_id)

    def set_stats(
        self,
        *,
        totals: dict[str, int | float],
        app_stats: list[AppStatsSummary],
    ) -> None:
        self._bound().set_stats(totals=totals, app_stats=app_stats)

    def set_history_records(self, records: list[dict]) -> None:
        self._bound().set_history_records(records)

    def _bound(self) -> StatusTray:
        if self._tray is None:
            raise RuntimeError("status tray has not been bound")
        return self._tray
