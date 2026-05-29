from __future__ import annotations

import sys

import pytest

from asr_evo.ui.text_review import TkTextReviewer, parse_review_process_result


async def test_tk_text_reviewer_runs_dialog_module_in_child_process() -> None:
    calls = []
    process = _FakeProcess(stdout="edited".encode(), stderr=b"", returncode=0)

    async def process_factory(*args, **kwargs):
        calls.append((args, kwargs))
        return process

    reviewer = TkTextReviewer(process_factory=process_factory)

    assert await reviewer.review("initial") == "edited"
    assert calls[0][0] == (sys.executable, "-m", "asr_evo.ui.text_review")
    assert process.input == "initial".encode()


def test_parse_review_process_result_returns_confirmed_text() -> None:
    assert parse_review_process_result(0, "确认文本".encode(), b"") == "确认文本"


def test_parse_review_process_result_returns_none_on_cancel() -> None:
    assert parse_review_process_result(2, b"", b"") is None


def test_parse_review_process_result_raises_stderr_on_failure() -> None:
    with pytest.raises(RuntimeError, match="tk failed"):
        parse_review_process_result(1, b"", b"tk failed")


class _FakeProcess:
    def __init__(self, *, stdout: bytes, stderr: bytes, returncode: int) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.input = b""

    async def communicate(self, input: bytes):
        self.input = input
        return self.stdout, self.stderr
