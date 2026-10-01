from __future__ import annotations

import json
import sys
from dataclasses import fields

from asr_evo.cli import control
from asr_evo.config import AppConfig, LinuxConfig, StatusConfig
from asr_evo.platforms.linux import desktop
from asr_evo.platforms.linux.tray import LinuxStatusTray
from asr_evo.ui.menu import TrayMenuActions
from asr_evo.ui.waybar import waybar_status


def test_hyprland_context(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "test")
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        return json.dumps({"class": "kitty", "title": "terminal", "pid": 123})

    monkeypatch.setattr(desktop, "run_command", run)
    app = desktop.LinuxDesktop().current_app()
    assert app.bundle_id == "kitty"
    assert app.window_title == "terminal"
    assert calls == [("hyprctl", "activewindow", "-j")]


async def test_hyprland_paste_restores_captured_window(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "test")
    commands = []
    system = desktop.LinuxDesktop()
    monkeypatch.setattr(system, "active_window", lambda: {"address": "0x123"})
    monkeypatch.setattr(system, "copy_text", lambda text: commands.append(("clipboard", text)))
    monkeypatch.setattr(desktop, "run_command", lambda *args: commands.append(args))
    inserter = desktop.LinuxTextInserter(system, LinuxConfig(paste_shortcut="ctrl+shift+v"))
    inserter.capture_target()
    await inserter.insert("你好")
    assert commands == [
        ("hyprctl", "dispatch", "focuswindow", "address:0x123"),
        ("clipboard", "你好"),
        ("hyprctl", "dispatch", "sendshortcut", "CTRL SHIFT, V, activewindow"),
    ]


