from __future__ import annotations

import asyncio

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
