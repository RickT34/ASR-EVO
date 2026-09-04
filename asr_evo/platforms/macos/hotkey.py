from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from asr_evo.config import HotkeyConfig


MODIFIER_ALIASES = {
    "command": "cmd",
    "cmd": "cmd",
    "win": "cmd",
    "windows": "cmd",
    "control": "ctrl",
    "ctrl": "ctrl",
    "option": "alt",
    "alt": "alt",
    "shift": "shift",
    "fn": "fn",
    "globe": "fn",
}

KEY_ALIASES = {
    "return": "enter",
    "escape": "esc",
    "del": "delete",
    "pgup": "page_up",
    "pageup": "page_up",
    "pgdn": "page_down",
    "pagedown": "page_down",
}

# macOS virtual key codes identify physical keys and do not depend on the active input method.
KEYCODES = {
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
    "enter": 36,
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
    "tab": 48,
    "space": 49,
    "backspace": 51,
    "delete": 51,
    "esc": 53,
    "f17": 64,
    "f18": 79,
    "f19": 80,
    "f20": 90,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f3": 99,
    "f8": 100,
    "f9": 101,
    "f11": 103,
    "f13": 105,
    "f16": 106,
    "f14": 107,
    "f10": 109,
    "f12": 111,
    "f15": 113,
    "home": 115,
    "page_up": 116,
    "forward_delete": 117,
    "f4": 118,
    "end": 119,
    "f2": 120,
    "page_down": 121,
    "f1": 122,
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
}


@dataclass(frozen=True)
class HotkeySpec:
    keycode: int | None
    modifiers: frozenset[str]
    hold_modifier: str | None = None

    @classmethod
    def parse(cls, value: str) -> HotkeySpec:
        parts = [part.strip().lower().strip("<>") for part in value.split("+") if part.strip()]
        if not parts:
            raise ValueError("hotkey cannot be empty")

        key = parts[-1]
        modifiers = frozenset(_normalize_modifier(part) for part in parts[:-1])
        if key in MODIFIER_ALIASES:
            return cls(
                keycode=None,
                modifiers=modifiers,
                hold_modifier=MODIFIER_ALIASES[key],
            )

        key = KEY_ALIASES.get(key, key)
        if key not in KEYCODES:
            raise ValueError(f"unsupported macOS hotkey key: {key}")
        return cls(keycode=KEYCODES[key], modifiers=modifiers)

    @property
    def is_modifier_only(self) -> bool:
        return self.keycode is None

    def matches(self, *, keycode: int, flags: int, quartz) -> bool:
        return keycode == self.keycode and self._modifiers_match(flags, quartz, exact=True)

    def hold_is_active(self, *, flags: int, quartz, exact: bool) -> bool:
        if self.hold_modifier is None:
            return self._modifiers_match(flags, quartz, exact=exact)
        required = self.modifiers | {self.hold_modifier}
        return _flags_match(required, flags, quartz, exact=exact)

    def _modifiers_match(self, flags: int, quartz, *, exact: bool) -> bool:
        return _flags_match(self.modifiers, flags, quartz, exact=exact)


