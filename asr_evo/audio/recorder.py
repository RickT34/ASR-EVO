from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sounddevice as sd
import soundfile as sf

from asr_evo.core.ports import AudioClip


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
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.input_device = _normalize_device_id(input_device)
        self._frames: list = []
        self._stop_event: threading.Event | None = None
        self._restart_event: threading.Event | None = None
        self._lock = threading.Lock()
        self._stop_requested = False

    def set_input_device(self, device_id: str | int | None) -> None:
        self.input_device = _normalize_device_id(device_id)
        if self._restart_event is not None:
            self._restart_event.set()

    def input_devices(self) -> list[InputDevice]:
        return list_input_devices()

    def current_input_label(self) -> str:
        return input_device_label(self.input_device, self.input_devices())

    async def record_until_stopped(self) -> AudioClip:
        fd, raw_path = tempfile.mkstemp(prefix="asr-evo-", suffix=".wav")
        os.close(fd)
        path = Path(raw_path)
        try:
            return await asyncio.to_thread(self._record_until_stopped_sync, path)
        except Exception:
            with contextlib.suppress(OSError):
                path.unlink()
            raise

    def _record_until_stopped_sync(self, path: Path) -> AudioClip:
        self._frames = []
        stop_event = threading.Event()
        with self._lock:
            self._stop_event = stop_event
            if self._stop_requested:
                self._stop_requested = False
                stop_event.set()
        sample_rate = _stream_sample_rate(
            self.input_device,
            channels=self.channels,
            preferred_sample_rate=self.sample_rate,
        )

        def callback(indata, frames, time, status) -> None:
            if status:
                return
            self._frames.append(indata.copy())

        try:
            while not stop_event.is_set():
                restart_event = threading.Event()
                with self._lock:
                    self._restart_event = restart_event
                sample_rate = _stream_sample_rate(
                    self.input_device,
                    channels=self.channels,
                    preferred_sample_rate=self.sample_rate,
                )
                with sd.InputStream(
                    device=_stream_device_arg(self.input_device),
                    samplerate=sample_rate,
                    channels=self.channels,
                    callback=callback,
                ):
                    while not stop_event.is_set():
                        if restart_event.wait(timeout=0.05):
                            break
        finally:
            with self._lock:
                self._stop_requested = False
                self._stop_event = None
                self._restart_event = None

        if not self._frames:
            sf.write(path, [], sample_rate)
            return AudioClip(path=path, sample_rate=sample_rate, duration_seconds=0)

        import numpy as np

        audio = np.concatenate(self._frames, axis=0)
        sf.write(path, audio, sample_rate)
        return AudioClip(
            path=path,
            sample_rate=sample_rate,
            duration_seconds=len(audio) / sample_rate,
        )

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
