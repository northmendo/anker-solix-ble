# Architecture

## Two transports, one protocol library

`anker_ble/` is the transport-agnostic core: packet decode, the wake query,
and control-command construction (`charge_rate_command()`). Everything above
it is a transport that consumes the same `Telemetry` stream:

```
                   anker_ble/  (protocol core: decode + commands)
                          |
        +-----------------+------------------+
        |                                    |
   cli.py (BLE, standalone)     custom_components/anker_solix_ble/
   anker_ble/monitor.py          (HA integration)
   AnkerMonitor(client_provider=None)      AnkerMonitor(client_provider=...)
```

### Standalone mode (CLI / server daemon)

`AnkerMonitor` opens its own `BleakClient`, retries connect-by-address
(required for standby units that don't advertise), writes the wake query on
connect and every 30 s, and reconnects with backoff. Used by `cli.py`.

### Home Assistant mode

The HA coordinator hands the monitor a **client provider** instead: it
resolves the address through HA's Bluetooth integration
(`bluetooth.async_ble_device_from_address`) and connects with
`bleak_retry_connector.establish_connection`. The monitor then only
subscribes/consumes and never opens or closes the connection itself —
HA owns the BLE lifecycle, pools the adapter with other Bluetooth
integrations, and retries natively.

This is why the HA integration does **not** need the BlueZ seed script:
HA's Bluetooth integration keeps scanning, so once the unit is ever seen
it stays resolvable by address even in standby.

## Why not a raw BleakClient in HA

A raw client bypasses HA's Bluetooth stack, which causes:
- BLE contention (two stacks competing for one radio)
- No connection pooling with other BLE integrations
- No way to validate the device in the config flow
- Duplicated retry logic HA already provides

The `bleak_retry_connector` pattern is the standard HA BLE approach and is
used by the F2000/767 integration for the same product family.

## Packaging

The HA component vendors the protocol library at
`custom_components/anker_solix_ble/lib/anker_ble/` so the component is
self-contained (HA installs it as a folder; there is no root-level
`anker_ble/` on sys.path there). `tests/test_vendored_lib_sync.py` asserts
the vendored copy matches the root package.

## Server-side proxy (future transport)

The protocol core is ready for a third transport: a small daemon
(`ankerd`) wrapping `AnkerMonitor.stream()` and publishing telemetry to
MQTT; HA would subscribe instead of connecting over BLE. This was a
"maybe" from the user (2026-08-10): server keeps the BLE link, reports to
HA. Not implemented — revisit if direct-BLE proves flaky.
