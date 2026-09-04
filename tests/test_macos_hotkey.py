from __future__ import annotations

import sys

import pytest

from asr_evo.config import HotkeyConfig
from asr_evo.platforms.macos.hotkey import HotkeySpec, MacOSHotkeyListener


def test_hotkey_parse_aliases_and_special_keys() -> None:
    spec = HotkeySpec.parse("command+shift+space")

    assert spec.keycode == 49
    assert spec.modifiers == frozenset({"cmd", "shift"})
    assert HotkeySpec.parse("control+pageup").keycode == 116
    assert HotkeySpec.parse("<option>+<return>").keycode == 36


def test_hotkey_parse_modifier_only_hold() -> None:
    spec = HotkeySpec.parse("globe")

    assert spec.keycode is None
    assert spec.hold_modifier == "fn"
    assert spec.is_modifier_only


def test_hotkey_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        HotkeySpec.parse(" + ")
    with pytest.raises(ValueError, match="unsupported macOS hotkey key"):
        HotkeySpec.parse("cmd+not-a-key")
    with pytest.raises(ValueError, match="modifier-only"):
        MacOSHotkeyListener(HotkeyConfig(toggle="fn", mode="toggle"), lambda: None)


def test_hotkey_match_requires_exact_modifiers() -> None:
    spec = HotkeySpec.parse("cmd+space")

    assert spec.matches(keycode=49, flags=_Quartz.kCGEventFlagMaskCommand, quartz=_Quartz)
    assert not spec.matches(
        keycode=49,
        flags=_Quartz.kCGEventFlagMaskCommand | _Quartz.kCGEventFlagMaskShift,
        quartz=_Quartz,
    )


def test_toggle_ignores_autorepeat_and_consumes_matching_key() -> None:
    events = []
    listener = _listener(HotkeyConfig(toggle="cmd+space"), lambda: events.append("toggle"))

    assert listener._handle_event(None, _Quartz.kCGEventKeyDown, _Event(49, command=True), None) is None
    repeated = _Event(49, command=True, autorepeat=True)
    assert listener._handle_event(None, _Quartz.kCGEventKeyDown, repeated, None) is None
    assert listener._handle_event(None, _Quartz.kCGEventKeyUp, _Event(49), None) is None
    unmatched = _Event(49)
    assert listener._handle_event(None, _Quartz.kCGEventKeyDown, unmatched, None) is unmatched
    assert events == ["toggle"]


def test_hold_stops_when_key_or_required_modifier_is_released() -> None:
    events = []
    listener = _listener(
        HotkeyConfig(toggle="cmd+shift+space", mode="hold"),
        lambda: events.append("toggle"),
        on_start=lambda: events.append("start"),
        on_stop=lambda: events.append("stop"),
    )

    listener._handle_event(None, _Quartz.kCGEventKeyDown, _Event(49, command=True, shift=True), None)
    listener._handle_event(None, _Quartz.kCGEventFlagsChanged, _Event(56, command=True), None)
    assert listener._handle_event(None, _Quartz.kCGEventKeyUp, _Event(49, command=True), None) is None

    listener._handle_event(None, _Quartz.kCGEventKeyDown, _Event(49, command=True, shift=True), None)
    listener._handle_event(None, _Quartz.kCGEventKeyUp, _Event(49, command=True, shift=True), None)

    assert events == ["start", "stop", "start", "stop"]


def test_modifier_only_hold_tracks_flags_without_consuming_them() -> None:
    events = []
    listener = _listener(
        HotkeyConfig(toggle="globe", mode="hold"),
        lambda: events.append("toggle"),
        on_start=lambda: events.append("start"),
        on_stop=lambda: events.append("stop"),
    )
    down = _Event(0, fn=True)
    up = _Event(0)

    assert listener._handle_event(None, _Quartz.kCGEventFlagsChanged, down, None) is down
    assert listener._handle_event(None, _Quartz.kCGEventFlagsChanged, up, None) is up
    assert events == ["start", "stop"]


def test_listener_registers_and_removes_quartz_event_tap(monkeypatch) -> None:
    quartz = _LifecycleQuartz()
    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    listener = MacOSHotkeyListener(HotkeyConfig(toggle="cmd+space"), lambda: None)

    listener.start()
    listener.stop()

    assert quartz.tap_enabled == [True, False]
    assert quartz.added_source == (quartz.run_loop, quartz.source, quartz.kCFRunLoopCommonModes)
    assert quartz.removed_source == quartz.added_source
    assert quartz.invalidated_tap is quartz.tap
    assert listener._tap is None


def _listener(config, on_toggle, *, on_start=None, on_stop=None):
    listener = MacOSHotkeyListener(
        config,
        on_toggle,
        on_start=on_start,
        on_stop=on_stop,
    )
    listener._quartz = _Quartz
    listener._tap = object()
    return listener


class _Event:
    def __init__(
        self,
        keycode: int,
        *,
        command: bool = False,
        shift: bool = False,
        fn: bool = False,
        autorepeat: bool = False,
    ) -> None:
        self.keycode = keycode
        self.flags = 0
        if command:
            self.flags |= _Quartz.kCGEventFlagMaskCommand
        if shift:
            self.flags |= _Quartz.kCGEventFlagMaskShift
        if fn:
            self.flags |= _Quartz.kCGEventFlagMaskSecondaryFn
        self.autorepeat = autorepeat


class _Quartz:
    kCGEventKeyDown = 10
    kCGEventKeyUp = 11
    kCGEventFlagsChanged = 12
    kCGEventTapDisabledByTimeout = -2
    kCGEventTapDisabledByUserInput = -1
    kCGKeyboardEventKeycode = 9
    kCGKeyboardEventAutorepeat = 8
    kCGEventFlagMaskCommand = 1 << 0
    kCGEventFlagMaskShift = 1 << 1
    kCGEventFlagMaskControl = 1 << 2
    kCGEventFlagMaskAlternate = 1 << 3
    kCGEventFlagMaskSecondaryFn = 1 << 4

    @staticmethod
    def CGEventGetIntegerValueField(event, field):
        if field == _Quartz.kCGKeyboardEventAutorepeat:
            return event.autorepeat
        return event.keycode

    @staticmethod
    def CGEventGetFlags(event):
        return event.flags

    @staticmethod
    def CGEventTapEnable(tap, enabled):
        pass


class _LifecycleQuartz(_Quartz):
    kCGSessionEventTap = 1
    kCGHeadInsertEventTap = 0
    kCGEventTapOptionDefault = 0
    kCFRunLoopCommonModes = "common"

    def __init__(self) -> None:
        self.tap = object()
        self.source = object()
        self.run_loop = object()
        self.tap_enabled = []
        self.added_source = None
        self.removed_source = None
        self.invalidated_tap = None

    @staticmethod
    def CGEventMaskBit(event_type):
        return 1 << event_type

    def CGEventTapCreate(self, *args):
        return self.tap

    def CFMachPortCreateRunLoopSource(self, allocator, tap, order):
        return self.source

    def CFRunLoopGetCurrent(self):
        return self.run_loop

    def CFRunLoopAddSource(self, run_loop, source, mode):
        self.added_source = (run_loop, source, mode)

    def CGEventTapEnable(self, tap, enabled):
        self.tap_enabled.append(enabled)

    def CFRunLoopRemoveSource(self, run_loop, source, mode):
        self.removed_source = (run_loop, source, mode)

    def CFMachPortInvalidate(self, tap):
        self.invalidated_tap = tap
