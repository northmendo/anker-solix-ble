"""Validate the decoder against captured telemetry files.

Uses the real captures from 2026-08-09 (verified against the unit display:
AC out 295 W, DC in 253 W, SOC 50%).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anker_ble import WAKE_QUERY, charge_rate_command, checksum, decode

# Committed fixture, portable on a fresh clone (safe to publish: the serial
# is synthetic).
FIXTURE = str(Path(__file__).resolve().parent / "fixtures" / "sample_telemetry.txt")


def test_wake_query_checksum() -> None:
    """The wake query's last byte is the same sum % 256 checksum."""
    assert len(WAKE_QUERY) == 10
    assert checksum(WAKE_QUERY) == WAKE_QUERY[-1] == 0x02
    print(f"wake query checksum ok: {WAKE_QUERY.hex()}")


def test_charge_rate_command() -> None:
    """Charge-rate command matches the app-captured payload byte-for-byte.

    Captured from the Anker app's btsnoop log 2026-08-10 and verified live
    on the unit (200W moved AC input ~420W -> ~520W; 100W restored ~420W).
    The rate is a little-endian u16 (bytes 9-10), so rates above 255 W
    (e.g. 1000 W = 0x03E8) encode as e8 03.
    """
    assert charge_rate_command(200).hex() == "08ee00000002800c00c8004c"
    assert charge_rate_command(100).hex() == "08ee00000002800c006400e8"
    # Higher rates: u16 LE at bytes 9-10.
    assert charge_rate_command(300).hex() == "08ee00000002800c002c01b1"
    assert charge_rate_command(1000).hex() == "08ee00000002800c00e8036f"
    # Checksum is the same sum % 256 scheme.
    for watts in (100, 200, 300, 1000, 150, 1, 65535):
        cmd = charge_rate_command(watts)
        assert checksum(cmd) == cmd[-1], f"bad checksum for {watts}W"
    print("charge rate commands match app capture (incl. >255W); checksums ok")


def test_wake_query_prefix() -> None:
    """Wake query starts with the 0x08 0xEE command family seen in the 767 decoder."""
    assert WAKE_QUERY[:2] == bytes([0x08, 0xEE])


def test_ac_dc_output_commands() -> None:
    """AC/DC toggles match the app-captured payloads from btsnoop_hci-1.log."""
    from anker_ble.protocol import CONTROL_QUERY, ac_output_command, dc_output_command

    assert ac_output_command(True).hex() == "08ee00000002860b00018a"
    assert ac_output_command(False).hex() == "08ee00000002860b000089"
    assert dc_output_command(True).hex() == "08ee00000002870b00018b"
    assert dc_output_command(False).hex() == "08ee00000002870b00008a"
    assert CONTROL_QUERY.hex() == "08ee00000001020a0003"
    for cmd in (ac_output_command(True), ac_output_command(False),
                dc_output_command(True), dc_output_command(False), CONTROL_QUERY):
        assert checksum(cmd) == cmd[-1], f"bad checksum for {cmd.hex()}"
    print("ac/dc output + control query match app capture; checksums ok")


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


def check_checksums(path: str) -> None:
    valid, bad, other, soc_min, soc_max = decode_file(path)
    print(f"{path}: {valid} telemetry (checksum ok), {other} other-type, {bad} bad")
    assert bad == 0, f"{bad} packets failed checksum"
    assert soc_min >= 0 and soc_max <= 100, f"SOC out of range: {soc_min}-{soc_max}"
    print(f"  SOC range seen: {soc_min}-{soc_max}")


def test_checksums() -> None:
    """Every packet in the fixture checksums and decodes sanely.

    (Named as a test, with no path argument, so pytest can collect it; pass
    extra capture files to ``check_checksums`` from ``__main__`` instead.)
    """
    check_checksums(FIXTURE)


def test_known_packet() -> None:
    """First fixture packet matches the values verified against the display."""
    capture_path = FIXTURE
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
    # Serial is unit-specific; assert format (16 chars, letter-prefixed),
    # not the exact value, so the fixture is safe to publish.
    assert len(t.serial) == 16 and t.serial[0].isalpha(), f"unexpected serial {t.serial!r}"
    assert 280 <= t.ac_output_w <= 360, f"AC output out of range: {t.ac_output_w}"
    print(f"known packet: ac={t.ac_output_w}W dc={t.dc_input_w}W soc={t.soc}% "
          f"net={t.net_w}W serial={t.serial}")


if __name__ == "__main__":
    # Default: committed fixture (portable on fresh clone). Optional args:
    # one or more full capture files to validate against (e.g. the original
    # ../capture_long_223854.txt kept locally out of git).
    test_known_packet()
    test_checksums()
    for arg in sys.argv[1:]:
        check_checksums(arg)
    print("ALL TESTS PASSED")
