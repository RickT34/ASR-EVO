from __future__ import annotations

from asr_evo.config import API_KEY_ENV, ASR_ENABLE_ITN, ASR_LANGUAGE, ASR_MAX_AUDIO_MB, AppConfig

from .aliyun_asr import AliyunASRProvider
from .openai_compat_llm import OpenAICompatibleLLMProvider


def create_llm_provider(config: AppConfig) -> OpenAICompatibleLLMProvider:
    api_key = config.api_key()
    if not api_key:
        raise RuntimeError(f"Missing API key in ${API_KEY_ENV}. Add it to .env.")
    return OpenAICompatibleLLMProvider(
        api_key=api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
    )


def create_asr_provider(config: AppConfig) -> AliyunASRProvider:
    api_key = config.api_key()
    if not api_key:
        raise RuntimeError(f"Missing API key in ${API_KEY_ENV}. Add it to .env.")
    return AliyunASRProvider(
        api_key=api_key,
        model=config.asr.model,
        base_url=config.asr.base_url,
        language=ASR_LANGUAGE,
        enable_itn=ASR_ENABLE_ITN,
        max_audio_mb=ASR_MAX_AUDIO_MB,
    )
