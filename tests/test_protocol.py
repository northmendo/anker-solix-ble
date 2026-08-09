"""Validate the decoder against captured telemetry files.

Uses the real captures from 2026-08-09 (verified against the unit display:
AC out 295 W, DC in 253 W, SOC 50%).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anker_ble import decode


def decode_file(path: str) -> tuple[int, int, int, int, int]:
    valid = bad = other = 0
    soc_min, soc_max = 101, -1
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pkt = bytes.fromhex(line.split()[-1])
            t = decode(pkt)
            if t is None:
                # Non-94-byte packet: the device also emits a 15-byte
                # status/ACK frame with the same checksum scheme.
                other += 1
                continue
            if t.checksum_ok:
                valid += 1
            else:
                bad += 1
            soc_min = min(soc_min, t.soc)
            soc_max = max(soc_max, t.soc)
    return valid, bad, other, soc_min, soc_max


def test_checksums(path: str) -> None:
    valid, bad, other, soc_min, soc_max = decode_file(path)
    print(f"{path}: {valid} telemetry (checksum ok), {other} other-type, {bad} bad")
    assert bad == 0, f"{bad} packets failed checksum"
    assert soc_min >= 0 and soc_max <= 100, f"SOC out of range: {soc_min}-{soc_max}"
    print(f"  SOC range seen: {soc_min}-{soc_max}")


def test_known_packet(capture_path: str) -> None:
    # First real packet from the 2026-08-09 capture (verified vs display).
    with open(capture_path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pkt = bytes.fromhex(line.split()[-1])
            break
    t = decode(pkt)
    assert t is not None
    assert t.checksum_ok, "checksum failed on known packet"
    assert t.serial == "AKER000000000001"
    assert 280 <= t.ac_output_w <= 360, f"AC output out of range: {t.ac_output_w}"
    print(f"known packet: ac={t.ac_output_w}W dc={t.dc_input_w}W soc={t.soc}% "
          f"net={t.net_w}W serial={t.serial}")


if __name__ == "__main__":
    capture_path = sys.argv[1] if len(sys.argv) > 1 else "../capture_long_223854.txt"
    test_known_packet(capture_path)
    for arg in sys.argv[1:]:
        test_checksums(arg)
    print("ALL TESTS PASSED")
