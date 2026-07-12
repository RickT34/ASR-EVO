from __future__ import annotations

import sys

import pytest

from asr_evo.core.ports import (
    TextReviewPreviewRequest,
    TextReviewRequest,
    TextReviewResult,
    TextReviewSaveRequest,
    TextReviewSaveResult,
    TextReviewStyle,
)
from asr_evo.ui import text_review
from asr_evo.ui.text_review import (
    TkTextReviewer,
    configure_stdio_encoding,
    parse_review_process_result,
    review_confirmation_ready,
)


async def test_tk_text_reviewer_runs_dialog_module_in_child_process() -> None:
    calls = []
    process = _FakeProcess(
        stdout=[
            {
                "type": "confirm",
                "text": "edited",
                "polished_text": "polished",
                "style_id": "通用润色",
                "prompt_instruction": "polish",
            }
        ],
        stderr=b"",
        returncode=0,
    )

    async def process_factory(*args, **kwargs):
        calls.append((args, kwargs))
        return process

    reviewer = TkTextReviewer(process_factory=process_factory)
    request = _review_request()

    assert await reviewer.review(request, _previewer, _saver) == TextReviewResult(
        text="edited",
        polished_text="polished",
        style_id="通用润色",
        prompt_instruction="polish",
    )
    assert calls[0][0] == (sys.executable, "-X", "utf8", "-m", "asr_evo.ui.text_review")
    assert calls[0][1]["env"]["PYTHONUTF8"] == "1"
    assert calls[0][1]["env"]["PYTHONIOENCODING"] == "utf-8"
    assert b'"type": "init"' in process.input
    assert "initial".encode() in process.input


async def test_tk_text_reviewer_handles_preview_round_trip() -> None:
    process = _FakeProcess(
        stdout=[
            {
                "type": "preview",
                "id": "1",
                "style_id": "通用润色",
                "prompt_instruction": "custom",
            },
            {
                "type": "confirm",
                "text": "accepted",
                "polished_text": "previewed",
                "style_id": "通用润色",
                "prompt_instruction": "custom",
            },
        ],
        stderr=b"",
        returncode=0,
    )
    async def process_factory(*args, **kwargs):
        return process

    reviewer = TkTextReviewer(process_factory=process_factory)

    result = await reviewer.review(_review_request(), _previewer, _saver)

    assert result is not None
    assert result.text == "accepted"
    assert b'"type": "preview_result"' in process.input
    assert b'"polished_text": "previewed"' in process.input


async def test_tk_text_reviewer_handles_save_round_trip() -> None:
    process = _FakeProcess(
        stdout=[
            {
                "type": "save",
                "id": "1",
                "style_id": "通用润色",
                "prompt_instruction": "saved prompt",
            },
            {
                "type": "confirm",
                "text": "accepted",
                "polished_text": "initial",
                "style_id": "通用润色",
                "prompt_instruction": "saved prompt",
            },
        ],
        stderr=b"",
        returncode=0,
    )

    async def process_factory(*args, **kwargs):
        return process

    reviewer = TkTextReviewer(process_factory=process_factory)

    result = await reviewer.review(_review_request(), _previewer, _saver)

    assert result is not None
    assert result.prompt_instruction == "saved prompt"
    assert b'"type": "save_result"' in process.input
    assert "已保存".encode() in process.input


def test_parse_review_process_result_returns_confirmed_text() -> None:
    assert (
        parse_review_process_result(
            0,
            b'{"type":"confirm","text":"\\u786e\\u8ba4\\u6587\\u672c"}\n',
            b"",
        )
        == "确认文本"
    )


def test_parse_review_process_result_returns_none_on_cancel() -> None:
    assert parse_review_process_result(2, b"", b"") is None


def test_parse_review_process_result_raises_stderr_on_failure() -> None:
    with pytest.raises(RuntimeError, match="tk failed"):
        parse_review_process_result(1, b"", b"tk failed")


def test_review_confirmation_waits_for_pending_preview_work() -> None:
    assert review_confirmation_ready(io_busy=False, preview_scheduled=False) is True
    assert review_confirmation_ready(io_busy=True, preview_scheduled=False) is False
    assert review_confirmation_ready(io_busy=False, preview_scheduled=True) is False


def test_configure_stdio_encoding_reconfigures_all_standard_streams(monkeypatch) -> None:
    streams = {
        "stdin": _FakeTextStream(),
        "stdout": _FakeTextStream(),
        "stderr": _FakeTextStream(),
    }
    monkeypatch.setattr(text_review.sys, "stdin", streams["stdin"])
    monkeypatch.setattr(text_review.sys, "stdout", streams["stdout"])
    monkeypatch.setattr(text_review.sys, "stderr", streams["stderr"])

    configure_stdio_encoding()

    assert streams["stdin"].encoding == "utf-8"
    assert streams["stdout"].encoding == "utf-8"
    assert streams["stderr"].encoding == "utf-8"


class _FakeProcess:
    def __init__(self, *, stdout: list[dict], stderr: bytes, returncode: int) -> None:
        self.stdout = _FakeStdout(stdout)
        self.stderr = _FakeStderr(stderr)
        self.returncode = returncode
        self.stdin = _FakeStdin(self)
        self.input = b""

    async def wait(self) -> int:
        return self.returncode


class _FakeStdout:
    def __init__(self, messages: list[dict]) -> None:
        self.lines = [
            (__import__("json").dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
            for message in messages
        ]

    async def readline(self) -> bytes:
        if not self.lines:
            return b""
        return self.lines.pop(0)


class _FakeStdin:
    def __init__(self, process: _FakeProcess) -> None:
        self.process = process

    def write(self, data: bytes) -> None:
        self.process.input += data

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


class _FakeStderr:
    def __init__(self, data: bytes) -> None:
        self.data = data

    async def read(self) -> bytes:
        return self.data


class _FakeTextStream:
    def __init__(self) -> None:
        self.encoding = ""

    def reconfigure(self, *, encoding: str) -> None:
        self.encoding = encoding


def _review_request() -> TextReviewRequest:
    return TextReviewRequest(
        raw_text="raw",
        polished_text="initial",
        style_id="通用润色",
        prompt_instruction="polish",
        styles=[TextReviewStyle(id="通用润色", label="通用润色", prompt="polish")],
    )


async def _previewer(request: TextReviewPreviewRequest) -> str:
    assert request.prompt_instruction == "custom"
    return "previewed"


async def _saver(request: TextReviewSaveRequest) -> TextReviewSaveResult:
    if request.prompt_instruction != "saved prompt":
        raise AssertionError(request.prompt_instruction)
    return TextReviewSaveResult(message="已保存")
