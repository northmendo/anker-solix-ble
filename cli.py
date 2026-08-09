#!/usr/bin/env python3
"""Standalone CLI monitor for Anker SOLIX F1200 / 757 PowerHouse over BLE.

Usage:
    python cli.py E8:EE:CC:00:00:01
    python cli.py --once E8:EE:CC:00:00:01
    python cli.py --capture 60 E8:EE:CC:00:00:01
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

from anker_ble import AnkerMonitor


async def run(address: str, once: bool, capture: int | None) -> None:
    monitor = AnkerMonitor(address)
    try:
        async for t in monitor.stream():
            print(json.dumps(t.as_dict()), flush=True)
            if once:
                break
            if capture is not None:
                capture -= 1
                if capture <= 0:
                    break
    except KeyboardInterrupt:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", help="BLE MAC of the power station")
    parser.add_argument("--once", action="store_true", help="print one packet and exit")
    parser.add_argument("--capture", type=int, default=None,
                        help="stop after N packets")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.address, args.once, args.capture))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
