from __future__ import annotations

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
    key_update = current.model_copy(deep=True)
    key_update._api_key = "replacement-key"

    assert provider_config_changed(current, ui_only) is False
    assert provider_config_changed(current, provider_update) is True
    assert provider_config_changed(current, key_update) is True


def test_macos_runtime_replaces_providers_after_config_reload(monkeypatch) -> None:
    runtime = object.__new__(macos_runtime.MacOSDictationRuntime)
    runtime.control_server = _ControlServer()
    runtime.tray = _Tray()
    runtime.controller = _Controller()
    providers = (object(), object())
    monkeypatch.setattr(macos_runtime, "create_providers", lambda config: providers)
    updated = runtime.controller.config.model_copy(deep=True)
    updated.llm.model = "replacement-model"

    runtime.apply_config(updated)

    assert runtime.controller.providers == providers


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
    port = 8765


class _Tray:
    pass


class _Hotkey:
    def __init__(self) -> None:
        self.config = None

    def apply_config(self, config) -> None:
        self.config = config
