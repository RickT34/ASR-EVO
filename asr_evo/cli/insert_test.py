from __future__ import annotations

import argparse
import asyncio

from asr_evo.config import AppConfig
from asr_evo.platforms.macos.inserter import MacOSTextInserter


def main() -> None:
    parser = argparse.ArgumentParser(description="Insert test text at the current macOS cursor.")
    parser.add_argument("text", nargs="?", default="ASR-EVO insert test")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument(
        "--fallback",
        choices=["unicode_events", "clipboard_restore"],
        default=None,
    )
    args = parser.parse_args()
    config = AppConfig.load(args.config)
    fallback = args.fallback or config.insert.fallback
    asyncio.run(MacOSTextInserter(fallback=fallback).insert(args.text))


if __name__ == "__main__":
    main()
