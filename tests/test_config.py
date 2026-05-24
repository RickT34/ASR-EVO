from __future__ import annotations

from pathlib import Path

from asr_evo.config import AppConfig
from asr_evo.platforms.macos.windows import SettingsWindow


def test_config_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = AppConfig()
    config.context.ttl_seconds = 123
    config.style.prompts_dir = "my-prompts"

    config.save(path)
    loaded = AppConfig.load(path)

    assert loaded.context.ttl_seconds == 123
    assert loaded.style.prompts_dir == "my-prompts"


def test_settings_window_build_config_validation() -> None:
    # Exercise the validation path without constructing an AppKit window.
    window = object.__new__(SettingsWindow)
    window.config = AppConfig()
    window.fields = {
        "hotkey": _Field("globe"),
        "hotkey_mode": _Field("hold"),
        "ttl": _Field("600"),
        "max_items": _Field("20"),
        "max_chars": _Field("6000"),
        "prompts_dir": _Field("prompts"),
        "database_path": _Field("data/asr_evo.sqlite3"),
    }

    config = window._build_config()

    assert config.hotkey.toggle == "globe"
    assert config.hotkey.mode == "hold"


class _Field:
    def __init__(self, value: str) -> None:
        self.value = value

    def stringValue(self) -> str:
        return self.value
