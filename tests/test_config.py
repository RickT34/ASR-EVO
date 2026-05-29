from __future__ import annotations

from pathlib import Path

from asr_evo.config import AppConfig


def test_config_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = AppConfig()
    config.context.ttl_seconds = 123
    config.context.max_chars = 456
    config.context.scope = "window"
    config.style.prompts_dir = "my-prompts"
    config.style.app_styles["com.example.Editor"] = "会议纪要"
    config.audio.input_device = "3"
    config.status.idle_icon = "听写"
    config.status.reviewing_text = "确认文字"
    config.review.enabled = False
    config.debug.dump_remote_requests = True
    config.debug.max_request_value_chars = 99

    config.save(path)
    loaded = AppConfig.load(path)

    assert loaded.context.ttl_seconds == 123
    assert loaded.context.max_chars == 456
    assert loaded.context.scope == "window"
    assert loaded.style.prompts_dir == "my-prompts"
    assert loaded.style.app_styles["com.example.Editor"] == "会议纪要"
    assert loaded.audio.input_device == "3"
    assert loaded.status.idle_icon == "听写"
    assert loaded.status.reviewing_text == "确认文字"
    assert loaded.review.enabled is False
    assert loaded.debug.dump_remote_requests is True
    assert loaded.debug.max_request_value_chars == 99
