from __future__ import annotations

from .config import AppConfig


def main() -> None:
    config = AppConfig.load()
    print(f"ASR-EVO loaded config for hotkey: {config.hotkey.toggle}")
    print("The macOS tray runtime will be wired in after provider credentials are configured.")


if __name__ == "__main__":
    main()
