from __future__ import annotations

from pathlib import Path

from asr_evo.providers.aliyun_asr import AliyunASRProvider


def test_audio_data_url_uses_base64(tmp_path: Path) -> None:
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"abc")
    provider = AliyunASRProvider(api_key="test")

    data_url = provider._audio_data_url(audio)

    assert data_url == "data:audio/x-wav;base64,YWJj"
