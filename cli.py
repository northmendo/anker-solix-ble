#!/usr/bin/env python3
"""Standalone CLI monitor for Anker SOLIX F1200 / 757 PowerHouse over BLE.

Usage:
    python cli.py E8:EE:CC:00:00:01
    python cli.py --once E8:EE:CC:00:00:01
    python cli.py --capture 60 E8:EE:CC:00:00:01
    python cli.py --set-charge-rate 200 E8:EE:CC:00:00:01
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

from anker_ble import AnkerMonitor


async def run(
    address: str,
    once: bool,
    capture: int | None,
    set_charge_rate: int | None = None,
) -> None:
    monitor = AnkerMonitor(address)
    if set_charge_rate is not None:
        # Connect, apply the rate, read one packet back to confirm, exit.
        try:
            async for t in monitor.stream():
                await monitor.set_charge_rate(set_charge_rate)
                print(
                    json.dumps(
                        {"set_charge_rate_w": set_charge_rate, **t.as_dict()}
                    ),
                    flush=True,
                )
                break
        except ConnectionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return
        except KeyboardInterrupt:
            pass
        return
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
    parser.add_argument("--set-charge-rate", type=int, default=None, metavar="W",
                        help="set AC charge rate in watts (verified: 100, 200) and exit")
    args = parser.parse_args()
    try:
        asyncio.run(
            run(args.address, args.once, args.capture, args.set_charge_rate)
        )
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
