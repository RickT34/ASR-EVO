from __future__ import annotations

from pathlib import Path

from asr_evo.config import AppConfig


def test_config_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = AppConfig()
    config.context.ttl_seconds = 123
    config.style.prompts_dir = "my-prompts"

    config.save(path)
    loaded = AppConfig.load(path)

    assert loaded.context.ttl_seconds == 123
    assert loaded.style.prompts_dir == "my-prompts"
