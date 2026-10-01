from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from asr_evo.config import ASRConfig
from asr_evo.core.ports import AudioClip, Transcript


class QwenLocalASRProvider:
    """One worker per request: process exit also releases the CUDA context."""

    def __init__(self, config: ASRConfig) -> None:
        self.config = config.model_copy(deep=True)
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._closed = False

    async def transcribe(self, audio: AudioClip) -> Transcript:
        path = audio.path.resolve(strict=True)
        async with self._lock:
            if self._closed:
                raise RuntimeError("Local ASR provider is closed")
            worker = Path(__file__).with_name("qwen_worker.py")
            self._process = await asyncio.create_subprocess_exec(
                self.config.python_executable or sys.executable,
                str(worker),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            process = self._process
            request = {**self.config.model_dump(), "audio": str(path)}
            communication = asyncio.create_task(process.communicate(json.dumps(request).encode()))
            try:
                if self._closed:
                    raise RuntimeError("Local ASR provider is closed")
                stdout, stderr = await asyncio.wait_for(
                    asyncio.shield(communication),
                    timeout=self.config.timeout_seconds,
                )
                if process.returncode:
                    raise RuntimeError(
                        "Local Qwen ASR failed. Install the local-asr extra in its Python "
                        "environment and check the model/device.\n"
                        + stderr.decode(errors="replace")[-4000:]
                    )
                result = json.loads(stdout)
                return Transcript(text=result["text"].strip(), language=result.get("language"))
            except TimeoutError as exc:
                raise RuntimeError("Local Qwen ASR exceeded asr.timeout_seconds") from exc
            finally:
                # Keep draining both pipes even when timeout/cancellation interrupts us.
                # Otherwise a verbose worker can block Process.wait() on a full pipe.
                await self._terminate(process)
                await communication
                self._process = None

    async def aclose(self) -> None:
        self._closed = True
        if self._process is not None:
            await self._terminate(self._process)

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
