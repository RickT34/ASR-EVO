from __future__ import annotations

import sys

import pytest

from asr_evo.app import create_runtime
from asr_evo.config import AppConfig
from asr_evo.cli import insert_test


def test_create_runtime_reports_unsupported_platform(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "freebsd")

    with pytest.raises(SystemExit, match="freebsd"):
        create_runtime(AppConfig())


def test_insert_test_cli_imports_and_reports_unsupported_platform(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "argv", ["asr-evo-insert-test", "hello"])

    with pytest.raises(SystemExit, match="only supports macOS"):
        insert_test.main()


def test_create_runtime_selects_linux(monkeypatch):
    from asr_evo.platforms.linux import runtime

    config = AppConfig()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(runtime, "LinuxDictationRuntime", lambda config: ("linux", config))
    assert create_runtime(config) == ("linux", config)
