from __future__ import annotations

from asr_evo.platforms.macos.hotkey import HotkeySpec


def test_hotkey_parse_aliases() -> None:
    spec = HotkeySpec.parse("command+shift+space")

    assert spec.keycode == 49
    assert spec.modifiers == frozenset({"cmd", "shift"})
