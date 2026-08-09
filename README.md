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
- `custom_components/anker_solix_ble/` — Home Assistant integration
- `udev/` — udev rule to stop USB dongles from autosuspend-dropping the link
- `docs/PROTOCOL.md` — reverse-engineered BLE protocol (GATT, field map,
  checksum, keep-alive notes)

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
{"ac_output_w": 295, "total_output_w": 299, "ac_input_w": 0, "dc_input_w": 253, "net_w": -46, "soc": 50, "serial": "AKER000000000001"}
```

## Home Assistant

Copy `custom_components/anker_solix_ble/` into your HA `config/custom_components/`
directory (or install via HACS as a local repository), restart HA, then:

1. Settings → Devices & Services → Add Integration → **Anker SOLIX BLE**
2. Enter the station's BLE MAC address (find it with `bluetoothctl scan on`)

Sensors: Battery (%), AC output (W), Total output (W), AC input (W),
DC input (W), Net power (W). All update at ~2 Hz over BLE, enabling
automations on power thresholds, SOC, etc.

Requires bluez on the HA host:

```bash
sudo apt install bluez
```

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
- Command char `00007777-...` — read once at connect; no keep-alive writes
- Checksum: `sum(packet[:-1]) % 256`
- Keep-alive is the notification stream itself; the failure mode is host-side
  USB power management (see udev rule)

This is a **different** protocol from the newer SOLIX F2000/F2600/F3800
(`8c8500xx` + ECDH/AES) covered by
[flip-dots/SolixBLE](https://github.com/flip-dots/SolixBLE).

## Status

Monitoring: working, verified. Control (AC output toggle, etc.): not yet
reverse-engineered. The command characteristic accepts writes (see the 767
decoder for a similar unit's format) but the payloads for this unit are
undocumented — contributions welcome.

## Disclaimer

Independent project, not affiliated with Anker. Use at your own risk.
