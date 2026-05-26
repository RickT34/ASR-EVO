from __future__ import annotations

import sys

from .config import AppConfig


def create_runtime(config: AppConfig):
    if sys.platform == "darwin":
        from .platforms.macos.runtime import MacOSDictationRuntime

        return MacOSDictationRuntime(config)
    raise SystemExit(f"ASR-EVO does not yet ship a runnable desktop runtime for {sys.platform}.")


def main() -> None:
    config = AppConfig.load()
    create_runtime(config).run()


if __name__ == "__main__":
    main()
