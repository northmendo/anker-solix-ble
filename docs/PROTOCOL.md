# Anker SOLIX F1200 / 757 PowerHouse — BLE protocol notes

Reverse-engineered 2026-08-09 from live captures with a TP-Link UB400
(CSR 8510, USB `0a12:0001`) on Ubuntu 24.04 / bluez 5.72 / bleak.
Decoded values were verified against the unit's display
(AC out = 295 W, DC in = 253 W, SOC = 50%).

## Device identity

- Advertised name: `757_PowerHouse`
- MAC OUI `E8:EE:CC` = Fantasia Trading LLC (Anker). Anker uses this block
  across the SOLIX family.
- The SOLIX F1200 (1024 Wh) and 757 PowerHouse (1229 Wh) share this BLE
  protocol. Other SOLIX models (F2000/F2600/F3800) use a *different* GATT
  layout (`8c8500xx` service with ECDH+AES negotiation) — that protocol is
  covered by [flip-dots/SolixBLE](https://github.com/flip-dots/SolixBLE).

## GATT layout

| Item | UUID |
|---|---|
| Primary service | `0159f5da-0000-1000-8000-00805f9b34fb` |
| Command (write, status on read) | `00007777-0000-1000-8000-00805f9b34fb` |
| Telemetry (notify) | `00008888-0000-1000-8000-00805f9b34fb` |

## Telemetry

- 94-byte packets pushed at ~2 Hz on the notify characteristic once
  subscribed. **No pairing, no encryption, no handshake.**
- Checksum: byte 93 = sum(bytes 0..92) % 256.

### Field map (verified)

| Field | Type | Offset | Verified value |
|---|---|---|---|
| AC input W | u16 LE | 19 | 0 |
| AC output W | u16 LE | 21 | 295 |
| DC input W | u16 LE | 37 | 253 |
| Total output W | u16 LE | 41 | 299 |
| Battery SOC % | u8 | 64 | 50 |
| Serial | ASCII | 77..92 | `A...` (redacted — your unit's serial) |
| Checksum | u8 | 93 | sum % 256 |

### Not yet decoded

| Byte | Behavior | Guess |
|---|---|---|
| 17 | jittery 34-69, no load correlation | temperature, likely deg F |
| 31 | toggles 1/2/3 | state flag (not mapped) |
| 33 | 3, briefly 4/5 on connect | state |
| 62 | constant 39 across all captures | temperature deg C or config byte |
| 76 | toggles 0/1 | state |

### Second frame type (15 bytes)

Occasionally (~1 per 5 min) the device emits a short 15-byte frame on the
same notify characteristic, e.g. `09ff00000101480f00010000000163`. Same
header prefix (`09 ff 00 00 01`), same checksum scheme (sum % 256). Not
decoded; the monitor ignores it. Its low frequency suggests a periodic
status/keep-alive ACK from the device.

## Keep-alive and waking from standby

- **The notification stream itself is the keep-alive during a session.** Once
  subscribed, the device pushes telemetry at ~2 Hz, which keeps the BLE link
  alive at the L2CAP level.
- **How the official app "wakes" a standby unit** (verified 2026-08-09 from
  the F2000/767 HA integration [yun-s-oh/ha-anker-solix-f2000], which mimics
  the app, and the commented `0x08/0xEE` write in
  [BerndAmend/anker_powerhouse_767]):
  1. Retry a **connect-by-address** until the unit accepts. In standby the
     unit stops advertising but keeps a low-duty radio listen window, so a
     connect attempt eventually lands — "it turns off bluetooth eventually,
     but not that fast."
  2. After connecting, **write the 10-byte wake/status query** to `00007777`
     (write, no response): `08 EE 00 00 00 01 01 0A 00 02`. This forces the
     BMS to push telemetry even when the unit is idle.
  3. **Re-send the query periodically** (the F2000 integration uses 30 s) so
     the BMS keeps reporting and the unit does not fall back into standby.
- The monitor does all three: it polls the query every 30 s on an active
  connection, and it retries connect-by-address forever (with scan fallback)
  when the unit is asleep.
- **Linux/BlueZ gotcha — the device must be known to BlueZ first.** Phones
  can direct-connect to any address, but BlueZ refuses to connect to an
  address it has no device entry for (`Device E8:EE:CC:00:00:01 not
  available` from `bluetoothctl`, `BleakDeviceNotFoundError` from bleak).
  Standby units do not advertise, so a scan cannot re-discover them either.
  Fix: seed BlueZ's device store once with
  [`scripts/seed-bluez-device.sh`](../scripts/seed-bluez-device.sh) (writes
  `/var/lib/bluetooth/<adapter>/<MAC>/info` with `SupportedTechnologies=LE`,
  `AddressType=public`, `Trusted=true`, then restarts bluetoothd). Verified
  live 2026-08-09: after seeding, connect-by-address issues a real directed
  LE connection and the unit answers in its listen window (`Connected: yes`).
  The seed survives reboots; re-run it only if bluetoothd's store is wiped.
- **The realistic failure mode is on the host side**, not the device: USB
  adapters with power management (CSR 8510 = TP-Link UB400) go into
  autosuspend after ~2 s idle and drop the connection. Fix is a udev rule
  pinning `power/control=on` (see `udev/90-ub400-nosuspend.rules`).
- **The 15-byte frame is the BMS's response to the wake query.** The F2000
  integration defines `HEADER_PREFIX = 09 FF` for its response frames; our
  15-byte frames (`09 ff 00 00 01 ...`) share that prefix and the same
  checksum scheme. The monitor ignores them (telemetry stays on the 94-byte
  stream), but their presence confirms the wake query path is live.
- On the test box: front USB ports dropped the dongle within 5 s
  (likely platform-managed), rear ports held with the udev rule in place.
- Adapter-agnostic guidance: use any BlueZ-compatible adapter; the protocol
  is standard GATT. If packets stop arriving, disconnect → rescan →
  reconnect → resubscribe (the monitor does this automatically).

## Control commands (AC charge rate)

Reverse-engineered from the official app's btsnoop log 2026-08-10 and
verified live on the unit. Format matches
[yun-s-oh/ha-anker-solix-f2000](https://github.com/yun-s-oh/ha-anker-solix-f2000)
(the same unencrypted protocol family): `08 EE 00 00 00 | 02 | cmd_id |
total_len (u16 LE) | payload | checksum`:

| Command | Payload | Effect (verified) |
|---|---|---|
| Set charge rate 200 W | `08 EE 00 00 00 02 80 0C 00 C8 00 4C` | AC input ~420 W → ~520 W |
| Set charge rate 100 W | `08 EE 00 00 00 02 80 0C 00 64 00 E8` | AC input back to ~420 W |
| Set charge rate 1000 W | `08 EE 00 00 00 02 80 0C 00 E8 03 6F` | rate value is u16 LE; see below |
| AC output ON | `08 EE 00 00 00 02 86 0B 00 01 8A` | app-captured, unit ACKed `09 FF 00 00 01 02 86 0A 00 9B` |
| AC output OFF | `08 EE 00 00 00 02 86 0B 00 00 89` | app-captured, unit ACKed |
| DC output ON | `08 EE 00 00 00 02 87 0B 00 01 8B` | app-captured, unit ACKed `09 FF 00 00 01 02 87 0A 00 9C` |
| DC output OFF | `08 EE 00 00 00 02 87 0B 00 00 8A` | app-captured, unit ACKed |

- Packet type `0x02` = control; byte 6 = command ID; bytes 7-8 = total
  length (u16 LE, includes prefix+checksum); payload follows; last byte =
  checksum (`sum % 256`).
- Cmd `0x80` = AC charge rate, payload u16 LE watts (100/200 confirmed; the
  app also accepts intermediate values — treat as a limit, not a guarantee).
- Cmd `0x88` = screen brightness, payload 0..3. Captured from the app as
  `08 EE 00 00 00 02 88 0B 00 02 8D` (brightness 2) and `... 01 8C`
  (brightness 1). (Previously mislabeled "register 0x880B unknown toggle".)
- Cmd `0x86` / `0x87` = AC/DC output toggle on this unit (1 = on, 0 = off).
  Captured from the app 2026-08-10 (btsnoop_hci-1.log); each write was
  ACKed by the unit. **Prerequisite:** the app sent the control-arming
  query `08 EE 00 00 00 01 02 0A 00 03` (CONTROL_QUERY) plus a CCCD
  re-subscribe before the toggles. Writes without that query were ignored
  by the unit in our probes (no ACK, no state change), so always send
  CONTROL_QUERY first. On-unit effect not yet live-verified from HA.
- Builder: `anker_ble.protocol.charge_rate_command(watts)`;
  `ac_output_command(on)`; `dc_output_command(on)`; CLI:
  `python cli.py --set-charge-rate W <MAC>`,
  `python cli.py --set-ac-output on|off <MAC>`,
  `python cli.py --set-dc-output on|off <MAC>`.

## References

- [yun-s-oh/ha-anker-solix-f2000](https://github.com/yun-s-oh/ha-anker-solix-f2000)
  — F2000/767 HA integration; source of the `08 EE ... 02` wake query, the
  30 s poll cadence, and the standby ("deep standby disables passive
  broadcasts") behavior. Same 7777/8888 UUIDs and header prefix as ours.
- [BerndAmend/anker_powerhouse_767](https://github.com/BerndAmend/anker_powerhouse_767)
  — closest sibling (767/F2000), TypeScript decoder, same 7777/8888 style
- [flip-dots/SolixBLE](https://github.com/flip-dots/SolixBLE) — F2000/F2600/F3800
  BLE, different protocol
- [thomluther/ha-anker-solix](https://github.com/thomluther/ha-anker-solix) —
  cloud-API HA integration (no BLE)
- [moag1000/anker-solix-api-exploration](https://github.com/moag1000/anker-solix-api-exploration)
  — cloud API research
- [anker-charging/ha-anker-solix-official](https://github.com/anker-charging/ha-anker-solix-official)
  — official Modbus integration (different transport)
