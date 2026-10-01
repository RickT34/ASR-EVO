from __future__ import annotations

from pathlib import Path

from asr_evo.config import AppConfig, LLMProfileConfig


def test_config_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = AppConfig()
    config.context.ttl_seconds = 123
    config.context.max_chars = 456
    config.context.scope = "window"
    config.style.prompts_dir = "my-prompts"
    config.style.app_styles["com.example.Editor"] = "会议纪要"
    config.llm.profiles["balanced"].enable_thinking = True
    config.llm.profiles["deep"] = LLMProfileConfig(
        base_url="https://deep.example.test/v1",
        model="deep-model",
        api_key_env="DEEP_API_KEY",
        enable_thinking=True,
    )
    config.audio.input_device = "3"
    config.control.port = 9876
    config.hotkey.toggle = "ctrl+shift+space"
    config.hotkey.enabled = False
    config.hotkey.mode = "hold"
    config.status.idle_symbol = "mic.badge.plus"
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
    assert loaded.llm.profiles["balanced"].enable_thinking is True
    assert loaded.llm.profiles["deep"].model == "deep-model"
    assert loaded.llm.profiles["deep"].api_key_env == "DEEP_API_KEY"
    assert loaded.audio.input_device == "3"
    assert loaded.control.port == 9876
    assert loaded.hotkey.toggle == "ctrl+shift+space"
    assert loaded.hotkey.enabled is False
    assert loaded.hotkey.mode == "hold"
    assert loaded.status.idle_symbol == "mic.badge.plus"
    assert loaded.status.reviewing_text == "确认文字"
    assert loaded.review.enabled is False
    assert loaded.debug.dump_remote_requests is True
    assert loaded.debug.max_request_value_chars == 99


def test_config_reload_reads_updated_profile_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("LLM_API_KEY=first-key\n", encoding="utf-8")
    first = AppConfig.load()
    dotenv_path.write_text("LLM_API_KEY=second-key\n", encoding="utf-8")

    second = AppConfig.load()

    assert first.llm_api_key() == "first-key"
    assert second.llm_api_key() == "second-key"


def test_config_loads_separate_provider_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ASR_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEP_API_KEY", raising=False)
    config = AppConfig()
    config.llm.profiles["deep"] = LLMProfileConfig(
        base_url="https://deep.example.test/v1",
        model="deep-model",
        api_key_env="DEEP_API_KEY",
    )
    config.save(tmp_path / "config.toml")
    (tmp_path / ".env").write_text(
        "ASR_API_KEY=asr-key\nLLM_API_KEY=llm-key\nDEEP_API_KEY=deep-key\n",
        encoding="utf-8",
    )

    config = AppConfig.load()

    assert config.asr_api_key() == "asr-key"
    assert config.llm_api_key() == "llm-key"
    assert config.llm_api_key("deep") == "deep-key"


def test_config_rejects_missing_default_profile() -> None:
    try:
        AppConfig.model_validate(
            {
                "llm": {
                    "default_profile": "missing",
                    "profiles": {
                        "fast": {
                            "base_url": "https://example.test/v1",
                            "model": "fast-model",
                            "api_key_env": "FAST_API_KEY",
                        }
                    },
                }
            }
        )
    except ValueError as exc:
        assert "default LLM profile not found" in str(exc)
    else:
        raise AssertionError("expected missing default profile to fail validation")


def test_config_rejects_obsolete_flat_llm_fields() -> None:
    try:
        AppConfig.model_validate(
            {
                "llm": {
                    "base_url": "https://old.example.test/v1",
                    "model": "old-model",
                }
            }
        )
    except ValueError as exc:
        assert "Extra inputs are not permitted" in str(exc)
    else:
        raise AssertionError("expected obsolete flat LLM config to fail validation")
