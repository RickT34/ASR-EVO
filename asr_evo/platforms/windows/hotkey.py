from __future__ import annotations

from collections.abc import Callable

from asr_evo.config import HotkeyConfig


MODIFIER_ALIASES = {
    "control": "ctrl",
    "ctrl": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "cmd": "cmd",
    "win": "cmd",
    "windows": "cmd",
}

SPECIAL_KEYS = {
    "space",
    "enter",
    "return",
    "tab",
    "esc",
    "escape",
    "backspace",
    "delete",
    "insert",
    "home",
    "end",
    "page_up",
    "page_down",
    "up",
    "down",
    "left",
    "right",
    *{f"f{index}" for index in range(1, 25)},
}

SPECIAL_KEY_ALIASES = {
    "return": "enter",
    "pgup": "page_up",
    "pageup": "page_up",
    "pgdn": "page_down",
    "pagedown": "page_down",
    "del": "delete",
    "ins": "insert",
    "escape": "esc",
}


def normalize_hotkey(value: str) -> str:
    parts = [part.strip().lower() for part in value.replace("-", "+").split("+")]
    keys = [part.strip("<>") for part in parts if part]
    if not keys:
        raise ValueError("hotkey cannot be empty")
    normalized = []
    for key in keys:
        alias = MODIFIER_ALIASES.get(key)
        if alias:
            normalized.append(f"<{alias}>")
            continue
        special_key = SPECIAL_KEY_ALIASES.get(key, key)
        normalized.append(f"<{special_key}>" if special_key in SPECIAL_KEYS else key)
    return "+".join(normalized)


class WindowsHotkeyListener:
    def __init__(
        self,
        config: HotkeyConfig,
        on_toggle: Callable[[], None],
    ) -> None:
        self.config = config
        self.on_toggle = on_toggle
        self._listener = None

    def start(self) -> None:
        if not self.config.enabled:
            return
        try:
            from pynput import keyboard
        except ImportError as exc:
            raise RuntimeError("pynput is required for Windows global hotkeys") from exc

        hotkey = normalize_hotkey(self.config.toggle)
        self._listener = keyboard.GlobalHotKeys({hotkey: self.on_toggle})
        self._listener.start()

    def stop(self) -> None:
        if self._listener is None:
            return
        self._listener.stop()
        self._listener = None

    def apply_config(self, config: HotkeyConfig) -> None:
        if config == self.config:
            return
        self.stop()
        self.config = config
        if config.enabled:
            self.start()
