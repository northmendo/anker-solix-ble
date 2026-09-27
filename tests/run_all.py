"""Run every test module in this directory (no pytest needed).

    python3 tests/run_all.py

Each module is executed in its own interpreter so the Home Assistant stubs
installed by test_ha_behavior.py cannot leak into the others. Exits non-zero
if any module fails.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
MODULES = [
    "test_protocol.py",
    "test_ha_wiring.py",
    "test_ha_behavior.py",
    "test_vendored_lib_sync.py",
]


def main() -> int:
    failed = []
    for name in MODULES:
        print(f"=== {name} " + "=" * max(0, 60 - len(name)))
        result = subprocess.run([sys.executable, str(TESTS / name)], text=True)
        if result.returncode != 0:
            failed.append(name)
    print("=" * 64)
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print(f"ALL {len(MODULES)} TEST MODULES PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
