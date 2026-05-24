from __future__ import annotations

from pathlib import Path

import httpx

from asr_evo.core.ports import AudioClip, Transcript


class AliyunASRProvider:
    """DashScope Qwen-ASR adapter.

    The exact API payload can vary by model and release channel. This adapter keeps the dependency
    isolated so the rest of the app does not care whether ASR uses DashScope native APIs,
    OpenAI-compatible APIs, or a local service.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "qwen3-asr-flash",
        endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        timeout_seconds: float = 60,
    ) -> None:
        self.model = model
        self.endpoint = endpoint
        self.client = httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={
                "Authorization": f"Bearer {api_key}",
                "X-DashScope-DataInspection": "enable",
            },
        )

    async def transcribe(self, audio: AudioClip) -> Transcript:
        audio_path = Path(audio.path)
        if not audio_path.exists():
            raise FileNotFoundError(audio_path)

        # Placeholder shape for the native DashScope adapter. The provider is intentionally
        # isolated because Qwen-ASR local-file upload details are likely to be the first thing
        # we tune against real credentials.
        raise NotImplementedError(
            "Aliyun Qwen-ASR transport is isolated here and should be completed with real "
            "DashScope credentials/API shape before enabling live transcription."
        )

    async def aclose(self) -> None:
        await self.client.aclose()
