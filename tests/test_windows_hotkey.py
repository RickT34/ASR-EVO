from __future__ import annotations

import pytest

from asr_evo.platforms.windows.hotkey import normalize_hotkey


def test_normalize_hotkey_accepts_plain_modifier_names() -> None:
    assert normalize_hotkey("ctrl+alt+space") == "<ctrl>+<alt>+space"
    assert normalize_hotkey("control-shift-v") == "<ctrl>+<shift>+v"
    assert normalize_hotkey("<win>+space") == "<cmd>+space"


def test_normalize_hotkey_rejects_empty_value() -> None:
    with pytest.raises(ValueError, match="hotkey cannot be empty"):
        normalize_hotkey(" + ")
