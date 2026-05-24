from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import sounddevice as sd
import soundfile as sf

from asr_evo.core.ports import AudioClip


class SoundDeviceRecorder:
    def __init__(self, *, sample_rate: int = 16000, channels: int = 1) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self._frames: list = []
        self._stop_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def record_until_stopped(self) -> AudioClip:
        self._frames = []
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        fd, raw_path = tempfile.mkstemp(prefix="asr-evo-", suffix=".wav")
        os.close(fd)
        path = Path(raw_path)

        def callback(indata, frames, time, status) -> None:
            if status:
                return
            self._frames.append(indata.copy())

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            callback=callback,
        ):
            await self._stop_event.wait()

        if not self._frames:
            sf.write(path, [], self.sample_rate)
            return AudioClip(path=path, sample_rate=self.sample_rate, duration_seconds=0)

        import numpy as np

        audio = np.concatenate(self._frames, axis=0)
        sf.write(path, audio, self.sample_rate)
        return AudioClip(
            path=path,
            sample_rate=self.sample_rate,
            duration_seconds=len(audio) / self.sample_rate,
        )

    def stop(self) -> None:
        if self._stop_event is not None:
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._stop_event.set)
            else:
                self._stop_event.set()
