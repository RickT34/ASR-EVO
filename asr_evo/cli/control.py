from __future__ import annotations

import argparse
import json
import sys

from asr_evo.config import AppConfig
from asr_evo.core.control import CONTROL_COMMANDS, send_control_command


def main() -> None:
    parser = argparse.ArgumentParser(description="Control the running ASR-EVO tray process.")
    parser.add_argument("command", choices=sorted(CONTROL_COMMANDS))
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--port", type=int, default=None, help="Override the control port.")
    parser.add_argument("--json", action="store_true", help="Print the raw JSON response.")
    args = parser.parse_args()

    config = AppConfig.load(args.config)
    port = args.port or config.control.port
    try:
        response = send_control_command(args.command, port=port)
    except OSError as exc:
        raise SystemExit(f"ASR-EVO control endpoint is unavailable at 127.0.0.1:{port}: {exc}") from exc

    if args.json:
        print(json.dumps(response, ensure_ascii=False))
    else:
        print(_format_response(args.command, response))
    if not response.get("ok"):
        sys.exit(1)


def _format_response(command: str, response: dict) -> str:
    state = response.get("state", "unknown")
    if response.get("ok"):
        return f"{command}: {state}"
    return f"{command}: failed ({response.get('error', 'unknown error')})"


if __name__ == "__main__":
    main()
