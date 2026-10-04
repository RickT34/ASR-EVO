from __future__ import annotations

import queue
import threading
from collections import deque
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

from asr_evo.audio.enhancement import AudioProcessingOptions, SpeechEnhancer
from asr_evo.audio.recorder import _stream_device_arg, _stream_sample_rate


@dataclass(frozen=True)
class MonitorSettings:
    input_device: str
    output_device: str
    processing: AudioProcessingOptions
    volume: float = 0.2


class PlaybackBuffer:
    """Bound latency when an output device lags; an underrun produces silence."""

    def __init__(self, max_frames: int) -> None:
        self.max_frames = max_frames
        self.frames = 0
        self._parts = deque()
        self._lock = threading.Lock()

    def put(self, samples: np.ndarray) -> None:
        with self._lock:
            self._parts.append(np.asarray(samples, dtype=np.float32).reshape(-1))
            self.frames += len(samples)
            self._discard(max(0, self.frames - self.max_frames))

    def _discard(self, count: int) -> None:
        while count:
            part = self._parts.popleft()
            consumed = min(count, len(part))
            if consumed < len(part):
                self._parts.appendleft(part[consumed:])
            count -= consumed
            self.frames -= consumed

    def read(self, count: int) -> np.ndarray:
        output = np.zeros(count, dtype=np.float32)
        position = 0
        with self._lock:
            while position < count and self._parts:
                part = self._parts.popleft()
                consumed = min(count - position, len(part))
                output[position:position + consumed] = part[:consumed]
                if consumed < len(part):
                    self._parts.appendleft(part[consumed:])
                position += consumed
                self.frames -= consumed
        return output


class MicrophoneMonitor:
    def __init__(self) -> None:
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._settings = None
        self._status = {"running": False, "input_db": -96.0, "output_db": -96.0, "error": ""}

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._status)

    def _publish(self, **values) -> None:
        with self._lock:
            self._status.update(values)

    def configure(self, settings: MonitorSettings) -> None:
        if not 0 <= settings.volume <= 1:
            raise ValueError("监听音量必须在 0% 到 100% 之间")
        with self._lock:
            previous = self._settings
        if self._thread is not None and self._thread.is_alive():
            if previous and (previous.input_device, previous.output_device) == (settings.input_device, settings.output_device):
                with self._lock:
                    self._settings = settings
                return
        self.stop()
        with self._lock:
            self._settings = settings
        self._stop.clear()
        self._publish(running=True, error="", input_db=-96.0, output_db=-96.0)
        self._thread = threading.Thread(target=self._run, name="microphone-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                raise RuntimeError("音频设备尚未停止，请稍后重试")
            self._thread = None
        self._publish(running=False, input_db=-96.0, output_db=-96.0)

    def _run(self) -> None:
        processor = None
        try:
            with self._lock:
                settings = self._settings
            source_rate = _stream_sample_rate(settings.input_device, channels=1, preferred_sample_rate=48000)
            output_device = _stream_device_arg(settings.output_device)
            output_info = sd.query_devices(output_device, "output")
            output_rate = int(output_info["default_samplerate"])
            output_channels = min(2, int(output_info["max_output_channels"]))
            if output_channels < 1:
                raise RuntimeError("所选设备没有音频输出通道")
            processor = SpeechEnhancer(source_rate, settings.processing)
            resampler = self._resampler(processor.sample_rate, output_rate)
            playback = PlaybackBuffer(max_frames=output_rate // 4)
            captured = queue.Queue(maxsize=12)

            def capture(indata, frames, timing, status):
                try:
                    captured.put_nowait(indata.copy())
                except queue.Full:
                    try:
                        captured.get_nowait()
                    except queue.Empty:
                        pass

            def play(outdata, frames, timing, status):
                with self._lock:
                    volume = self._settings.volume
                outdata[:] = playback.read(frames)[:, None] * volume

            with sd.OutputStream(device=output_device, samplerate=output_rate, channels=output_channels,
                                 dtype="float32", blocksize=0, latency="low", callback=play):
                with sd.InputStream(device=_stream_device_arg(settings.input_device), samplerate=source_rate,
                                    channels=1, dtype="float32", blocksize=max(1, source_rate // 50),
                                    latency="low", callback=capture):
                    self._publish(input_rate=source_rate, output_rate=output_rate)
                    while not self._stop.is_set():
                        try:
                            frames = captured.get(timeout=0.05)
                        except queue.Empty:
                            continue
                        with self._lock:
                            latest = self._settings
                        if latest.processing != settings.processing:
                            if latest.processing.noise_suppression != settings.processing.noise_suppression:
                                replacement = SpeechEnhancer(source_rate, latest.processing)
                                processor.close()
                                processor = replacement
                                resampler = self._resampler(processor.sample_rate, output_rate)
                                # Don't replay queued audio from the old filter mode.
                                playback = PlaybackBuffer(max_frames=output_rate // 4)
                            else:
                                processor.update_levels(latest.processing.input_gain_db, latest.processing.denoise_mix)
                            settings = latest
                        processed = processor.process(frames)
                        self._publish(input_db=_level(frames), output_db=_level(processed))
                        if len(processed):
                            mono = processed[:, 0]
                            if resampler is not None:
                                mono = resampler.resample_chunk(mono)
                            if len(mono):
                                playback.put(mono)
        except Exception as exc:
            self._publish(error=str(exc))
        finally:
            if processor is not None:
                processor.close()
            self._publish(running=False)

    @staticmethod
    def _resampler(source_rate: int, output_rate: int):
        if source_rate == output_rate:
            return None
        import soxr
        return soxr.ResampleStream(source_rate, output_rate, 1, dtype="float32")


def _level(samples: np.ndarray) -> float:
    if not len(samples):
        return -96.0
    return max(-96.0, float(20 * np.log10(max(float(np.sqrt(np.mean(samples**2))), 1e-12))))