class MacOSHotkeyListener:
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
        self.spec = HotkeySpec.parse(config.toggle)
        if config.mode == "toggle" and self.spec.is_modifier_only:
            raise ValueError("modifier-only macOS hotkeys require mode = \"hold\"")

        self._pressed = False
        self._key_down = False
        self._tap = None
        self._source = None
        self._run_loop = None
        self._quartz = None

    def start(self) -> None:
        if not self.config.enabled or self._tap is not None:
            return
        try:
            import Quartz
        except ImportError as exc:
            raise RuntimeError("PyObjC Quartz is required for macOS global hotkeys") from exc

        mask = (
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
            | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
        )
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            mask,
            self._handle_event,
            None,
        )
        if tap is None:
            raise RuntimeError(
                "Unable to create macOS global hotkey listener. Grant Accessibility permission "
                "and restart ASR-EVO."
            )

        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        run_loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(run_loop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)
        self._quartz = Quartz
        self._tap = tap
        self._source = source
        self._run_loop = run_loop

    def stop(self) -> None:
        if self._tap is None:
            return
        quartz = self._quartz
        if self._pressed:
            self._pressed = False
            self.on_stop()
        self._key_down = False
        quartz.CGEventTapEnable(self._tap, False)
        quartz.CFRunLoopRemoveSource(
            self._run_loop,
            self._source,
            quartz.kCFRunLoopCommonModes,
        )
        quartz.CFMachPortInvalidate(self._tap)
        self._tap = None
        self._source = None
        self._run_loop = None

    def _handle_event(self, proxy, event_type, event, refcon):
        quartz = self._quartz
        if event_type in {
            quartz.kCGEventTapDisabledByTimeout,
            quartz.kCGEventTapDisabledByUserInput,
        }:
            quartz.CGEventTapEnable(self._tap, True)
            return event
        if self.config.mode == "hold":
            return self._handle_hold_event(event_type, event)
        if event_type not in {quartz.kCGEventKeyDown, quartz.kCGEventKeyUp}:
            return event

        keycode = quartz.CGEventGetIntegerValueField(event, quartz.kCGKeyboardEventKeycode)
        if keycode == self.spec.keycode and event_type == quartz.kCGEventKeyUp:
            if self._key_down:
                self._key_down = False
                return None
            return event
        if event_type != quartz.kCGEventKeyDown:
            return event
        if keycode == self.spec.keycode and self._key_down:
            return None
        if quartz.CGEventGetIntegerValueField(event, quartz.kCGKeyboardEventAutorepeat):
            return event

        flags = quartz.CGEventGetFlags(event)
        if not self.spec.matches(keycode=keycode, flags=flags, quartz=quartz):
            return event
        self._key_down = True
        self.on_toggle()
        return None

    def _handle_hold_event(self, event_type, event):
        quartz = self._quartz
        flags = quartz.CGEventGetFlags(event)

        if self.spec.is_modifier_only:
            if event_type != quartz.kCGEventFlagsChanged:
                return event
            active = self.spec.hold_is_active(flags=flags, quartz=quartz, exact=not self._pressed)
            if active and not self._pressed:
                self._pressed = True
                self.on_start()
            elif not active and self._pressed:
                self._pressed = False
                self.on_stop()
            return event

        if event_type == quartz.kCGEventFlagsChanged and self._pressed:
            if not self.spec.hold_is_active(flags=flags, quartz=quartz, exact=False):
                self._pressed = False
                self.on_stop()
            return event

        keycode = quartz.CGEventGetIntegerValueField(event, quartz.kCGKeyboardEventKeycode)
        if keycode != self.spec.keycode:
            return event
        if event_type == quartz.kCGEventKeyDown:
            if self._key_down:
                return None
            if self.spec.matches(keycode=keycode, flags=flags, quartz=quartz):
                self._key_down = True
                self._pressed = True
                self.on_start()
                return None
            return event
        if event_type == quartz.kCGEventKeyUp and self._key_down:
            self._key_down = False
            if self._pressed:
                self._pressed = False
                self.on_stop()
            return None
        return event


def _normalize_modifier(value: str) -> str:
    if value not in MODIFIER_ALIASES:
        raise ValueError(f"unsupported macOS hotkey modifier: {value}")
    return MODIFIER_ALIASES[value]


def _flags_match(required: frozenset[str], flags: int, quartz, *, exact: bool) -> bool:
    for name, mask in _modifier_masks(quartz).items():
        active = bool(flags & mask)
        if name in required:
            if not active:
                return False
        elif exact and active:
            return False
    return True


def _modifier_masks(quartz) -> dict[str, int]:
    return {
        "cmd": quartz.kCGEventFlagMaskCommand,
        "shift": quartz.kCGEventFlagMaskShift,
        "ctrl": quartz.kCGEventFlagMaskControl,
        "alt": quartz.kCGEventFlagMaskAlternate,
        "fn": quartz.kCGEventFlagMaskSecondaryFn,
    }
