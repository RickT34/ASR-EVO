"""One vLLM streaming session per subprocess; stdout is JSON protocol only."""
from __future__ import annotations

import base64
import json
import os
import sys


def run_session(request, messages, emit, model_factory=None) -> None:
    import numpy as np

    if model_factory is None:
        from qwen_asr import Qwen3ASRModel

        model_factory = Qwen3ASRModel.LLM
    model = model_factory(
        model=request["model"],
        gpu_memory_utilization=request["gpu_memory_utilization"],
        max_new_tokens=32,
    )
    state = model.init_streaming_state(
        language=request["language"] or None,
        chunk_size_sec=request["chunk_size_seconds"],
        unfixed_chunk_num=2,
        unfixed_token_num=5,
    )
    emit({"type": "ready"})
    for line in messages:
        message = json.loads(line)
        if message["type"] == "finish":
            model.finish_streaming_transcribe(state)
            emit({"type": "transcript", "text": state.text, "language": state.language})
            emit({"type": "done"})
            return
        if message["type"] != "audio":
            raise ValueError("Unexpected streaming worker message")
        pcm = np.frombuffer(base64.b64decode(message["audio"], validate=True), dtype="<i2")
        model.streaming_transcribe(pcm.astype(np.float32) / 32768, state)
        emit({"type": "transcript", "text": state.text, "language": state.language})
    raise RuntimeError("Streaming audio input closed before finish")


def main() -> None:
    # vLLM subprocess/native-library logs can bypass redirect_stdout.
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    request = json.loads(sys.stdin.readline())
    run_session(request, sys.stdin, lambda event: print(json.dumps(event), file=protocol))


if __name__ == "__main__":
    main()
