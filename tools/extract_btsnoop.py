#!/usr/bin/env python3
"""Extract GATT writes to the Anker command characteristic from an Android
Bluetooth HCI snoop log (btsnoop_hci.log).

Why: the Anker app changes settings (e.g. AC charge rate 100W -> 200W) by
writing to UUID 00007777-0000-1000-8000-00805f9b34fb. We want the exact
payload. Android's Developer Options -> "Bluetooth HCI snoop log" writes a
btsnoop file; this script finds ATT Write Request / Write Command packets
targeting the command characteristic (handle resolved from the connection).

Usage:
    python3 tools/extract_btsnoop.py path/to/btsnoop_hci.log

Output: one line per write, with timestamp, ATT opcode, handle, and hex payload.
The payload with a trailing checksum byte (sum%256 of the rest) is our target.

Format notes (btsnoop):
  - File header 16 bytes: magic 0x6274736e ("btsnoop"), version, datalink type
    (1002 = HCI UART / H4)
  - Record header 20 bytes: 4-byte original length, 4-byte captured length,
    4-byte flags, 8-byte timestamp (microseconds since 1970-01-01), then packet
  - H4 type byte: 0x02 = ACL data
  - ACL header: 2-byte handle+flags, 2-byte length, then L2CAP payload
  - L2CAP B-frame: 2-byte len, 2-byte CID (0x0004 = ATT), then ATT payload
  - ATT: opcode 0x12 = Write Request, 0x52 = Write Command, then 2-byte
    handle + value
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

# Anker command characteristic (0x00007777 little-endian in ATT)
CMD_HANDLE = 0x7777
ATT_WRITE_REQ = 0x12
ATT_WRITE_CMD = 0x52
OPCODE_NAMES = {ATT_WRITE_REQ: "write-req", ATT_WRITE_CMD: "write-cmd"}

RECORD_HDR = 20  # 4+4+4+8


def iter_records(path: Path):
    data = path.read_bytes()
    if len(data) < 16 or data[0:8] != b"btsnoop\x00":
        raise ValueError("not a btsnoop file (bad magic)")
    off = 16
    while off + RECORD_HDR <= len(data):
        orig_len, captured_len = struct.unpack_from(">II", data, off)
        ts_us = struct.unpack_from(">Q", data, off + 12)[0]
        pkt = data[off + RECORD_HDR : off + RECORD_HDR + captured_len]
        off += RECORD_HDR + captured_len
        yield ts_us, pkt


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"error: {path} not found", file=sys.stderr)
        return 1

    found = 0
    for ts_us, pkt in iter_records(path):
        if len(pkt) < 1 or pkt[0] != 0x02:  # HCI ACL data
            continue
        acl = pkt[1:]
        if len(acl) < 4:
            continue
        # acl[0:2] = handle+flags, acl[2:4] = length
        l2cap_len = struct.unpack_from("<H", acl, 2)[0]
        if len(acl) < 4 + l2cap_len:
            continue
        l2cap = acl[4 : 4 + l2cap_len]
        if len(l2cap) < 4:
            continue
        # l2cap[0:2] = len, l2cap[2:4] = CID
        cid = struct.unpack_from("<H", l2cap, 2)[0]
        if cid != 0x0004:  # ATT over LE
            continue
        att_len = struct.unpack_from("<H", l2cap, 0)[0]
        att = l2cap[4 : 4 + att_len]
        if len(att) < 3:
            continue
        opcode = att[0]
        if opcode not in OPCODE_NAMES:
            continue
        handle = struct.unpack_from("<H", att, 1)[0]
        value = att[3:]
        found += 1
        marker = "  <== CMD" if handle == CMD_HANDLE else ""
        print(
            f"{ts_us / 1_000_000:.6f}  {OPCODE_NAMES[opcode]:9s}  "
            f"handle 0x{handle:04x}  {len(value)}B  {value.hex()}{marker}"
        )
    if found == 0:
        print("no writes to 0x7777 found in capture", file=sys.stderr)
        print(
            "hint: enable Developer Options -> Bluetooth HCI snoop log, "
            "re-run the app action, then pull /sdcard/btsnoop_hci.log",
            file=sys.stderr,
        )
        return 1
    print(f"\n{found} write(s) to command characteristic 0x{CMD_HANDLE:04x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
