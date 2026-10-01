"""Standalone worker; may run in a separate qwen-asr virtual environment."""

from __future__ import annotations

import contextlib
import json
import sys


def transcribe(request: dict) -> dict:
    import torch
    from qwen_asr import Qwen3ASRModel

    device = request["device"]
    if device == "auto":
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    dtype = request["dtype"]
    if dtype == "auto":
        dtype = "bfloat16" if device.startswith("cuda") else "float32"
    model = Qwen3ASRModel.from_pretrained(
        request["model"],
        device_map=device,
        dtype=getattr(torch, dtype),
        max_inference_batch_size=1,
        max_new_tokens=512,
    )
    results = model.transcribe(audio=request["audio"], language=request["language"] or None)
    return {"text": results[0].text, "language": results[0].language}


def main() -> None:
    request = json.load(sys.stdin)
    # Libraries may print progress to stdout; reserve it for the result protocol.
    with contextlib.redirect_stdout(sys.stderr):
        result = transcribe(request)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
