from __future__ import annotations

from pathlib import Path

import httpx

from asr_evo.providers.aliyun_asr import AliyunASRProvider
from asr_evo.providers.request_debug import RemoteRequestDebugOptions


def test_audio_data_url_uses_base64(tmp_path: Path) -> None:
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"abc")
    provider = AliyunASRProvider(api_key="test")

    data_url = provider._audio_data_url(audio)

    assert data_url == "data:audio/x-wav;base64,YWJj"


async def test_transcribe_dumps_sanitized_remote_request(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"abc")
    provider = AliyunASRProvider(
        api_key="test",
        request_debug=RemoteRequestDebugOptions(enabled=True),
    )

    async def fake_post(path: str, *, json):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": " hello ",
                            "annotations": [{"type": "audio_info", "language": "zh"}],
                        }
                    }
                ]
            },
            request=httpx.Request("POST", f"https://example.test{path}"),
        )

    monkeypatch.setattr(provider.client, "post", fake_post)

    transcript = await provider.transcribe(
        audio=type("Audio", (), {"path": audio, "sample_rate": 16000, "duration_seconds": 1.0})()
    )
    captured = capsys.readouterr()

    assert transcript.text == "hello"
    assert "ASR-EVO remote API request" in captured.err
    assert '"authorization": "<redacted>"' in captured.err
    assert "<data:audio/x-wav;base64, 3 bytes, 4 base64 chars>" in captured.err
    assert "Bearer test" not in captured.err
