from __future__ import annotations

from asr_evo.config import AppConfig
from asr_evo.providers import factory


def test_create_providers_uses_separate_endpoints_and_keys(monkeypatch) -> None:
    config = AppConfig()
    config.asr.base_url = "https://asr.example.test/v1"
    config.llm.base_url = "https://llm.example.test/v1"
    config._asr_api_key = "asr-key"
    config._llm_api_key = "llm-key"
    created = {}

    def create_asr(**kwargs):
        created["asr"] = kwargs
        return object()

    def create_llm(**kwargs):
        created["llm"] = kwargs
        return object()

    monkeypatch.setattr(factory, "OpenAIChatCompletionsASRProvider", create_asr)
    monkeypatch.setattr(factory, "OpenAIChatCompletionsLLMProvider", create_llm)

    factory.create_providers(config)

    assert created["asr"]["api_key"] == "asr-key"
    assert created["asr"]["base_url"] == "https://asr.example.test/v1"
    assert created["llm"]["api_key"] == "llm-key"
    assert created["llm"]["base_url"] == "https://llm.example.test/v1"
