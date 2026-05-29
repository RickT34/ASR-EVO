from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


CONTROL_COMMANDS = frozenset({"start", "stop", "toggle", "status"})
DEFAULT_CONTROL_HOST = "127.0.0.1"


@dataclass(frozen=True)
class ControlResult:
    ok: bool
    state: str
    detail: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, bool | str]:
        return {
            "ok": self.ok,
            "state": self.state,
            "detail": self.detail,
            "error": self.error,
        }


ControlHandler = Callable[[str], ControlResult]


class DictationControlServer:
    def __init__(
        self,
        *,
        port: int,
        handler: ControlHandler,
    ) -> None:
        self.host = DEFAULT_CONTROL_HOST
        self.port = port
        self.handler = handler
        self._server: asyncio.AbstractServer | None = None

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        future = asyncio.run_coroutine_threadsafe(self.start_async(), loop)
        future.result(timeout=2)

    def stop(self, loop: asyncio.AbstractEventLoop) -> None:
        future = asyncio.run_coroutine_threadsafe(self.stop_async(), loop)
        future.result(timeout=2)

    async def start_async(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self.host,
            port=self.port,
        )
        sockets = self._server.sockets or []
        if sockets:
            self.port = sockets[0].getsockname()[1]

    async def stop_async(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw = await reader.readline()
            request = json.loads(raw.decode("utf-8"))
            command = str(request.get("command", ""))
            result = self.handler(command)
            payload = result.to_dict()
        except Exception as exc:
            payload = ControlResult(
                ok=False,
                state="unknown",
                error=str(exc),
            ).to_dict()
        writer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        await writer.drain()
        writer.close()
        await writer.wait_closed()


def send_control_command(
    command: str,
    *,
    port: int,
    timeout: float = 2,
) -> dict[str, Any]:
    if command not in CONTROL_COMMANDS:
        raise ValueError(f"unsupported control command: {command}")
    payload = json.dumps({"command": command}, ensure_ascii=False).encode("utf-8") + b"\n"
    with socket.create_connection((DEFAULT_CONTROL_HOST, port), timeout=timeout) as client:
        client.sendall(payload)
        data = _recv_line(client)
    return json.loads(data.decode("utf-8"))


def _recv_line(client: socket.socket) -> bytes:
    chunks = []
    while True:
        chunk = client.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    return b"".join(chunks).splitlines()[0]
