from __future__ import annotations

import asyncio
import threading
import time

from asr_evo.core.control import (
    ControlResult,
    DictationControlServer,
    send_control_command,
)


async def test_control_server_dispatches_commands(tmp_path) -> None:
    seen = []

    def handle(command: str) -> ControlResult:
        seen.append(command)
        return ControlResult(ok=True, state="recording")

    server = DictationControlServer(port=0, handler=handle)
    await server.start_async()
    try:
        response = await asyncio.to_thread(
            send_control_command,
            "start",
            port=server.port,
        )
    finally:
        await server.stop_async()

    assert server.address != "127.0.0.1:0"
    assert seen == ["start"]
    assert response == {"ok": True, "state": "recording", "detail": "", "error": ""}


async def test_control_server_keeps_accepting_clients_while_handler_waits() -> None:
    started = threading.Event()
    release = threading.Event()

    def handle(command: str) -> ControlResult:
        if command == "start":
            started.set()
            release.wait(timeout=1)
            return ControlResult(ok=True, state="recording")
        return ControlResult(ok=True, state="idle")

    server = DictationControlServer(port=0, handler=handle)
    await server.start_async()
    try:
        slow_request = asyncio.create_task(
            asyncio.to_thread(send_control_command, "start", port=server.port, timeout=2)
        )
        assert await asyncio.to_thread(started.wait, 1)

        before = time.monotonic()
        response = await asyncio.to_thread(
            send_control_command,
            "status",
            port=server.port,
            timeout=1,
        )
        elapsed = time.monotonic() - before
        release.set()
        await slow_request
    finally:
        release.set()
        await server.stop_async()

    assert elapsed < 0.5
    assert response == {"ok": True, "state": "idle", "detail": "", "error": ""}
