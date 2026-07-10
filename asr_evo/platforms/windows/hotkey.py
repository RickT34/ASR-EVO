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
        *,
        on_start: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
    ) -> None:
        self.config = config
        self.on_toggle = on_toggle
        self.on_start = on_start or on_toggle
        self.on_stop = on_stop or on_toggle
        self._listener = None
        self._pressed: set[str] = set()
        self._hold_active = False

    def start(self) -> None:
        if not self.config.enabled:
            return
        try:
            from pynput import keyboard
        except ImportError as exc:
            raise RuntimeError("pynput is required for Windows global hotkeys") from exc

        if self.config.mode == "hold":
            target = set(hotkey_names(self.config.toggle))
            self._listener = keyboard.Listener(
                on_press=lambda key: self._handle_hold_press(key, target),
                on_release=lambda key: self._handle_hold_release(key, target),
            )
        else:
            hotkey = normalize_hotkey(self.config.toggle)
            self._listener = keyboard.GlobalHotKeys({hotkey: self.on_toggle})
        self._listener.start()

    def stop(self) -> None:
        if self._listener is None:
            return
        self._listener.stop()
        self._listener = None
        if self._hold_active:
            self._hold_active = False
            self.on_stop()
        self._pressed = set()

    def apply_config(self, config: HotkeyConfig) -> None:
        if config == self.config:
            return
        self.stop()
        self.config = config
        if config.enabled:
            self.start()

    def _handle_hold_press(self, key, target: set[str]) -> None:
        key_name = hotkey_event_name(key)
        if key_name is None:
            return
        self._pressed.add(key_name)
        if not self._hold_active and target.issubset(self._pressed):
            self._hold_active = True
            self.on_start()

    def _handle_hold_release(self, key, target: set[str]) -> None:
        key_name = hotkey_event_name(key)
        if key_name is None:
            return
        self._pressed.discard(key_name)
        if self._hold_active and key_name in target:
            self._hold_active = False
            self.on_stop()


def hotkey_names(value: str) -> tuple[str, ...]:
    parts = [part.strip().lower() for part in value.replace("-", "+").split("+")]
    keys = [part.strip("<>") for part in parts if part]
    if not keys:
        raise ValueError("hotkey cannot be empty")
    names = []
    for key in keys:
        names.append(MODIFIER_ALIASES.get(key) or SPECIAL_KEY_ALIASES.get(key, key))
    return tuple(names)


def hotkey_event_name(key) -> str | None:
    name = getattr(key, "name", None)
    if name:
        return KEY_EVENT_ALIASES.get(name, name)
    char = getattr(key, "char", None)
    if char:
        return str(char).lower()
    return None


KEY_EVENT_ALIASES = {
    "ctrl_l": "ctrl",
    "ctrl_r": "ctrl",
    "alt_l": "alt",
    "alt_r": "alt",
    "shift_l": "shift",
    "shift_r": "shift",
    "cmd_l": "cmd",
    "cmd_r": "cmd",
    "win_l": "cmd",
    "win_r": "cmd",
    "return": "enter",
}
