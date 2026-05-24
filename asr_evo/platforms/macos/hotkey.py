from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


class MacOSHotkeyService:
    def __init__(self, hotkey: str, *, mode: str = "toggle") -> None:
        import Quartz

        self.hotkey = hotkey
        self.mode = mode
        self.spec = HotkeySpec.parse(hotkey)
        self._on_toggle: Callable[[], None] | None = None
        self._on_press: Callable[[], None] | None = None
        self._on_release: Callable[[], None] | None = None
        self._pressed = False
        self._tap = None
        self._source = None
        self._Quartz = Quartz

    def on_toggle(self, callback: Callable[[], None]) -> None:
        self._on_toggle = callback

    def on_press_release(self, press: Callable[[], None], release: Callable[[], None]) -> None:
        self._on_press = press
        self._on_release = release

    def start(self) -> None:
        Quartz = self._Quartz
        mask = Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown) | Quartz.CGEventMaskBit(
            Quartz.kCGEventFlagsChanged
        ) | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            mask,
            self._handle_event,
            None,
        )
        if self._tap is None:
            raise RuntimeError("Unable to create macOS event tap. Grant Accessibility permission.")
        self._source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(),
            self._source,
            Quartz.kCFRunLoopCommonModes,
        )
        Quartz.CGEventTapEnable(self._tap, True)

    def stop(self) -> None:
        if self._tap is not None:
            self._Quartz.CGEventTapEnable(self._tap, False)
        self._on_toggle = None
        self._on_press = None
        self._on_release = None

    def _handle_event(self, proxy, event_type, event, refcon):
        Quartz = self._Quartz
        if self.mode == "hold":
            return self._handle_hold_event(Quartz, event_type, event)
        if event_type != Quartz.kCGEventKeyDown:
            return event
        autorepeat = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat)
        if autorepeat:
            return event
        keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        flags = Quartz.CGEventGetFlags(event)
        if self.spec.matches(keycode=keycode, flags=flags, Quartz=Quartz):
            if self._on_toggle is not None:
                self._on_toggle()
            return None
        return event

    def _handle_hold_event(self, Quartz, event_type, event):
        flags = Quartz.CGEventGetFlags(event)
        is_down = self.spec.matches_hold(flags=flags, Quartz=Quartz)
        if event_type == Quartz.kCGEventFlagsChanged and self.spec.is_modifier_only:
            if is_down and not self._pressed:
                self._pressed = True
                if self._on_press is not None:
                    self._on_press()
                return None
            if not is_down and self._pressed:
                self._pressed = False
                if self._on_release is not None:
                    self._on_release()
                return None
        if event_type == Quartz.kCGEventKeyDown and not self.spec.is_modifier_only:
            keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
            if self.spec.matches(keycode=keycode, flags=flags, Quartz=Quartz) and not self._pressed:
                self._pressed = True
                if self._on_press is not None:
                    self._on_press()
                return None
        if event_type == Quartz.kCGEventKeyUp and not self.spec.is_modifier_only:
            keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
            if keycode == self.spec.keycode and self._pressed:
                self._pressed = False
                if self._on_release is not None:
                    self._on_release()
                return None
        return event


@dataclass(frozen=True)
class HotkeySpec:
    keycode: int | None
    modifiers: frozenset[str]
    hold_modifier: str | None = None

    @classmethod
    def parse(cls, value: str) -> "HotkeySpec":
        parts = [part.strip().lower() for part in value.split("+") if part.strip()]
        if not parts:
            raise ValueError("Hotkey cannot be empty")
        key = parts[-1]
        modifiers = frozenset(_normalize_modifier(part) for part in parts[:-1])
        if key in HOLD_MODIFIERS:
            return cls(keycode=None, modifiers=modifiers, hold_modifier=HOLD_MODIFIERS[key])
        if key not in KEYCODES:
            raise ValueError(f"Unsupported hotkey key: {key}")
        return cls(keycode=KEYCODES[key], modifiers=modifiers)

    @property
    def is_modifier_only(self) -> bool:
        return self.hold_modifier is not None and self.keycode is None

    def matches(self, *, keycode: int, flags: int, Quartz) -> bool:
        if keycode != self.keycode:
            return False
        masks = {
            "cmd": Quartz.kCGEventFlagMaskCommand,
            "shift": Quartz.kCGEventFlagMaskShift,
            "ctrl": Quartz.kCGEventFlagMaskControl,
            "alt": Quartz.kCGEventFlagMaskAlternate,
        }
        for name, mask in masks.items():
            expected = name in self.modifiers
            actual = bool(flags & mask)
            if expected != actual:
                return False
        return True

    def matches_hold(self, *, flags: int, Quartz) -> bool:
        if self.hold_modifier is None:
            return False
        masks = _modifier_masks(Quartz)
        for name in self.modifiers:
            if not flags & masks[name]:
                return False
        return bool(flags & masks[self.hold_modifier])


def _normalize_modifier(value: str) -> str:
    aliases = {
        "command": "cmd",
        "cmd": "cmd",
        "⌘": "cmd",
        "control": "ctrl",
        "ctrl": "ctrl",
        "⌃": "ctrl",
        "option": "alt",
        "alt": "alt",
        "⌥": "alt",
        "shift": "shift",
        "⇧": "shift",
        "fn": "fn",
        "globe": "fn",
        "🌐": "fn",
    }
    if value not in aliases:
        raise ValueError(f"Unsupported hotkey modifier: {value}")
    return aliases[value]


def _modifier_masks(Quartz) -> dict[str, int]:
    return {
        "cmd": Quartz.kCGEventFlagMaskCommand,
        "shift": Quartz.kCGEventFlagMaskShift,
        "ctrl": Quartz.kCGEventFlagMaskControl,
        "alt": Quartz.kCGEventFlagMaskAlternate,
        "fn": Quartz.kCGEventFlagMaskSecondaryFn,
    }


HOLD_MODIFIERS = {
    "fn": "fn",
    "globe": "fn",
    "🌐": "fn",
}


KEYCODES = {
    "space": 49,
    "return": 36,
    "enter": 36,
    "escape": 53,
    "esc": 53,
    "tab": 48,
    "a": 0,
    "s": 1,
    "d": 2,
    "f": 3,
    "h": 4,
    "g": 5,
    "z": 6,
    "x": 7,
    "c": 8,
    "v": 9,
    "b": 11,
    "q": 12,
    "w": 13,
    "e": 14,
    "r": 15,
    "y": 16,
    "t": 17,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "6": 22,
    "5": 23,
    "=": 24,
    "9": 25,
    "7": 26,
    "-": 27,
    "8": 28,
    "0": 29,
    "]": 30,
    "o": 31,
    "u": 32,
    "[": 33,
    "i": 34,
    "p": 35,
    "l": 37,
    "j": 38,
    "'": 39,
    "k": 40,
    ";": 41,
    "\\": 42,
    ",": 43,
    "/": 44,
    "n": 45,
    "m": 46,
    ".": 47,
}
