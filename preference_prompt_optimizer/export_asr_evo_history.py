from __future__ import annotations

import argparse
from pathlib import Path

from asr_evo.config import AppConfig, STORAGE_DEFAULTS
from preference_prompt_optimizer.asr_evo_history import load_history_samples, write_samples_jsonl


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export ASR-EVO history as preference optimizer JSONL with reconstructed context."
    )
    parser.add_argument("-o", "--output", required=True, type=Path)
    parser.add_argument("--database", default=STORAGE_DEFAULTS.database_path)
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--segment",
        choices=("style", "app", "app-style"),
        default="style",
        help="How to segment optimizer samples.",
    )
    args = parser.parse_args(argv)

    config = AppConfig.load(args.config)
    samples = load_history_samples(
        args.database,
        context_config=config.context,
        prompts_dir=config.style.prompts_dir,
        limit=args.limit,
        segment=args.segment,
    )
    write_samples_jsonl(samples, args.output)
    print(f"Wrote {len(samples)} samples to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
