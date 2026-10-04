from __future__ import annotations

import argparse
from pathlib import Path

from asr_evo.audio.enhance_file import enhance_file
from asr_evo.config import AudioConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="离线降噪并增强录音，保留原文件。")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--gain-db", type=float, default=0)
    parser.add_argument("--mix", type=float, default=0.85)
    parser.add_argument("--no-denoise", action="store_true", help="只调整音量，用于等增益对比")
    args = parser.parse_args()
    options = AudioConfig(noise_suppression=not args.no_denoise, input_gain_db=args.gain_db,
                          denoise_mix=args.mix).processing_options()
    clip = enhance_file(args.input, args.output, options)
    print(f"已保存：{clip.path}（{clip.duration_seconds:.2f} 秒，{clip.sample_rate} Hz）")


if __name__ == "__main__":
    main()
