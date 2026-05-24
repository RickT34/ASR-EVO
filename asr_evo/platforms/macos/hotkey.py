from __future__ import annotations

from collections.abc import Callable


class MacOSHotkeyService:
    """Placeholder for the Carbon/RegisterEventHotKey runtime.

    The core pipeline only needs a callback when the user toggles dictation. Keeping this class
    small makes it straightforward to replace with a Swift helper if Python event taps feel brittle.
    """

    def __init__(self, hotkey: str) -> None:
        self.hotkey = hotkey
        self._on_toggle: Callable[[], None] | None = None

    def on_toggle(self, callback: Callable[[], None]) -> None:
        self._on_toggle = callback

    def start(self) -> None:
        raise NotImplementedError("macOS global hotkey loop is the next runtime integration step")

    def stop(self) -> None:
        self._on_toggle = None
