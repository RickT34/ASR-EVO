"""Serialize a tray-menu snapshot and supervise its isolated popup process."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from functools import partial


def snapshot_menu(menu) -> tuple[list[dict], dict]:
    """Evaluate dynamic tray properties once; retain actions only in the parent."""
    callbacks = {}

    def entries(items):
        result = []
        for item in items:
            if item is menu.SEPARATOR:
                result.append({"separator": True})
                continue
            entry = {
                "title": item.text,
                "enabled": item.enabled,
                "checked": item.checked,
                "radio": item.radio,
            }
            if item.submenu is not None:
                entry["children"] = entries(item.submenu)
            elif item.enabled:
                key = str(len(callbacks))
                callbacks[key] = partial(item, None)
                entry["id"] = key
            result.append(entry)
        return result

    return entries(menu), callbacks


async def show_popup_menu(menu) -> None:
    entries, callbacks = snapshot_menu(menu)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "asr_evo.platforms.linux.popup_menu",
        env={**os.environ, **({"GDK_BACKEND": "wayland"} if os.getenv("WAYLAND_DISPLAY") else {})},
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    communication = asyncio.create_task(process.communicate(json.dumps(entries).encode()))
    try:
        stdout, stderr = await asyncio.shield(communication)
        if process.returncode:
            raise RuntimeError(
                "无法显示右键菜单；请检查 GTK 3、PyGObject 和 gtk-layer-shell。\n"
                + stderr.decode(errors="replace")[-2000:]
            )
        selected = stdout.decode().strip()
        if selected:
            if selected not in callbacks:
                raise RuntimeError("Invalid popup menu selection")
            # Config reload and Quit callbacks can synchronously wait on the event loop.
            await asyncio.to_thread(callbacks[selected])
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await communication
        await process.wait()
