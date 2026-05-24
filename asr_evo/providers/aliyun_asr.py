from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

import httpx

from asr_evo.core.ports import AudioClip, Transcript
from asr_evo.providers.http_retry import raise_provider_status, with_http_retries


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
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        language: str | None = "zh",
        enable_itn: bool = True,
        max_audio_mb: int = 10,
        timeout_seconds: float = 60,
    ) -> None:
        self.model = model
        self.language = language
        self.enable_itn = enable_itn
        self.max_audio_bytes = max_audio_mb * 1024 * 1024
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={
                "Authorization": f"Bearer {api_key}",
            },
        )

    async def transcribe(self, audio: AudioClip) -> Transcript:
        audio_path = Path(audio.path)
        if not audio_path.exists():
            raise FileNotFoundError(audio_path)
        size = audio_path.stat().st_size
        if size > self.max_audio_bytes:
            raise ValueError(f"Audio file is {size} bytes, exceeding configured ASR limit")

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": self._audio_data_url(audio_path),
                            },
                        }
                    ],
                }
            ],
            "asr_options": self._asr_options(),
            "stream": False,
        }
        response = await with_http_retries(
            lambda: self.client.post("/chat/completions", json=payload)
        )
        raise_provider_status(response)
        data = response.json()
        message = data["choices"][0]["message"]
        language = None
        for annotation in message.get("annotations", []):
            if annotation.get("type") == "audio_info":
                language = annotation.get("language")
                break
        return Transcript(text=message["content"].strip(), language=language)

    def _asr_options(self) -> dict[str, object]:
        options: dict[str, object] = {"enable_itn": self.enable_itn}
        if self.language:
            options["language"] = self.language
        return options

    def _audio_data_url(self, path: Path) -> str:
        mime_type = mimetypes.guess_type(path.name)[0] or "audio/wav"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    async def aclose(self) -> None:
        await self.client.aclose()
