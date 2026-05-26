from __future__ import annotations

import sys

from asr_evo.app import create_runtime
from asr_evo.config import AppConfig


def test_create_runtime_reports_unsupported_platform(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    try:
        create_runtime(AppConfig())
    except SystemExit as exc:
        assert "linux" in str(exc)
    else:
        raise AssertionError("expected unsupported platform to exit")
