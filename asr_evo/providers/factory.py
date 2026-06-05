from __future__ import annotations

from asr_evo.config import API_KEY_ENV, PROVIDER_DEFAULTS, AppConfig
from asr_evo.providers.request_debug import RemoteRequestDebugOptions

from .openai_provider import (
    OpenAIChatCompletionsASRProvider,
    OpenAIChatCompletionsLLMProvider,
)


def create_llm_provider(config: AppConfig) -> OpenAIChatCompletionsLLMProvider:
    api_key = config.api_key()
    if not api_key:
        raise RuntimeError(f"Missing API key in ${API_KEY_ENV}. Add it to .env.")
    return OpenAIChatCompletionsLLMProvider(
        api_key=api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
        enable_thinking=config.llm.enable_thinking,
        request_debug=_request_debug_options(config),
    )


def create_asr_provider(config: AppConfig) -> OpenAIChatCompletionsASRProvider:
    api_key = config.api_key()
    if not api_key:
        raise RuntimeError(f"Missing API key in ${API_KEY_ENV}. Add it to .env.")
    return OpenAIChatCompletionsASRProvider(
        api_key=api_key,
        model=config.asr.model,
        base_url=config.asr.base_url,
        language=PROVIDER_DEFAULTS.asr_language,
        enable_itn=PROVIDER_DEFAULTS.asr_enable_itn,
        max_audio_mb=PROVIDER_DEFAULTS.asr_max_audio_mb,
        request_debug=_request_debug_options(config),
    )


def _request_debug_options(config: AppConfig) -> RemoteRequestDebugOptions:
    return RemoteRequestDebugOptions(
        enabled=config.debug.dump_remote_requests,
        include_large_values=config.debug.include_large_request_values,
        max_value_chars=config.debug.max_request_value_chars,
    )