async def test_wayland_without_hyprland_uses_wtype_not_x11(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    system = desktop.LinuxDesktop()
    assert system.current_app().bundle_id is None
    calls = []
    monkeypatch.setattr(system, "copy_text", lambda text: None)
    monkeypatch.setattr(desktop, "run_command", lambda *args: calls.append(args))
    await desktop.LinuxTextInserter(system, LinuxConfig()).insert("hello")
    assert calls == [("wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl")]


async def test_x11_insertion(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    system = desktop.LinuxDesktop()
    calls = []
    monkeypatch.setattr(system, "copy_text", lambda text: None)
    monkeypatch.setattr(desktop, "run_command", lambda *args: calls.append(args))
    inserter = desktop.LinuxTextInserter(system, LinuxConfig())
    inserter.target = {"address": "42"}
    await inserter.insert("hello")
    assert calls == [
        ("xdotool", "windowactivate", "--sync", "42"),
        ("xdotool", "key", "--clearmodifiers", "ctrl+v"),
    ]


def test_waybar_format_escapes_markup_and_reports_offline():
    assert waybar_status(None)["alt"] == "offline"
    result = waybar_status({"ok": True, "state": "recording", "detail": '<mic> & "test"'})
    assert result["alt"] == result["class"] == "recording"
    assert "<mic>" not in result["tooltip"]
    assert "&lt;mic&gt;" in result["tooltip"]
    assert waybar_status({"ok": False, "state": "idle"})["class"] == "error"


def test_waybar_cli_outputs_json_when_daemon_is_offline(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["asr-evo-control", "status", "--waybar"])
    monkeypatch.setattr(control.AppConfig, "load", lambda _: AppConfig())

    def offline(*args, **kwargs):
        raise ConnectionRefusedError()

    monkeypatch.setattr(control, "send_control_command", offline)
    control.main()
    assert json.loads(capsys.readouterr().out)["class"] == "offline"


def test_waybar_tray_does_not_import_pystray(monkeypatch):
    monkeypatch.setitem(sys.modules, "pystray", None)
    actions = TrayMenuActions(
        **{field.name: lambda *args: None for field in fields(TrayMenuActions)}
    )
    tray = LinuxStatusTray(
        mode="waybar",
        control_label="127.0.0.1:8765",
        status_config=StatusConfig(),
        styles=[],
        selected_style_id="",
        actions=actions,
    )
    tray.set_state("recording")
    assert "正在录音" in tray.tooltip
    tray.stop()
    tray.run()
    assert tray.icon is None


def test_local_configuration_roundtrip(tmp_path):
    config = AppConfig.model_validate(
        {
            "linux": {"tray": "waybar", "paste_shortcut": "ctrl+shift+v"},
            "asr": {"backend": "qwen_local", "model": "/models/asr", "device": "cpu"},
            "llm": {
                "default_profile": "local",
                "profiles": {
                    "local": {
                        "backend": "ollama",
                        "model": "qwen3:4b",
                        "base_url": "http://localhost:11434",
                        "keep_alive_seconds": 30,
                    }
                },
            },
        }
    )
    path = tmp_path / "config.toml"
    config.save(path)
    assert AppConfig.load(path).model_dump() == config.model_dump()


def test_shipped_local_example_resolves_all_prompt_profiles():
    from pathlib import Path

    from asr_evo.core.controller import prepare_runtime_config

    project = Path(__file__).resolve().parents[1]
    config = AppConfig.load(project / "examples/linux/config.local.toml")
    config.style.prompts_dir = str(project / "prompts")
    applied = prepare_runtime_config(config, config.style.mode)
    assert applied.styles.all()


def test_menu_control_coalesces_requests_while_popup_is_open(monkeypatch):
    import threading
    from types import SimpleNamespace

    from asr_evo.platforms.linux import runtime

    instance = object.__new__(runtime.LinuxDictationRuntime)
    instance._lock = threading.RLock()
    instance._menu_future = None
    instance.loop = object()
    instance.tray = SimpleNamespace(popup_menu=lambda: "snapshot")
    instance.controller = SimpleNamespace(
        state=SimpleNamespace(state=SimpleNamespace(value="idle"))
    )
    calls = []

    def schedule(coroutine, loop):
        coroutine.close()
        calls.append(loop)
        return SimpleNamespace(done=lambda: False)

    monkeypatch.setattr(runtime.asyncio, "run_coroutine_threadsafe", schedule)
    assert instance._handle_control_command("menu").ok
    assert instance._handle_control_command("menu").ok
    assert calls == [instance.loop]


def test_command_error_preserves_stdout_diagnostics(monkeypatch):
    import subprocess

    import pytest

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(7, args[0], output="Lua syntax error", stderr="")

    monkeypatch.setattr(desktop.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="exit 7.*Lua syntax error"):
        desktop.run_command("hyprctl", "dispatch", "focuswindow", "address:0x123")


async def test_hyprland_lua_syntax_rejection_switches_focus_and_paste(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "test")
    system = desktop.LinuxDesktop()
    calls = []

    def run(*args):
        calls.append(args)
        if args[2] == "focuswindow":
            raise RuntimeError("dispatch in lua is a shorthand for hl.dispatch(...)")
        return "ok"

    monkeypatch.setattr(desktop, "run_command", run)
    monkeypatch.setattr(system, "copy_text", lambda text: calls.append(("clipboard", text)))
    inserter = desktop.LinuxTextInserter(system, LinuxConfig())
    inserter.target = {"address": "0x123"}
    await inserter.insert("中文")
    assert calls == [
        ("hyprctl", "dispatch", "focuswindow", "address:0x123"),
        ("hyprctl", "dispatch", 'hl.dsp.focus({window = "address:0x123"})'),
        ("clipboard", "中文"),
        (
            "hyprctl",
            "dispatch",
            'hl.dsp.send_shortcut({mods = "CTRL", key = "V", window = "activewindow"})',
        ),
    ]


def test_hyprland_does_not_retry_other_dispatch_failures(monkeypatch):
    import pytest

    system = desktop.LinuxDesktop()
    calls = []

    def run(*args):
        calls.append(args)
        raise RuntimeError("window not found")

    monkeypatch.setattr(desktop, "run_command", run)
    with pytest.raises(RuntimeError, match="window not found"):
        system.dispatch("sendshortcut", "CTRL, V, activewindow", "unused")
    assert len(calls) == 1
