from __future__ import annotations

import pytest

from asr_evo.config import AppConfig, LLMProfileConfig
from asr_evo.providers import factory
from asr_evo.providers.llm_router import LLMProfileRouter


def test_factory_builds_each_provider_from_its_configured_endpoint_and_key(
    monkeypatch,
) -> None:
    config = _profile_config()
    monkeypatch.setenv("ASR_API_KEY", "asr-key")
    monkeypatch.setenv("FAST_API_KEY", "fast-key")
    monkeypatch.setenv("DEEP_API_KEY", "deep-key")
    created = {}

    def create_asr(**kwargs):
        created["asr"] = kwargs
        return object()

    def create_llm(**kwargs):
        provider = FakeLLMProvider(kwargs)
        created[kwargs["model"]] = provider
        return provider

    monkeypatch.setattr(factory, "OpenAIChatCompletionsASRProvider", create_asr)
    monkeypatch.setattr(factory, "OpenAIChatCompletionsLLMProvider", create_llm)

    _, router = factory.create_providers(config)

    assert router.default_provider is created["fast-model"]
    assert created["asr"]["api_key"] == "asr-key"
    assert created["asr"]["base_url"] == "https://asr.example.test/v1"
    assert created["fast-model"].kwargs["api_key"] == "fast-key"
    assert created["fast-model"].kwargs["base_url"] == "https://fast.example.test/v1"
    assert created["deep-model"].kwargs["api_key"] == "deep-key"
    assert created["deep-model"].kwargs["base_url"] == "https://deep.example.test/v1"
    assert created["deep-model"].kwargs["enable_thinking"] is True


def test_factory_rejects_missing_profile_key_before_creating_llm_clients(monkeypatch) -> None:
    config = _profile_config()
    monkeypatch.setenv("FAST_API_KEY", "fast-key")
    monkeypatch.delenv("DEEP_API_KEY", raising=False)
    created_models = []

    def create_llm(**kwargs):
        created_models.append(kwargs["model"])
        return FakeLLMProvider(kwargs)

    monkeypatch.setattr(factory, "OpenAIChatCompletionsLLMProvider", create_llm)

    with pytest.raises(RuntimeError, match=r"profile 'deep'.*\$DEEP_API_KEY"):
        factory.create_llm_provider(config)

    assert created_models == []


async def test_router_uses_default_provider_when_template_has_no_profile() -> None:
    fast = FakeLLMProvider({})
    deep = FakeLLMProvider({})
    router = LLMProfileRouter(default_provider=fast, profiles={"fast": fast, "deep": deep})

    result = await router.polish("raw", "context", "prompt")

    assert result == "polished"
    assert fast.calls == [("raw", "context", "prompt")]
    assert deep.calls == []


async def test_router_uses_profile_selected_by_template() -> None:
    fast = FakeLLMProvider({})
    deep = FakeLLMProvider({})
    router = LLMProfileRouter(default_provider=fast, profiles={"fast": fast, "deep": deep})

    result = await router.polish("raw", "context", "prompt", profile="deep")

    assert result == "polished"
    assert fast.calls == []
    assert deep.calls == [("raw", "context", "prompt")]


async def test_router_rejects_unknown_template_profile() -> None:
    fast = FakeLLMProvider({})
    router = LLMProfileRouter(default_provider=fast, profiles={"fast": fast})

    with pytest.raises(ValueError, match="LLM profile not found: missing"):
        await router.polish("raw", "context", "prompt", profile="missing")


async def test_router_uses_default_provider_for_json_calls() -> None:
    fast = FakeLLMProvider({})
    deep = FakeLLMProvider({})
    router = LLMProfileRouter(default_provider=fast, profiles={"fast": fast, "deep": deep})

    result = await router.complete_json([{"role": "user", "content": "JSON"}], temperature=0.1)

    assert result == {"ok": True}
    assert fast.json_calls == [([{"role": "user", "content": "JSON"}], 0.1)]
    assert deep.json_calls == []


async def test_router_closes_each_client_once_when_default_is_also_named() -> None:
    fast = FakeLLMProvider({})
    deep = FakeLLMProvider({})
    router = LLMProfileRouter(default_provider=fast, profiles={"fast": fast, "deep": deep})

    await router.aclose()

    assert fast.close_count == 1
    assert deep.close_count == 1


def _profile_config() -> AppConfig:
    config = AppConfig()
    config.asr.base_url = "https://asr.example.test/v1"
    config.llm.default_profile = "fast"
    config.llm.profiles = {
        "fast": LLMProfileConfig(
            base_url="https://fast.example.test/v1",
            model="fast-model",
            api_key_env="FAST_API_KEY",
        ),
        "deep": LLMProfileConfig(
            base_url="https://deep.example.test/v1",
            model="deep-model",
            api_key_env="DEEP_API_KEY",
            enable_thinking=True,
        ),
    }
    return config


class FakeLLMProvider:
    def __init__(self, kwargs) -> None:
        self.kwargs = kwargs
        self.calls = []
        self.json_calls = []
        self.close_count = 0

    async def polish(self, raw_text, context, prompt_instruction):
        self.calls.append((raw_text, context, prompt_instruction))
        return "polished"

    async def complete_json(self, messages, *, temperature=0):
        self.json_calls.append((messages, temperature))
        return {"ok": True}

    async def aclose(self) -> None:
        self.close_count += 1
