from __future__ import annotations

from asr_evo.platforms.macos.hotkey import HotkeySpec


def test_hotkey_parse_aliases() -> None:
    spec = HotkeySpec.parse("command+shift+space")

    assert spec.keycode == 49
    assert spec.modifiers == frozenset({"cmd", "shift"})


def test_hotkey_parse_globe_hold() -> None:
    spec = HotkeySpec.parse("globe")

    assert spec.keycode is None
    assert spec.hold_modifier == "fn"
    assert spec.is_modifier_only


def test_non_modifier_hold_matches_keycode() -> None:
    spec = HotkeySpec.parse("cmd+shift+space")

    assert spec.keycode == 49
    assert not spec.is_modifier_only


def test_fn_combo_requires_fn_flag() -> None:
    spec = HotkeySpec.parse("fn+space")

    assert not spec.matches(keycode=49, flags=0, Quartz=_FakeQuartz)
    assert spec.matches(keycode=49, flags=_FakeQuartz.kCGEventFlagMaskSecondaryFn, Quartz=_FakeQuartz)


class _FakeQuartz:
    kCGEventFlagMaskCommand = 1 << 0
    kCGEventFlagMaskShift = 1 << 1
    kCGEventFlagMaskControl = 1 << 2
    kCGEventFlagMaskAlternate = 1 << 3
    kCGEventFlagMaskSecondaryFn = 1 << 4
