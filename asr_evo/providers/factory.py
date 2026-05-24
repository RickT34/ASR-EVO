from __future__ import annotations

from asr_evo.config import AppConfig

from .aliyun_asr import AliyunASRProvider
from .openai_compat_llm import OpenAICompatibleLLMProvider


def create_llm_provider(config: AppConfig) -> OpenAICompatibleLLMProvider:
    api_key = config.llm_api_key()
    if not api_key:
        raise RuntimeError(f"Missing API key in ${config.llm.api_key_env}")
    if config.llm.provider != "openai_compat":
        raise ValueError(f"Unsupported LLM provider: {config.llm.provider}")
    return OpenAICompatibleLLMProvider(
        api_key=api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
    )


def create_asr_provider(config: AppConfig) -> AliyunASRProvider:
    api_key = config.asr_api_key()
    if not api_key:
        raise RuntimeError(f"Missing API key in ${config.asr.api_key_env}")
    if config.asr.provider != "aliyun":
        raise ValueError(f"Unsupported ASR provider: {config.asr.provider}")
    return AliyunASRProvider(api_key=api_key, model=config.asr.model)
