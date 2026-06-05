from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from asr_evo.providers.openai_provider import (
    OpenAIChatCompletionsASRProvider,
    OpenAIChatCompletionsLLMProvider,
)
from asr_evo.providers.request_debug import RemoteRequestDebugOptions


def test_audio_data_url_uses_base64(tmp_path: Path) -> None:
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"abc")
    provider = OpenAIChatCompletionsASRProvider(api_key="test")

    data_url = provider._audio_data_url(audio)

    assert data_url == "data:audio/x-wav;base64,YWJj"


async def test_transcribe_dumps_sanitized_remote_request(
    tmp_path: Path, capsys
) -> None:
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"abc")
    provider = OpenAIChatCompletionsASRProvider(
        api_key="test",
        request_debug=RemoteRequestDebugOptions(enabled=True),
    )
    client = FakeOpenAIClient(
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=" hello ",
                        annotations=[{"type": "audio_info", "language": "zh"}],
                    )
                )
            ]
        )
    )
    provider.client = client

    transcript = await provider.transcribe(
        audio=type("Audio", (), {"path": audio, "sample_rate": 16000, "duration_seconds": 1.0})()
    )
    captured = capsys.readouterr()

    assert transcript.text == "hello"
    assert transcript.language == "zh"
    assert client.kwargs["model"] == "qwen3-asr-flash"
    assert client.kwargs["extra_body"] == {"asr_options": {"enable_itn": True, "language": "zh"}}
    audio_payload = client.kwargs["messages"][0]["content"][0]["input_audio"]["data"]
    assert audio_payload == "data:audio/x-wav;base64,YWJj"
    assert "ASR-EVO remote API request" in captured.err
    assert '"Authorization": "<redacted>"' in captured.err
    assert "<data:audio/x-wav;base64, 3 bytes, 4 base64 chars>" in captured.err
    assert "Bearer test" not in captured.err


async def test_llm_complete_json_uses_openai_client_and_response_format(capsys) -> None:
    provider = OpenAIChatCompletionsLLMProvider(
        api_key="test",
        base_url="https://example.test/v1",
        model="configured-model",
        enable_thinking=True,
        request_debug=RemoteRequestDebugOptions(enabled=True),
    )
    client = FakeOpenAIClient(
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"ok": true}'),
                )
            ]
        )
    )
    provider.client = client

    result = await provider.complete_json(
        [{"role": "user", "content": "Return JSON."}],
        temperature=0,
    )
    captured = capsys.readouterr()

    assert result == {"ok": True}
    assert client.kwargs == {
        "model": "configured-model",
        "messages": [{"role": "user", "content": "Return JSON."}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "extra_body": {"enable_thinking": True},
    }
    assert "ASR-EVO remote API request" in captured.err
    assert '"provider": "openai-llm"' in captured.err
    assert '"enable_thinking": true' in captured.err
    assert '"Authorization": "<redacted>"' in captured.err
    assert "Bearer test" not in captured.err


class FakeOpenAIClient:
    def __init__(self, response) -> None:
        self.response = response
        self.kwargs = {}
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.kwargs = kwargs
        return self.response
