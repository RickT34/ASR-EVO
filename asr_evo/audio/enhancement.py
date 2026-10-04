from __future__ import annotations

import ctypes
import ctypes.util
from dataclasses import dataclass, replace
from collections import deque

import numpy as np


@dataclass(frozen=True)
class AudioProcessingOptions:
    noise_suppression: bool = False
    input_gain_db: float = 0.0
    denoise_mix: float = 0.85


class SpeechEnhancer:
    """Bounded streaming RNNoise processing; one state per recording, mono output."""

    def __init__(self, sample_rate: int, options: AudioProcessingOptions) -> None:
        self.options = options
        self.sample_rate = 48000 if options.noise_suppression else sample_rate
        self._gain = 10 ** (options.input_gain_db / 20)
        self._limit_gain = 1.0
        self._resampler = None
        self._state = None
        self._pending = np.empty(0, dtype=np.float32)
        self._dry_frames = deque()
        self._received = 0
        self._emitted = 0
        self._finished = False
        if options.noise_suppression:
            self._lib = _rnnoise_library()
            self._size = self._lib.rnnoise_get_frame_size()
            if self._size != 480:
                raise RuntimeError("RNNoise 版本不兼容：需要 48 kHz / 480 采样点帧")
            if sample_rate != 48000:
                import soxr

                self._resampler = soxr.ResampleStream(sample_rate, 48000, 1, dtype="float32")
            self._state = self._lib.rnnoise_create(None)
            if not self._state:
                raise RuntimeError("无法初始化 RNNoise 降噪模型")

    def update_levels(self, input_gain_db: float, denoise_mix: float) -> None:
        if not -12 <= input_gain_db <= 36 or not 0 <= denoise_mix <= 1:
            raise ValueError("无效的输入增益或降噪比例")
        self.options = replace(self.options, input_gain_db=input_gain_db, denoise_mix=denoise_mix)
        self._gain = 10 ** (input_gain_db / 20)

    def process(self, frames: np.ndarray) -> np.ndarray:
        if self._finished:
            raise RuntimeError("音频处理会话已结束")
        mono = np.asarray(frames, dtype=np.float32)
        if mono.ndim == 2:
            mono = mono.mean(axis=1)
        if not np.isfinite(mono).all():
            raise ValueError("录音包含无效音频采样")
        if self._state is None:
            # Exact bypass when both gain and suppression are disabled.
            return self._amplify(mono)[:, None]
        if self._resampler is not None:
            mono = self._resampler.resample_chunk(mono)
        return self._consume(mono)[:, None]

    def _amplify(self, samples: np.ndarray) -> np.ndarray:
        if self._gain == 1 and self._limit_gain == 1:
            return samples
        output = samples * self._gain
        if not len(output):
            return output
        peak = float(np.max(np.abs(output)))
        required = min(1.0, 0.98 / max(peak, 1e-12))
        # Immediate peak protection, gradual release; no gain chasing quiet noise.
        release = 1 - np.exp(-len(output) / (self.sample_rate * 0.25))
        self._limit_gain = min(required, self._limit_gain + (1 - self._limit_gain) * release)
        return output * self._limit_gain

    def _consume(self, samples: np.ndarray) -> np.ndarray:
        self._received += len(samples)
        self._pending = np.concatenate((self._pending, samples))
        output = []
        while len(self._pending) >= self._size:
            frame = self._pending[:self._size]
            self._pending = self._pending[self._size:]
            processed = self._frame(frame)
            if processed is not None:
                output.append(processed)
        joined = np.concatenate(output) if output else np.empty(0, dtype=np.float32)
        self._emitted += len(joined)
        return joined

    def _frame(self, frame: np.ndarray) -> np.ndarray | None:
        dry = self._amplify(frame)
        source = np.ascontiguousarray(dry * 32768, dtype=np.float32)
        clean = np.empty_like(source)
        pointer = ctypes.POINTER(ctypes.c_float)
        self._lib.rnnoise_process_frame(
            self._state, clean.ctypes.data_as(pointer), source.ctypes.data_as(pointer),
        )
        # RNNoise 0.2 adds one analysis frame plus one lookahead frame (20 ms).
        # Align the dry mix and remove startup latency from the saved/streamed audio.
        self._dry_frames.append(dry.copy())
        if len(self._dry_frames) <= 2:
            return None
        previous = self._dry_frames.popleft()
        mixed = self.options.denoise_mix * (clean / 32768) + (1 - self.options.denoise_mix) * previous
        return np.clip(mixed, -0.98, 0.98)

    def finish(self) -> np.ndarray:
        if self._finished:
            return np.empty((0, 1), dtype=np.float32)
        self._finished = True
        if self._state is None:
            return np.empty((0, 1), dtype=np.float32)
        output = []
        if self._resampler is not None:
            output.append(self._consume(self._resampler.resample_chunk(np.empty(0, dtype=np.float32), last=True)))
        remaining = self._received - self._emitted
        tail = []
        if len(self._pending):
            padded = np.pad(self._pending, (0, self._size - len(self._pending)))
            frame = self._frame(padded)
            if frame is not None:
                tail.append(frame)
        if self._received:
            for _ in range(2):
                frame = self._frame(np.zeros(self._size, dtype=np.float32))
                if frame is not None:
                    tail.append(frame)
        if tail:
            output.append(np.concatenate(tail)[:remaining])
        return (np.concatenate(output) if output else np.empty(0, dtype=np.float32))[:, None]

    def close(self) -> None:
        if self._state is not None:
            self._lib.rnnoise_destroy(self._state)
            self._state = None
        self._finished = True


def _rnnoise_library():
    name = ctypes.util.find_library("rnnoise")
    if not name:
        raise RuntimeError("降噪需要 RNNoise 系统库；Arch 安装 rnnoise，或设置 audio.noise_suppression = false")
    library = ctypes.CDLL(name)
    if not hasattr(library, "rnnoise_model_from_buffer"):
        raise RuntimeError("需要 RNNoise 0.2 或更新版本，请升级系统 rnnoise 库")
    library.rnnoise_get_frame_size.argtypes = []
    library.rnnoise_get_frame_size.restype = ctypes.c_int
    library.rnnoise_create.argtypes = [ctypes.c_void_p]
    library.rnnoise_create.restype = ctypes.c_void_p
    library.rnnoise_destroy.argtypes = [ctypes.c_void_p]
    library.rnnoise_destroy.restype = None
    pointer = ctypes.POINTER(ctypes.c_float)
    library.rnnoise_process_frame.argtypes = [ctypes.c_void_p, pointer, pointer]
    library.rnnoise_process_frame.restype = ctypes.c_float
    return library
