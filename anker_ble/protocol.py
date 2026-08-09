"""Anker SOLIX F1200 / 757 PowerHouse BLE protocol.

Reverse-engineered from live capture on 2026-08-09, verified against the
unit display (out=295 W, dc-in=253 W, soc=50%). No pairing, no encryption,
no handshake: the device pushes 94-byte telemetry packets at ~2 Hz on the
notify characteristic once subscribed.

GATT layout (NOT the newer 8c8500xx F2000/F3800 protocol):
  Service: 0159f5da-0000-1000-8000-00805f9b34fb
  Notify : 00008888-0000-1000-8000-00805f9b34fb  (94-byte telemetry)
  Write  : 00007777-0000-1000-8000-00805f9b34fb  (read once at connect for
           status; no periodic keep-alive writes needed - the notification
           stream itself keeps the BLE link alive)
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

SERVICE_UUID = "0159f5da-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY = "00008888-0000-1000-8000-00805f9b34fb"
CHAR_COMMAND = "00007777-0000-1000-8000-00805f9b34fb"

PACKET_LEN = 94

# Offsets verified against the unit display 2026-08-09.
# u16 values are little-endian.
_OFF_AC_OUTPUT = 21
_OFF_TOTAL_OUTPUT = 41
_OFF_AC_INPUT = 19
_OFF_DC_INPUT = 37
_OFF_SOC = 64
_OFF_SERIAL = 77
_OFF_CHECKSUM = 93

# Static/unknown bytes (observed, not decoded):
#   byte 17: jittery 34-69, no load correlation - temperature (deg F) candidate
#   byte 31: state flag, toggles 1/2/3 - not mapped
#   byte 33: state, 3 (brief 4/5 on connect)
#   byte 62: const 39 across all captures - temp (deg C) or config byte candidate
#   byte 76: toggles 0/1 - not mapped


@dataclass(frozen=True)
class Telemetry:
    ac_output_w: int
    total_output_w: int
    ac_input_w: int
    dc_input_w: int
    soc: int
    serial: str
    checksum_ok: bool
    raw: bytes

    @property
    def net_w(self) -> int:
        return self.dc_input_w + self.ac_input_w - self.total_output_w

    def as_dict(self) -> dict:
        return {
            "ac_output_w": self.ac_output_w,
            "total_output_w": self.total_output_w,
            "ac_input_w": self.ac_input_w,
            "dc_input_w": self.dc_input_w,
            "net_w": self.net_w,
            "soc": self.soc,
            "serial": self.serial,
        }


def checksum(data: bytes) -> int:
    return sum(data[:-1]) % 256


def decode(pkt: bytes) -> Telemetry | None:
    """Decode a 94-byte telemetry packet. Returns None on bad length."""
    if len(pkt) != PACKET_LEN:
        return None
    return Telemetry(
        ac_output_w=struct.unpack_from("<H", pkt, _OFF_AC_OUTPUT)[0],
        total_output_w=struct.unpack_from("<H", pkt, _OFF_TOTAL_OUTPUT)[0],
        ac_input_w=struct.unpack_from("<H", pkt, _OFF_AC_INPUT)[0],
        dc_input_w=struct.unpack_from("<H", pkt, _OFF_DC_INPUT)[0],
        soc=pkt[_OFF_SOC],
        serial=pkt[_OFF_SERIAL:_OFF_CHECKSUM].decode("ascii", errors="replace"),
        checksum_ok=checksum(pkt) == pkt[_OFF_CHECKSUM],
        raw=pkt,
    )
