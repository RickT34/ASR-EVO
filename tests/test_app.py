from __future__ import annotations

import sys

import pytest

from asr_evo.app import create_runtime
from asr_evo.config import AppConfig
from asr_evo.cli import insert_test


def test_create_runtime_reports_unsupported_platform(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    with pytest.raises(SystemExit, match="linux"):
        create_runtime(AppConfig())


def test_insert_test_cli_imports_and_reports_unsupported_platform(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "argv", ["asr-evo-insert-test", "hello"])

    with pytest.raises(SystemExit, match="only supports macOS"):
        insert_test.main()
