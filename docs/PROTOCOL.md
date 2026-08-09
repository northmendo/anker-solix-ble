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
| Serial | ASCII | 77..92 | `AKER000000000001` |
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

## Keep-alive

- **The notification stream itself is the keep-alive.** Once subscribed, the
  device pushes telemetry at ~2 Hz, which keeps the BLE link alive at the
  L2CAP level. No periodic writes to `00007777` are needed for monitoring
  (confirmed: the 767 PowerHouse decoder [BerndAmend/anker_powerhouse_767]
  reads `7777` once at connect and never writes during the session).
- **The realistic failure mode is on the host side**, not the device: USB
  adapters with power management (CSR 8510 = TP-Link UB400) go into
  autosuspend after ~2 s idle and drop the connection. Fix is a udev rule
  pinning `power/control=on` (see `udev/90-ub400-nosuspend.rules`).
- **The station must be awake.** When the unit enters standby (no load, no
  display interaction for a while), it stops advertising *and* stops
  answering direct connects (`BleakDeviceNotFoundError`). During earlier
  captures it stayed reachable because it was actively powering a server
  (~295 W out). The monitor retries indefinitely; wake the unit (display
  button, or apply a load) and it reconnects on the next scan.
- On the test box test box: front USB ports dropped the dongle within 5 s
  (likely platform-managed), rear ports held with the udev rule in place.
- Adapter-agnostic guidance: use any BlueZ-compatible adapter; the protocol
  is standard GATT. If packets stop arriving, disconnect → rescan →
  reconnect → resubscribe (the monitor does this automatically).

## References

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
