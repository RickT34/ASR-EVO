from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
import sys
from collections.abc import AsyncIterator
from pathlib import Path

from asr_evo.config import RealtimeASRConfig
from asr_evo.core.ports import Transcript


class QwenStreamingASRProvider:
    def __init__(self, config: RealtimeASRConfig) -> None:
        self.config = config.model_copy(deep=True)

    async def stream(self, chunks: AsyncIterator[bytes]) -> AsyncIterator[Transcript]:
        if os.name != "posix":
            raise RuntimeError("本地 Qwen 流式模式需要支持 vLLM 的 Linux 环境")
        process = await asyncio.create_subprocess_exec(
            self.config.python_executable or sys.executable,
            str(Path(__file__).with_name("qwen_stream_worker.py")),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        errors = bytearray()

        async def drain_errors():
            while data := await process.stderr.read(4096):
                errors.extend(data)
                del errors[:-4000]

        async def send(message):
            process.stdin.write((json.dumps(message) + "\n").encode())
            await process.stdin.drain()

        async def feed():
            try:
                async for chunk in chunks:
                    await send({"type": "audio", "audio": base64.b64encode(chunk).decode("ascii")})
                await send({"type": "finish"})
            finally:
                process.stdin.close()

        draining = asyncio.create_task(drain_errors())
        feeding = None
        try:
            await send(self.config.model_dump())
            while True:
                line = await asyncio.wait_for(process.stdout.readline(), self.config.timeout_seconds)
                if not line:
                    await process.wait()
                    await draining
                    if feeding is not None and feeding.done():
                        feeding.result()
                    raise RuntimeError("本地 Qwen 流式识别失败：" + errors.decode(errors="replace"))
                message = json.loads(line)
                if message["type"] == "ready":
                    feeding = asyncio.create_task(feed())
                elif message["type"] == "transcript":
                    yield Transcript(message["text"], message.get("language"))
                elif message["type"] == "done":
                    if feeding is not None:
                        await feeding
                    return
        except TimeoutError as exc:
            raise RuntimeError("本地 Qwen 流式识别超时；请检查 vLLM 环境、模型与显存") from exc
        finally:
            if feeding is not None:
                feeding.cancel()
                await asyncio.gather(feeding, return_exceptions=True)
            # Also release vLLM engine children and their CUDA contexts.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
            await draining
