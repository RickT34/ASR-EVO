from __future__ import annotations

import base64
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TextIO


@dataclass(frozen=True)
class RemoteRequestDebugOptions:
    enabled: bool = False
    include_large_values: bool = False
    max_value_chars: int = 4000


def dump_remote_request(
    *,
    provider: str,
    method: str,
    url: str,
    headers: dict[str, str],
    json_payload: dict[str, Any],
    options: RemoteRequestDebugOptions,
    stream: TextIO | None = None,
) -> None:
    if not options.enabled:
        return
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "method": method,
        "url": url,
        "headers": _redact_headers(headers),
        "json": _sanitize_json_value(json_payload, options),
    }
    target = stream or sys.stderr
    target.write("=== ASR-EVO remote API request ===\n")
    target.write(json.dumps(output, ensure_ascii=False, indent=2))
    target.write("\n=== end remote API request ===\n")
    target.flush()


def format_remote_request(
    *,
    provider: str,
    method: str,
    url: str,
    headers: dict[str, str],
    json_payload: dict[str, Any],
    options: RemoteRequestDebugOptions,
) -> str:
    output = {
        "timestamp": "<dynamic>",
        "provider": provider,
        "method": method,
        "url": url,
        "headers": _redact_headers(headers),
        "json": _sanitize_json_value(json_payload, options),
    }
    return json.dumps(output, ensure_ascii=False, indent=2)


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    redacted = {}
    for key, value in headers.items():
        if key.lower() in {"authorization", "api-key", "x-api-key"}:
            redacted[key] = "<redacted>"
        else:
            redacted[key] = value
    return redacted


def _sanitize_json_value(value: Any, options: RemoteRequestDebugOptions) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_json_value(item, options) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_json_value(item, options) for item in value]
    if isinstance(value, str):
        return _sanitize_string(value, options)
    return value


def _sanitize_string(value: str, options: RemoteRequestDebugOptions) -> str:
    if options.include_large_values:
        return value
    if value.startswith("data:") and ";base64," in value:
        prefix, encoded = value.split(",", 1)
        decoded_bytes = _decoded_base64_size(encoded)
        return f"<{prefix}, {decoded_bytes} bytes, {len(encoded)} base64 chars>"
    if len(value) <= options.max_value_chars:
        return value
    visible = max(0, options.max_value_chars)
    return f"{value[:visible]}... <truncated, {len(value)} chars total>"


def _decoded_base64_size(encoded: str) -> int:
    try:
        return len(base64.b64decode(encoded, validate=True))
    except ValueError:
        return -1
