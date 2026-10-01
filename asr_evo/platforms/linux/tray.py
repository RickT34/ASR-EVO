from __future__ import annotations

import os
import threading

from asr_evo.ui.pystray_tray import PystrayStatusTray


class LinuxStatusTray(PystrayStatusTray):
    def __init__(self, *, mode: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.mode = mode
        self._stopped = threading.Event()

    @property
    def tooltip(self) -> str:
        if self._error_feedback is not None:
            return self._error_feedback.tooltip
        return self._tooltip

    def popup_menu(self):
        # Reuse the ordinary tray's menu and callbacks, without creating an icon.
        os.environ.setdefault("PYSTRAY_BACKEND", "appindicator")
        try:
            return self._build_menu()
        except ImportError as exc:
            raise RuntimeError("右键菜单需要 Linux 可选依赖：安装 ASR-EVO 的 [linux] extra") from exc

    def run(self) -> None:
        if self._stopped.is_set():
            return
        if self.mode == "waybar":
            self._stopped.wait()
        else:
            # The legacy XEmbed backend is not displayed by Waybar's SNI tray.
            os.environ.setdefault("PYSTRAY_BACKEND", "appindicator")
            super().run()

    def stop(self) -> None:
        self._stopped.set()
        super().stop()
