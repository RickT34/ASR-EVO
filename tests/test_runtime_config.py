from __future__ import annotations

import pytest

from asr_evo.config import AppConfig
from asr_evo.platforms.macos import runtime as macos_runtime
from asr_evo.platforms.windows import runtime as windows_runtime
from asr_evo.providers.factory import provider_config_changed


def test_provider_config_change_detection_ignores_local_ui_settings(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "current-key")
    current = AppConfig()
    ui_only = current.model_copy(deep=True)
    ui_only.review.enabled = False
    provider_update = current.model_copy(deep=True)
    provider_update.llm.model = "replacement-model"
    asr_key_update = current.model_copy(deep=True)
    asr_key_update._asr_api_key = "replacement-asr-key"
    llm_key_update = current.model_copy(deep=True)
    llm_key_update._llm_api_key = "replacement-llm-key"

    assert provider_config_changed(current, ui_only) is False
    assert provider_config_changed(current, provider_update) is True
    assert provider_config_changed(current, asr_key_update) is True
    assert provider_config_changed(current, llm_key_update) is True


def test_macos_runtime_replaces_providers_after_config_reload(monkeypatch) -> None:
    runtime = object.__new__(macos_runtime.MacOSDictationRuntime)
    runtime.control_server = _ControlServer()
    runtime.tray = _Tray()
    runtime.hotkey = _Hotkey()
    runtime.lifecycle = _Lifecycle()
    runtime.controller = _Controller()
    providers = (object(), object())
    monkeypatch.setattr(macos_runtime, "create_providers", lambda config: providers)
    updated = runtime.controller.config.model_copy(deep=True)
    updated.llm.model = "replacement-model"

    runtime.apply_config(updated)

    assert runtime.controller.providers == providers
    assert runtime.hotkey.config == updated.hotkey


def test_macos_runtime_replaces_hotkey_after_config_reload() -> None:
    runtime = object.__new__(macos_runtime.MacOSDictationRuntime)
    runtime.control_server = _ControlServer()
    runtime.tray = _Tray()
    previous_hotkey = _Hotkey()
    runtime.hotkey = previous_hotkey
    runtime.lifecycle = _Lifecycle()
    runtime.controller = _Controller()
    updated = runtime.controller.config.model_copy(deep=True)
    updated.hotkey.toggle = "cmd+shift+space"
    replacement = _Hotkey(updated.hotkey)
    runtime._create_hotkey = lambda config: replacement

    runtime.apply_config(updated)

    assert previous_hotkey.stopped is True
    assert replacement.started is True
    assert runtime.hotkey is replacement
    assert runtime.lifecycle.callback == replacement.stop


def test_macos_runtime_rolls_back_prepared_services_when_hotkey_cannot_start(
    monkeypatch,
) -> None:
    runtime = object.__new__(macos_runtime.MacOSDictationRuntime)
    previous_server = _ControlServer()
    runtime.control_server = previous_server
    runtime.loop = object()
    runtime.tray = _Tray()
    previous_hotkey = _Hotkey()
    runtime.hotkey = previous_hotkey
    runtime.lifecycle = _Lifecycle()
    runtime.controller = _Controller()
    updated = runtime.controller.config.model_copy(deep=True)
    updated.control.port = 8766
    updated.hotkey.toggle = "cmd+shift+space"
    replacement = _Hotkey(updated.hotkey, start_error=RuntimeError("event tap unavailable"))
    replacement_server = _ControlServer(port=8766)
    monkeypatch.setattr(macos_runtime, "DictationControlServer", lambda **kwargs: replacement_server)
    runtime._create_hotkey = lambda config: replacement

    with pytest.raises(RuntimeError, match="event tap unavailable"):
        runtime.apply_config(updated)

    assert previous_hotkey.stopped is False
    assert runtime.hotkey is previous_hotkey
    assert replacement.stopped is True
    assert replacement_server.started is True
    assert replacement_server.stopped is True
    assert runtime.control_server is previous_server


def test_windows_runtime_replaces_providers_after_config_reload(monkeypatch) -> None:
    runtime = object.__new__(windows_runtime.WindowsDictationRuntime)
    runtime.control_server = _ControlServer()
    runtime.tray = _Tray()
    runtime.hotkey = _Hotkey()
    runtime.controller = _Controller()
    providers = (object(), object())
    monkeypatch.setattr(windows_runtime, "create_providers", lambda config: providers)
    updated = runtime.controller.config.model_copy(deep=True)
    updated.asr.model = "replacement-model"

    runtime.apply_config(updated)

    assert runtime.controller.providers == providers
    assert runtime.hotkey.config is updated.hotkey


class _Controller:
    def __init__(self) -> None:
        self.config = AppConfig()
        self.providers = None

    def replace_providers(self, *providers) -> None:
        self.providers = providers


class _ControlServer:
    def __init__(self, port=8765) -> None:
        self.port = port
        self.started = False
        self.stopped = False

    def start(self, loop) -> None:
        self.started = True

    def stop(self, loop) -> None:
        self.stopped = True


class _Tray:
    pass


class _Hotkey:
    def __init__(self, config=None, *, start_error=None) -> None:
        self.config = config or AppConfig().hotkey
        self.start_error = start_error
        self.started = False
        self.stopped = False

    def start(self) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def apply_config(self, config) -> None:
        self.config = config


class _Lifecycle:
    def bind(self, callback) -> None:
        self.callback = callback
