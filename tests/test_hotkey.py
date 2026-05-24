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
