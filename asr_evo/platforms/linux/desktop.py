from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

from asr_evo.config import LinuxConfig
from asr_evo.core.ports import AppContext


def run_command(*args: str, input: str | None = None) -> str:
    try:
        return subprocess.run(
            args,
            input=input,
            text=True,
            capture_output=True,
            check=True,
            timeout=5,
        ).stdout.strip()
    except FileNotFoundError as exc:
        raise RuntimeError(f"Linux desktop requires {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = "\n".join(
            value.strip() for value in (exc.stderr, exc.stdout) if value and value.strip()
        )
        raise RuntimeError(
            f"{args[0]} {' '.join(args[1:])} failed (exit {exc.returncode}): "
            f"{detail or 'command returned no diagnostic output'}"
        ) from exc


class LinuxDesktop:
    def __init__(self) -> None:
        self.wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        self.hyprland = self.wayland and bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))
        self._lua_dispatch = False

    def dispatch(self, legacy_name: str, legacy_args: str, lua_expression: str) -> None:
        if not self._lua_dispatch:
            try:
                run_command("hyprctl", "dispatch", legacy_name, legacy_args)
                return
            except RuntimeError as exc:
                # Lua-mode Hyprland rejects legacy syntax before executing it.
                # Retry only this explicit syntax rejection, never an arbitrary
                # failed paste (which might already have reached the target).
                if "dispatch in lua is a shorthand" not in str(exc):
                    raise
                self._lua_dispatch = True
        run_command("hyprctl", "dispatch", lua_expression)

    def active_window(self) -> dict:
        if self.hyprland:
            return json.loads(run_command("hyprctl", "activewindow", "-j"))
        if not self.wayland:
            window = run_command("xdotool", "getactivewindow")
            return {
                "address": window,
                "class": run_command("xdotool", "getwindowclassname", window),
                "title": run_command("xdotool", "getwindowname", window),
                "pid": int(run_command("xdotool", "getwindowpid", window)),
            }
        # Wayland has no desktop-independent foreground-window query.
        return {}

    def current_app(self) -> AppContext:
        try:
            window = self.active_window()
            return AppContext(
                bundle_id=window.get("class"),
                app_name=window.get("class"),
                window_title=window.get("title"),
                process_id=window.get("pid"),
            )
        except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired):
            return AppContext()

    def copy_text(self, text: str) -> None:
        if self.wayland:
            # wl-copy forks a selection owner. Do not leave it holding captured pipes.
            subprocess.run(
                ["wl-copy", "--type", "text/plain;charset=utf-8"],
                input=text,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=5,
            )
        else:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=5,
            )

    def open_path(self, path: Path) -> None:
        subprocess.Popen(
            ["xdg-open", str(path.resolve())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def accessibility_trusted(self, *, prompt: bool = False) -> bool:
        required = (
            ["wl-copy", "hyprctl" if self.hyprland else "wtype"]
            if self.wayland
            else [
                "xclip",
                "xdotool",
            ]
        )
        self._missing = [name for name in required if not shutil.which(name)]
        return not self._missing

    def accessibility_error(self):
        from asr_evo.core.errors import PermissionDeniedError

        return PermissionDeniedError(
            "缺少 Linux 桌面工具：" + ", ".join(self._missing),
            suggestion="安装这些工具后重启；Wayland 全局快捷键请在合成器中配置。",
        )


class LinuxTextInserter:
    def __init__(self, desktop: LinuxDesktop, config: LinuxConfig) -> None:
        self.desktop = desktop
        self.config = config
        self.target: dict = {}

    def capture_target(self) -> None:
        self.target = self.desktop.active_window()

    async def insert(self, text: str) -> None:
        await asyncio.to_thread(self._insert, text)

    def _insert(self, text: str) -> None:
        address = self.target.get("address")
        if address and self.desktop.hyprland:
            selector = json.dumps(f"address:{address}")
            self.desktop.dispatch(
                "focuswindow",
                f"address:{address}",
                f"hl.dsp.focus({{window = {selector}}})",
            )
        elif address and not self.desktop.wayland:
            run_command("xdotool", "windowactivate", "--sync", address)
        self.desktop.copy_text(text)
        shifted = self.config.paste_shortcut == "ctrl+shift+v"
        if self.desktop.hyprland:
            modifiers = "CTRL SHIFT" if shifted else "CTRL"
            self.desktop.dispatch(
                "sendshortcut",
                f"{modifiers}, V, activewindow",
                f'hl.dsp.send_shortcut({{mods = "{modifiers}", key = "V", '
                'window = "activewindow"})',
            )
        elif self.desktop.wayland:
            args = ["wtype", "-M", "ctrl"]
            if shifted:
                args += ["-M", "shift"]
            args += ["-k", "v"]
            if shifted:
                args += ["-m", "shift"]
            run_command(*args, "-m", "ctrl")
        else:
            run_command("xdotool", "key", "--clearmodifiers", self.config.paste_shortcut)
