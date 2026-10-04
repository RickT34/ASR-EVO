from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import queue
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sounddevice as sd
import soundfile as sf

from asr_evo.core.ports import AudioClip
from asr_evo.audio.pcm import PCM16StreamEncoder
from asr_evo.audio.enhancement import AudioProcessingOptions, SpeechEnhancer


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InputDevice:
    id: str
    name: str
    channels: int
    is_default: bool = False

    @property
    def label(self) -> str:
        suffix = "（系统默认）" if self.is_default else ""
        return f"{self.name}{suffix}"


class SoundDeviceRecorder:
    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        channels: int = 1,
        input_device: str | int | None = None,
        processing: AudioProcessingOptions | None = None,
    ) -> None:
        self.processing = processing or AudioProcessingOptions()
        self.sample_rate = sample_rate
        self.channels = channels
        self.input_device = _normalize_device_id(input_device)
        self._frames: list = []
        self._stop_event: threading.Event | None = None
        self._lock = threading.Lock()
        self._stop_requested = False

    def set_input_device(self, device_id: str | int | None) -> None:
        normalized = _normalize_device_id(device_id)
        if normalized == self.input_device:
            return
        self.input_device = normalized


    def set_processing(self, options: AudioProcessingOptions) -> None:
        # Applied at the start of the next recording; never reset a live filter.
        self.processing = options

    def input_devices(self) -> list[InputDevice]:
        return list_input_devices()

    def current_input_label(self) -> str:
        return input_device_label(self.input_device, self.input_devices())

    async def record_until_stopped(self, on_chunk: Callable[[bytes], None] | None = None) -> AudioClip:
        fd, raw_path = tempfile.mkstemp(prefix="asr-evo-", suffix=".wav")
        os.close(fd)
        path = Path(raw_path)
        recording = asyncio.create_task(asyncio.to_thread(self._record_until_stopped_sync, path, on_chunk))
        try:
            return await asyncio.shield(recording)
        except BaseException:
            if not recording.done():
                self.stop()
            await asyncio.gather(recording, return_exceptions=True)
            with contextlib.suppress(OSError):
                path.unlink()
            raise

    def _record_until_stopped_sync(
        self, path: Path, on_chunk: Callable[[bytes], None] | None = None,
    ) -> AudioClip:
        stop_event = threading.Event()
        with self._lock:
            self._frames = []
            self._stop_event = stop_event
            if self._stop_requested:
                self._stop_requested = False
                stop_event.set()
        options = self.processing
        device = self.input_device
        pending: queue.Queue = queue.Queue(maxsize=200)
        callback_error: list[Exception] = []
        input_overflows = 0
        enhancer = None
        sample_rate = self.sample_rate

        def callback(indata, frames, time, status) -> None:
            nonlocal input_overflows
            # An overflow reports already-lost samples, not an unusable current
            # buffer. Keep recording; never log or perform DSP on this callback.
            if status.input_overflow:
                input_overflows += 1
            try:
                pending.put_nowait(indata.copy())
            except queue.Full:
                callback_error.append(RuntimeError("音频处理积压，录音已停止，请降低处理负载"))
                stop_event.set()

        try:
            sample_rate = _stream_sample_rate(
                device, channels=self.channels,
                preferred_sample_rate=48000 if options.noise_suppression else self.sample_rate,
            )
            enhancer = SpeechEnhancer(sample_rate, options)
            output_rate = enhancer.sample_rate
            encoder = PCM16StreamEncoder(output_rate) if on_chunk is not None else None

            def emit(processed) -> None:
                if not len(processed):
                    return
                self._frames.append(processed)
                if encoder is not None:
                    chunk = encoder.encode(processed)
                    if chunk:
                        on_chunk(chunk)

            if not stop_event.is_set():
                with sd.InputStream(
                    device=_stream_device_arg(device), samplerate=sample_rate,
                    channels=self.channels, dtype="float32", latency="high",
                    blocksize=max(1, sample_rate // 10), callback=callback,
                ):
                    while not stop_event.is_set():
                        try:
                            frames = pending.get(timeout=0.05)
                        except queue.Empty:
                            continue
                        emit(enhancer.process(frames))
            # The microphone is closed: drain queued audio before flushing filters.
            while not pending.empty():
                emit(enhancer.process(pending.get_nowait()))
            emit(enhancer.finish())
            if encoder is not None:
                tail = encoder.finish()
                if tail:
                    on_chunk(tail)
            if callback_error:
                raise callback_error[0]

            import numpy as np

            audio = np.concatenate(self._frames, axis=0) if self._frames else np.empty((0, 1))
            sf.write(path, audio, output_rate)
            return AudioClip(path=path, sample_rate=output_rate, duration_seconds=len(audio) / output_rate)
        finally:
            if input_overflows:
                logger.warning(
                    "录音检测到 %d 次输入溢出，已继续接收有效音频；丢失部分无法恢复。设备=%s，采样率=%s",
                    input_overflows, device or "default", sample_rate,
                )
            if enhancer is not None:
                enhancer.close()
            with self._lock:
                self._stop_requested = False
                self._stop_event = None

    def stop(self) -> None:
        with self._lock:
            self._stop_requested = True
            if self._stop_event is not None:
                self._stop_event.set()


def list_input_devices() -> list[InputDevice]:
    devices = sd.query_devices()
    default_input = _default_input_device_index()
    result = [
        InputDevice(id="", name="系统默认输入", channels=0, is_default=True),
    ]
    for index, device in enumerate(devices):
        max_input_channels = int(device.get("max_input_channels") or 0)
        if max_input_channels <= 0:
            continue
        result.append(
            InputDevice(
                id=str(index),
                name=str(device.get("name") or f"输入设备 {index}"),
                channels=max_input_channels,
                is_default=index == default_input,
            )
        )
    return result


def input_device_label(device_id: str | int | None, devices: list[InputDevice]) -> str:
    normalized = _normalize_device_id(device_id)
    for device in devices:
        if device.id == normalized:
            return device.label
    if normalized:
        return f"输入设备 {normalized}（不可用）"
    return "系统默认输入"


def _normalize_device_id(device_id: str | int | None) -> str:
    if device_id is None:
        return ""
    normalized = str(device_id).strip()
    return "" if normalized.lower() in {"", "default", "none"} else normalized


def _stream_device_arg(device_id: str) -> int | str | None:
    if not device_id:
        return None
    try:
        return int(device_id)
    except ValueError:
        return device_id


def _stream_sample_rate(
    device_id: str,
    *,
    channels: int,
    preferred_sample_rate: int,
) -> int:
    device_arg = _stream_device_arg(device_id)
    if _input_settings_supported(device_arg, channels=channels, sample_rate=preferred_sample_rate):
        return preferred_sample_rate

    default_rate = _default_input_sample_rate(device_arg)
    if default_rate and _input_settings_supported(device_arg, channels=channels, sample_rate=default_rate):
        return default_rate

    return preferred_sample_rate


def _input_settings_supported(
    device: int | str | None,
    *,
    channels: int,
    sample_rate: int,
) -> bool:
    try:
        sd.check_input_settings(device=device, channels=channels, samplerate=sample_rate)
    except Exception:
        return False
    return True


def _default_input_sample_rate(device: int | str | None) -> int | None:
    try:
        info = sd.query_devices(device, "input")
    except Exception:
        return None
    try:
        return int(float(info.get("default_samplerate") or 0))
    except (AttributeError, TypeError, ValueError):
        return None


def _default_input_device_index() -> int | None:
    default_device: Any = sd.default.device
    if isinstance(default_device, (list, tuple)) and default_device:
        index = default_device[0]
    else:
        index = default_device
    try:
        return int(index)
    except (TypeError, ValueError):
        return None
