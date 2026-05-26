from __future__ import annotations

import argparse
import asyncio

from asr_evo.config import INSERT_DEFAULTS, AppConfig
from asr_evo.platforms.macos.inserter import MacOSTextInserter


def main() -> None:
    parser = argparse.ArgumentParser(description="Insert test text at the current macOS cursor.")
    parser.add_argument("text", nargs="?", default="ASR-EVO insert test")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument(
        "--mode",
        choices=["pasteboard_restore", "accessibility", "unicode_events", "native"],
        default=None,
    )
    parser.add_argument("--fallback", choices=["unicode_events", "pasteboard_restore"], default=None)
    args = parser.parse_args()
    AppConfig.load(args.config)
    mode = args.mode or INSERT_DEFAULTS.mode
    fallback = args.fallback or INSERT_DEFAULTS.fallback
    asyncio.run(
        MacOSTextInserter(
            mode=mode,
            fallback=fallback,
            restore_delay_ms=INSERT_DEFAULTS.restore_delay_ms,
        ).insert(args.text)
    )


if __name__ == "__main__":
    main()
