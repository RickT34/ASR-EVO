from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from asr_evo.ui.popup_menu import show_popup_menu, snapshot_menu


class Menu(list):
    SEPARATOR = object()


@dataclass
class Item:
    text: str
    callback: object = None
    enabled: bool = True
    checked: bool | None = None
    radio: bool = False
    submenu: Menu | None = None

    def __call__(self, icon):
        self.callback()


def test_snapshot_preserves_nested_items_and_dispatches_only_enabled_actions():
    selected = []
    menu = Menu(
        [
            Item("readonly", enabled=False),
            Menu.SEPARATOR,
            Item(
                "styles",
                submenu=Menu(
                    [
                        Item("中文", lambda: selected.append("style"), checked=True, radio=True),
                    ]
                ),
            ),
        ]
    )
    entries, callbacks = snapshot_menu(menu)
    assert "id" not in entries[0]
    assert entries[1] == {"separator": True}
    child = entries[2]["children"][0]
    assert child["checked"] is True and child["radio"] is True
    callbacks[child["id"]]()
    assert selected == ["style"]


@pytest.fixture
def popup_worker(tmp_path, monkeypatch):
    script = tmp_path / "popup.py"
    processes = []
    original = asyncio.create_subprocess_exec

    async def create(executable, *args, **kwargs):
        process = await original(executable, str(script), **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    return script, processes


async def test_popup_dispatches_selection_after_process_exit(popup_worker):
    script, processes = popup_worker
    script.write_text('import json, sys\nitems=json.load(sys.stdin)\nprint(items[0]["id"])')
    selected = []
    await show_popup_menu(Menu([Item("action", lambda: selected.append(processes[0].returncode))]))
    assert selected == [0]


async def test_dismissed_popup_does_not_invoke_callback(popup_worker):
    script, processes = popup_worker
    script.write_text("import json, sys\njson.load(sys.stdin)")
    selected = []
    await show_popup_menu(Menu([Item("action", lambda: selected.append(True))]))
    assert not selected
    assert processes[0].returncode == 0


async def test_popup_reports_display_error(popup_worker):
    script, processes = popup_worker
    script.write_text('import sys\nsys.stderr.write("no DISPLAY")\nsys.exit(1)')
    with pytest.raises(RuntimeError, match="DISPLAY"):
        await show_popup_menu(Menu([]))
    assert processes[0].returncode == 1


async def test_shutdown_kills_popup_process(popup_worker):
    script, processes = popup_worker
    script.write_text("import time\ntime.sleep(30)")
    task = asyncio.create_task(show_popup_menu(Menu([])))
    async with asyncio.timeout(3):
        while not processes:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert processes[0].returncode is not None


@pytest.mark.parametrize(
    "pointer,size,bounds,expected",
    [
        ((1200, 70), (380, 200), (1920, 1080), (1200, 70)),
        ((1910, 1070), (380, 200), (1920, 1080), (1540, 880)),
        ((300.4, 99.6), (380, 200), (1600, 1000), (300, 100)),
        ((-3, -5), (380, 200), (1920, 1080), (0, 0)),
        ((10, 10), (380, 200), (320, 180), (0, 0)),
    ],
)
def test_native_popup_uses_logical_coordinates_and_stays_inside_output(
    pointer,
    size,
    bounds,
    expected,
):
    from asr_evo.platforms.linux.popup_menu import menu_position

    assert menu_position(*pointer, *size, bounds) == expected


async def test_wayland_child_uses_native_backend_even_if_parent_prefers_x11(monkeypatch, tmp_path):
    script = tmp_path / "popup.py"
    script.write_text("import sys,json\njson.load(sys.stdin)")
    original = asyncio.create_subprocess_exec
    captured = {}

    async def create(executable, *args, **kwargs):
        captured.update(args=args, env=kwargs["env"])
        return await original(executable, str(script), **kwargs)

    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("GDK_BACKEND", "x11")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    await show_popup_menu(Menu([]))
    assert captured["args"] == ("-m", "asr_evo.platforms.linux.popup_menu")
    assert captured["env"]["GDK_BACKEND"] == "wayland"
    # The parent environment is not mutated.
    import os

    assert os.environ["GDK_BACKEND"] == "x11"
