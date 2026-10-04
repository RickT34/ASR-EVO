from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing
from urllib.parse import urlsplit, urlunsplit

import soundfile as sf

from asr_evo.audio.pcm import PCM16StreamEncoder
from asr_evo.config import ASRConfig, RealtimeASRConfig
from asr_evo.core.ports import AudioClip, Transcript
from asr_evo.providers.dashscope_streaming import DashScopeStreamingASRProvider


def message_websocket_url(base_url: str) -> str:
    parts = urlsplit(base_url)
    if parts.scheme not in {"https", "wss"} or not parts.hostname:
        raise ValueError("dashscope_message.base_url 需要 https:// 或 wss:// 百炼地址")
    if parts.path.rstrip("/") not in {
        "", "/api/v1", "/compatible-mode/v1", "/api-ws/v1/inference", "/api-ws/v1/realtime",
    }:
        raise ValueError("Message 模型需要 /api-ws/v1/inference 接口")
    return urlunsplit(parts._replace(scheme="wss", path="/api-ws/v1/inference", fragment=""))


class DashScopeMessageASRProvider:
    """Send a completed recording through the native Message WebSocket protocol."""

    def __init__(self, config: ASRConfig, api_key: str) -> None:
        if not config.model.endswith("-asr-flash-message"):
            raise ValueError("dashscope_message 后端需要 ASR Message 模型，请检查 asr.model")
        self.timeout_seconds = config.timeout_seconds
        self.streaming = DashScopeStreamingASRProvider(
            RealtimeASRConfig(
                backend="dashscope", model=config.model,
                url=message_websocket_url(config.base_url),
                timeout_seconds=config.timeout_seconds,
            ),
            api_key,
        )
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    async def transcribe(self, audio: AudioClip) -> Transcript:
        if self._closed:
            raise RuntimeError("Message ASR provider is closed")
        task = asyncio.current_task()
        self._tasks.add(task)
        result = Transcript("")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with aclosing(self._chunks(audio)) as chunks:
                    async with aclosing(self.streaming.stream(chunks)) as results:
                        async for result in results:
                            pass
                return result
        except TimeoutError as exc:
            raise RuntimeError("Message ASR 转写超时 (timeout)，请检查网络和 asr.timeout_seconds") from exc
        finally:
            self._tasks.discard(task)

    async def _chunks(self, audio: AudioClip) -> AsyncIterator[bytes]:
        # Read bounded blocks, downmix and resample once, preserving the filter tail.
        # The live recorder uses this same PCM encoder.
        with sf.SoundFile(audio.path) as source:
            if not source.frames:
                raise ValueError("Message ASR 无法识别空录音")
            encoder = PCM16StreamEncoder(source.samplerate)
            while True:
                frames = source.read(max(1, source.samplerate // 10), dtype="float32", always_2d=True)
                if not len(frames):
                    break
                chunk = encoder.encode(frames)
                if chunk:
                    yield chunk
                await asyncio.sleep(0)
            tail = encoder.finish()
            if tail:
                yield tail

    async def aclose(self) -> None:
        self._closed = True
        pending = [task for task in self._tasks if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
