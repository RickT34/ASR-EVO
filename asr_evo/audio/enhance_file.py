from __future__ import annotations

import os
import tempfile
from pathlib import Path

import soundfile as sf

from asr_evo.audio.enhancement import AudioProcessingOptions, SpeechEnhancer
from asr_evo.core.ports import AudioClip


def enhance_file(source: Path, destination: Path, options: AudioProcessingOptions) -> AudioClip:
    """Process an existing recording with exactly the live recording's filter."""
    if source.resolve() == destination.resolve():
        raise ValueError("输出路径不能与原录音相同")
    if destination.exists():
        raise FileExistsError(f"输出文件已存在：{destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix="asr-evo-enhanced-", suffix=".wav", dir=destination.parent)
    os.close(fd)
    temporary = Path(filename)
    try:
        with sf.SoundFile(source) as input_file:
            processor = SpeechEnhancer(input_file.samplerate, options)
            try:
                with sf.SoundFile(temporary, "w", samplerate=processor.sample_rate, channels=1, subtype="PCM_16") as output:
                    for frames in input_file.blocks(blocksize=max(1, input_file.samplerate // 10), dtype="float32", always_2d=True):
                        output.write(processor.process(frames))
                    output.write(processor.finish())
                    samples = output.frames
            finally:
                processor.close()
        temporary.replace(destination)
        return AudioClip(destination, processor.sample_rate, samples / processor.sample_rate)
    finally:
        temporary.unlink(missing_ok=True)
