from __future__ import annotations

import pytest

from asr_evo.config import HotkeyConfig
from asr_evo.platforms.windows.hotkey import WindowsHotkeyListener, hotkey_names, normalize_hotkey


def test_normalize_hotkey_accepts_plain_modifier_names() -> None:
    assert normalize_hotkey("ctrl+alt+space") == "<ctrl>+<alt>+<space>"
    assert normalize_hotkey("control-shift-v") == "<ctrl>+<shift>+v"
    assert normalize_hotkey("<win>+space") == "<cmd>+<space>"


def test_normalize_hotkey_accepts_special_key_aliases() -> None:
    assert normalize_hotkey("ctrl+return") == "<ctrl>+<enter>"
    assert normalize_hotkey("alt+pgdn") == "<alt>+<page_down>"
    assert normalize_hotkey("shift+f8") == "<shift>+<f8>"


def test_hotkey_names_normalizes_hold_target() -> None:
    assert hotkey_names("control+return") == ("ctrl", "enter")


def test_normalize_hotkey_rejects_empty_value() -> None:
    with pytest.raises(ValueError, match="hotkey cannot be empty"):
        normalize_hotkey(" + ")


def test_hold_hotkey_starts_once_and_stops_on_release() -> None:
    events = []
    listener = WindowsHotkeyListener(
        HotkeyConfig(mode="hold", toggle="ctrl+alt+space"),
        lambda: events.append("toggle"),
        on_start=lambda: events.append("start"),
        on_stop=lambda: events.append("stop"),
    )
    target = set(hotkey_names("ctrl+alt+space"))

    listener._handle_hold_press(_Key("ctrl_l"), target)
    listener._handle_hold_press(_Key("alt_l"), target)
    listener._handle_hold_press(_Key("space"), target)
    listener._handle_hold_press(_Key("space"), target)
    listener._handle_hold_release(_Key("space"), target)

    assert events == ["start", "stop"]


class _Key:
    def __init__(self, name: str) -> None:
        self.name = name
