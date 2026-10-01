from __future__ import annotations

from asr_evo.config import PROVIDER_DEFAULTS, AppConfig, LLMProfileConfig
from asr_evo.providers.llm_router import LLMProfileRouter
from asr_evo.providers.request_debug import RemoteRequestDebugOptions

from .openai_provider import (
    OpenAIChatCompletionsASRProvider,
    OpenAIChatCompletionsLLMProvider,
)


def create_providers(
    config: AppConfig,
) -> tuple[OpenAIChatCompletionsASRProvider, LLMProfileRouter]:
    return create_asr_provider(config), create_llm_provider(config)


def provider_config_changed(current: AppConfig, updated: AppConfig) -> bool:
    return (
        current.asr,
        current.llm,
        current.debug,
        current.asr_api_key(),
        current.llm_api_keys(),
    ) != (
        updated.asr,
        updated.llm,
        updated.debug,
        updated.asr_api_key(),
        updated.llm_api_keys(),
    )


def create_llm_provider(config: AppConfig) -> LLMProfileRouter:
    profile_specs = {
        alias: (profile, _require_profile_api_key(config, alias, profile))
        for alias, profile in config.llm.profiles.items()
    }
    profiles = {
        alias: _create_llm_client(config, profile, api_key)
        for alias, (profile, api_key) in profile_specs.items()
    }
    default_provider = profiles[config.llm.default_profile]
    return LLMProfileRouter(default_provider=default_provider, profiles=profiles)


def create_asr_provider(config: AppConfig) -> OpenAIChatCompletionsASRProvider:
    api_key = config.asr_api_key()
    if not api_key:
        raise RuntimeError(
            f"Missing ASR API key in ${config.asr.api_key_env}. Add it to .env."
        )
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


def _create_llm_client(
    config: AppConfig,
    profile: LLMProfileConfig,
    api_key: str,
) -> OpenAIChatCompletionsLLMProvider:
    return OpenAIChatCompletionsLLMProvider(
        api_key=api_key,
        base_url=profile.base_url,
        model=profile.model,
        enable_thinking=profile.enable_thinking,
        request_debug=_request_debug_options(config),
    )


def _require_profile_api_key(
    config: AppConfig,
    alias: str,
    profile: LLMProfileConfig,
) -> str:
    api_key = config.llm_api_key(alias)
    if api_key:
        return api_key
    raise _missing_llm_api_key(profile.api_key_env, alias)


def _missing_llm_api_key(api_key_env: str, alias: str) -> RuntimeError:
    return RuntimeError(
        f"Missing LLM API key for profile '{alias}' in ${api_key_env}. Add it to .env."
    )
