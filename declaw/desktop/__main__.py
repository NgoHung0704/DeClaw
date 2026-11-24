"""Fixed native-parent entry point. Never print credentials or raw exceptions."""

from __future__ import annotations

import argparse
import asyncio

from declaw.desktop.channel import PipeChannel
from declaw.desktop.protocol import ProtocolSession


def main() -> int:
    parser = argparse.ArgumentParser(description="Private DeClaw desktop child")
    parser.add_argument("--launch-id", required=True)
    parser.add_argument("--control", type=int, required=True)
    parser.add_argument("--events", type=int, required=True)
    parser.add_argument("--credentials", type=int, required=True)
    args = parser.parse_args()
    try:
        ProtocolSession(args.launch_id)
        channel = PipeChannel.from_handles(
            args.launch_id, args.control, args.events, args.credentials,
        )
        # Inheritance is removed before importing/constructing application services.
        from declaw.config import get_settings
        from declaw.desktop.runtime import run_desktop

        return asyncio.run(run_desktop(get_settings(), channel))
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
