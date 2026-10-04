from __future__ import annotations

import asyncio

import httpx
import numpy as np
import pytest
import soundfile as sf

from asr_evo.config import ASRConfig, AppConfig
from asr_evo.core.ports import AudioClip, Transcript
from asr_evo.providers.dashscope_message import DashScopeMessageASRProvider, message_websocket_url
from asr_evo.providers.dashscope_filetrans import _check_status
from asr_evo.providers.factory import create_asr_provider


def config():
    return ASRConfig(backend="dashscope_message", model="qwen-audio-3.1-asr-flash-message",
                     base_url="wss://dashscope.aliyuncs.com/api-ws/v1/inference")


async def test_message_resamples_stereo_and_returns_latest_result(tmp_path, monkeypatch):
    path = tmp_path / "stereo.wav"
    sf.write(path, np.ones((48000, 2), dtype="float32") * 0.2, 48000)
    provider = DashScopeMessageASRProvider(config(), "test-key")
    received = []
    closed = []

    async def stream(chunks):
        try:
            async for chunk in chunks:
                received.append(chunk)
                yield Transcript("草稿")
            yield Transcript("最终识别文本")
        finally:
            closed.append(True)

    monkeypatch.setattr(provider.streaming, "stream", stream)
    result = await provider.transcribe(AudioClip(path, 48000, 1))
    assert result.text == "最终识别文本"
    assert len(b"".join(received)) == 16000 * 2
    assert len(received) > 1
    assert closed == [True]
    assert not provider._tasks
    assert path.exists()
    await provider.aclose()


async def test_message_close_cancels_inflight_session(tmp_path, monkeypatch):
    provider = DashScopeMessageASRProvider(config(), "test-key")
    started = asyncio.Event()
    closed = asyncio.Event()

    async def stream(chunks):
        try:
            started.set()
            await asyncio.Event().wait()
            yield Transcript("")
        finally:
            closed.set()

    monkeypatch.setattr(provider.streaming, "stream", stream)
    task = asyncio.create_task(provider.transcribe(AudioClip(tmp_path / "unused", 16000, 1)))
    await started.wait()
    await provider.aclose()
    assert task.cancelled() and closed.is_set()


def test_message_url_preserves_workspace_and_region():
    assert message_websocket_url("https://space.ap-southeast-1.maas.aliyuncs.com/api/v1") == (
        "wss://space.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/inference"
    )


async def test_message_backend_is_selected_explicitly(monkeypatch):
    monkeypatch.setenv("ASR_API_KEY", "key")
    app = AppConfig(asr=config())
    provider = create_asr_provider(app)
    assert isinstance(provider, DashScopeMessageASRProvider)
    assert provider.streaming.task_protocol
    await provider.aclose()


def test_filetrans_http_error_preserves_diagnostics_without_signed_urls():
    response = httpx.Response(400, json={"code": "InvalidParameter", "message": "model not supported https://example/a?Signature=secret sk-secret123", "request_id": "request-123"})
    with pytest.raises(RuntimeError) as captured:
        _check_status(response, "提交转写任务")
    assert "InvalidParameter" in str(captured.value)
    assert "request-123" in str(captured.value)
    assert "secret" not in str(captured.value)
