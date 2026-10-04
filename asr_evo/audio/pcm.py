from __future__ import annotations


class PCM16StreamEncoder:
    """Stateful resampling preserves samples across device callback boundaries."""

    def __init__(self, sample_rate: int) -> None:
        import soxr

        self.resampler = soxr.ResampleStream(sample_rate, 16000, 1, dtype="float32")

    def encode(self, frames) -> bytes:
        return self._pcm(self.resampler.resample_chunk(frames.mean(axis=1)))

    def finish(self) -> bytes:
        import numpy as np

        return self._pcm(self.resampler.resample_chunk(np.empty(0, dtype="float32"), last=True))

    @staticmethod
    def _pcm(samples) -> bytes:
        import numpy as np

        return (np.clip(samples, -1, 32767 / 32768) * 32768).astype("<i2").tobytes()
