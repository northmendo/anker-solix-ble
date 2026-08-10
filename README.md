# Anker SOLIX F1200 / 757 PowerHouse — local BLE monitoring

Read live telemetry (battery SOC, AC output, DC input, AC input) from an
Anker SOLIX F1200 / 757 PowerHouse over Bluetooth LE. **No cloud, no Anker
app, no account.** Works with any BlueZ-compatible Bluetooth adapter on Linux.

This project was reverse-engineered from a live BLE capture on 2026-08-09 and
verified against the unit's display. See [docs/PROTOCOL.md](docs/PROTOCOL.md)
for the full protocol write-up.

## Components

- `anker_ble/` — Python protocol library (decode + monitor with auto-reconnect)
- `cli.py` — standalone CLI monitor
- `custom_components/anker_solix_ble/` — Home Assistant integration (vendors
  the protocol lib; uses HA's native Bluetooth integration)
- `scripts/seed-bluez-device.sh` — make BlueZ know a standby (non-advertising)
  station so connect-by-address works (CLI path only)
- `udev/` — udev rule to stop USB dongles from autosuspend-dropping the link
- `docs/PROTOCOL.md` — reverse-engineered BLE protocol (GATT, field map,
  checksum, keep-alive + standby wake notes)
- `docs/ARCHITECTURE.md` — transport design (CLI vs HA), packaging, future
  server-side proxy

## Linux / BlueZ setup (do this first)

The 757/F1200 in standby stops advertising but keeps a low-duty radio listen
window, so it only answers **directed connect requests by address**. Phones
do this natively; BlueZ refuses to connect to an address it has no entry for.
This affects the **CLI / standalone** path (and a raw-BleakClient HA setup).
One-time setup makes the station permanently known to BlueZ:

```bash
sudo scripts/seed-bluez-device.sh E8:EE:CC:00:00:01 757_PowerHouse
```

This writes the device entry into `/var/lib/bluetooth/` and restarts
bluetoothd. It survives reboots. Without it you will see
`Device ... not available` / `BleakDeviceNotFoundError` while the unit is in
standby (it does not advertise, so scanning cannot find it either).

**The HA integration does not need this step**: it connects through HA's
own Bluetooth integration (see docs/ARCHITECTURE.md), which keeps scanning
and resolves the device by address once it has ever been seen.

## Quick start (CLI)

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python cli.py E8:EE:CC:00:00:01
# or one shot:
.venv/bin/python cli.py --once E8:EE:CC:00:00:01
```

Output is one JSON object per telemetry packet (~2 Hz):

```json
{"ac_output_w": 295, "total_output_w": 299, "ac_input_w": 0, "dc_input_w": 253, "net_w": -46, "soc": 50, "serial": "A...58"}
```

## Home Assistant

Copy `custom_components/anker_solix_ble/` into your HA `config/custom_components/`
directory (or install via HACS as a local repository), restart HA, then:

1. Settings → Devices & Services → Add Integration → **Anker SOLIX BLE**
2. Enter the station's BLE MAC address (the address is pre-filled if HA has
   already discovered the station; you can also find it with `bluetoothctl
   scan on` on the HA host)

Sensors: Battery (%), AC output (W), Total output (W), AC input (W),
DC input (W), Net power (W). All update at ~2 Hz over BLE, enabling
automations on power thresholds, SOC, etc.

Control: a **Charge rate** select entity (100 W to 1000 W, 100 W steps,
optimistic) writes the AC charge rate to the unit — 100/200 W verified live.
**AC output** and **DC output** switch entities use the app-captured toggle
payloads (cmd `0x86`/`0x87`, ACKed by the unit; CONTROL_QUERY sent first).

Requires HA's Bluetooth integration to be enabled and a working BLE adapter
on the HA host. The component refuses to start with a clear error if no
adapter is detected.

### If your Bluetooth adapter drops the connection (USB dongle)

CSR 8510 / TP-Link UB400 dongles go into USB autosuspend after ~2 s idle and
the link dies. Install the udev rule:

```bash
sudo install -m 0644 udev/90-ub400-nosuspend.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

## Protocol summary

- GATT service `0159f5da-0000-1000-8000-00805f9b34fb`
- Telemetry notify char `00008888-...` — 94-byte packets at ~2 Hz,
  **no pairing, no encryption**
- Command char `00007777-...` — the 10-byte wake query
  (`08 EE 00 00 00 01 01 0A 00 02`) is written on connect and re-sent every
  30 s to wake a standby unit / keep the BMS reporting
- Checksum: `sum(packet[:-1]) % 256`
- Keep-alive is the notification stream itself; from standby the wake query
  is required (see docs/PROTOCOL.md); the host-side failure mode is USB
  power management (see udev rule)

This is a **different** protocol from the newer SOLIX F2000/F2600/F3800
(`8c8500xx` + ECDH/AES) covered by
[flip-dots/SolixBLE](https://github.com/flip-dots/SolixBLE).

## Status

Monitoring: working, verified against the unit display and live AC-input
behavior. Control: **AC charge rate** is implemented and verified live
(`cli.py --set-charge-rate W`; 200W moves AC input ~420W → ~520W, 100W
restores ~420W). Other control payloads (AC output toggle, light, etc.) are
not yet reverse-engineered — the command characteristic accepts writes (same
`08 EE` family) but their register map is undocumented; contributions welcome.

Home Assistant integration: written against HA's native Bluetooth APIs
(`bluetooth.async_ble_device_from_address` + `bleak_retry_connector`),
compiles and unit-tested for vendored-lib sync, but the HA component itself
has not been exercised end-to-end on a running HA instance by the author —
please test in a staging install before relying on it.

## Disclaimer

Independent project, not affiliated with Anker. Use at your own risk.
