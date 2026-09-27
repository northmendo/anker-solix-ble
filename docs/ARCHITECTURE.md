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

HA's Bluetooth integration resolves the address from the advertisements it
has seen, which covers the normal case. It cannot resolve a unit that has
never advertised since BlueZ last started — a F1200 in standby is radio
silent — so the coordinator falls back to BlueZ's device store
(`anker_ble.monitor.bluez_device_from_address`) before giving up. The
standalone CLI relies on the same resolution; seeding BlueZ
(`scripts/seed-bluez-device.sh`) makes it permanent across restarts for
both paths.

### Field failure modes handled by the coordinator (0.4.6)

Both were observed on a live install (2026-09-27):

- **Standby unit, unresolvable address.** HA's registry returned nothing and
  the integration retried forever while the unit sat in standby; a directed
  connect through the BlueZ-resolved path recovers it. Fix: BlueZ fallback
  in `_get_client()`.
- **Died consumer loop.** An exception escaping the stream consumer left
  every entity frozen until HA restarted the integration. Fix: `_run()` is a
  supervised loop (log + restart after `STREAM_RESTART_DELAY`, 30 s).
- **Dishonest rate entity.** The charge-rate select defaulted to `100`,
  so automations that wrote a rate and then checked the entity state were
  "verifying" a value the unit may never have received (the unit has no rate
  readback). Fix: the select reports `unknown` until a write succeeds in the
  current session, and a failed write leaves the state untouched. Automations
  should gate charging safety on their own logic, not on this entity.

## Why not a raw BleakClient in HA

A raw client bypasses HA's Bluetooth stack, which causes:
- BLE contention (two stacks competing for one radio)
- No connection pooling with other BLE integrations
- No access to HA's discovery/registry (the config flow pre-fills the
  station address from `async_discovered_service_info`)
- Duplicated retry logic HA already provides

The `bleak_retry_connector` pattern is the standard HA BLE approach and is
used by the F2000/767 integration for the same product family.

## Packaging

The HA component vendors the protocol library at
`custom_components/anker_solix_ble/lib/anker_ble/` so the component is
self-contained (HA installs it as a folder; there is no root-level
`anker_ble/` on sys.path there). `tests/test_ha_wiring.py` asserts the
vendored copy matches the root package, and that every HA sensor key
resolves on the `Telemetry` dataclass (guards against the unavailable-
entity bug class).

## Server-side proxy (future transport)

The protocol core is ready for a third transport: a small daemon
(`ankerd`) wrapping `AnkerMonitor.stream()` and publishing telemetry to
MQTT; HA would subscribe instead of connecting over BLE. This was a
"maybe" from the user (2026-08-10): server keeps the BLE link, reports to
HA. Not implemented — revisit if direct-BLE proves flaky.
