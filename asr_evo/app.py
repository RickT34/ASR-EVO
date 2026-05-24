from __future__ import annotations

import sys

from .config import AppConfig


def main() -> None:
    config = AppConfig.load()
    if sys.platform != "darwin":
        raise SystemExit("ASR-EVO currently ships a runnable macOS runtime only.")

    from .platforms.macos.runtime import MacOSDictationRuntime

    MacOSDictationRuntime(config).run()


if __name__ == "__main__":
    main()
