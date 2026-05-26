from __future__ import annotations

import json

from asr_evo.providers.request_debug import RemoteRequestDebugOptions, format_remote_request


def test_format_remote_request_redacts_headers_and_summarizes_audio() -> None:
    formatted = format_remote_request(
        provider="test",
        method="POST",
        url="https://example.test/v1/chat/completions",
        headers={"Authorization": "Bearer secret", "Content-Type": "application/json"},
        json_payload={
            "model": "qwen3-asr-flash",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {"data": "data:audio/wav;base64,YWJj"},
                        }
                    ],
                }
            ],
        },
        options=RemoteRequestDebugOptions(enabled=True),
    )

    data = json.loads(formatted)

    assert data["headers"]["Authorization"] == "<redacted>"
    assert data["headers"]["Content-Type"] == "application/json"
    audio = data["json"]["messages"][0]["content"][0]["input_audio"]["data"]
    assert audio == "<data:audio/wav;base64, 3 bytes, 4 base64 chars>"


def test_format_remote_request_can_include_large_values() -> None:
    formatted = format_remote_request(
        provider="test",
        method="POST",
        url="https://example.test/v1/chat/completions",
        headers={},
        json_payload={"audio": "data:audio/wav;base64,YWJj"},
        options=RemoteRequestDebugOptions(enabled=True, include_large_values=True),
    )

    data = json.loads(formatted)

    assert data["json"]["audio"] == "data:audio/wav;base64,YWJj"
