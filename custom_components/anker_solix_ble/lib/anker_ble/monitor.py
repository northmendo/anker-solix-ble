"""BLE monitor for Anker SOLIX F1200 / 757 PowerHouse.

Maintains the connection to the notify characteristic and yields decoded
telemetry. Includes automatic reconnect with backoff.

Keep-alive notes (documented in docs/PROTOCOL.md):
- After connecting, the monitor writes the wake/status query (WAKE_QUERY) to
  the command characteristic. This is what the official Anker app does to
  wake a unit that has dropped into standby: the unit keeps a low-duty radio
  listen window in standby (so it answers connect attempts "eventually, but
  not that fast"), and the query forces the BMS to push telemetry even when
  idle. The query is re-sent periodically (WAKE_POLL_INTERVAL).
- The device itself pushes telemetry at ~2 Hz once subscribed, which keeps the
  BLE link alive at the L2CAP level in normal operation.
- The real-world failure mode is the USB dongle going into autosuspend
  (CSR 8510 / TP-Link UB400). Fix: udev rule pinning power/control=on
  (see udev/90-ub400-nosuspend.rules).
- If no packet arrives for a while, treat the link as stale: disconnect,
  rescan, reconnect, resubscribe.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakDeviceNotFoundError

from .protocol import CHAR_COMMAND, CHAR_NOTIFY, SERVICE_UUID, Telemetry, WAKE_QUERY, decode

_LOGGER = logging.getLogger(__name__)

# How often to re-send the wake query to a connected unit. Matches the
# F2000/767 integration's DEFAULT_POLL_INTERVAL of 30 s.
WAKE_POLL_INTERVAL = 30.0


async def _bluez_device_from_address(address: str) -> "Any | None":
    """Resolve a known BlueZ device without scanning.

    bleak >= 3 resolves ``BleakClient(address)`` by scanning, which misses
    standby units that do not advertise. BlueZ keeps such devices in its
    ObjectManager (D-Bus) once seeded (scripts/seed-bluez-device.sh), and a
    BLEDevice with the known path connects directly. Returns a BLEDevice or
    None if BlueZ has no object for the address.
    """
    try:
        from dbus_fast.aio import MessageBus
        from dbus_fast.constants import BusType
    except ImportError:
        return None

    try:
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        obj = bus.get_proxy_object(
            "org.bluez", "/", "org.freedesktop.DBus.ObjectManager"
        )
        iface = obj.get_interface("org.freedesktop.DBus.ObjectManager")
        objects = await iface.call_get_managed_objects()
        await bus.disconnect()
    except Exception:
        return None

    target = address.upper().replace(":", "_")
    for path, interfaces in objects.items():
        props = interfaces.get("org.bluez.Device1", {})
        dev_addr = (props.get("Address") or "").replace(":", "_").upper()
        if dev_addr == target:
            from bleak.backends.device import BLEDevice

            return BLEDevice(address, props.get("Name") or None, {"path": path})
    return None


class AnkerMonitor:
    """Async BLE monitor for an Anker power station.

    Args:
        address: BLE MAC address (e.g. "E8:EE:CC:00:00:01").
        stale_after: seconds without a packet before forcing a reconnect.
        retry_delay: base seconds between reconnect attempts (exponential
            backoff, capped).
        client_provider: optional async callable returning an already-
            connected BleakClient. When set, the monitor never opens its
            own connection (and never disconnects); it just subscribes and
            consumes. This is how the Home Assistant integration hands in
            a connection managed by bleak_retry_connector / HA's Bluetooth
            integration. Default None = standalone mode (CLI): the monitor
            connects/disconnects and reconnects by itself.
    """

    def __init__(
        self,
        address: str,
        stale_after: float = 30.0,
        retry_delay: float = 5.0,
        client_provider=None,
    ) -> None:
        self.address = address.upper()
        self.stale_after = stale_after
        self.retry_delay = retry_delay
        self.client_provider = client_provider
        self._last_packet = 0.0
        self._latest: Telemetry | None = None
        self._stop = False
        self._client: BleakClient | None = None

    async def send_command(self, payload: bytes) -> None:
        """Write an arbitrary command payload to the command characteristic.

        Raises ConnectionError if the monitor is not currently connected.
        """
        if self._client is None or not self._client.is_connected:
            raise ConnectionError("monitor is not connected")
        await self._client.write_gatt_char(CHAR_COMMAND, payload, response=False)

    async def set_charge_rate(self, watts: int) -> None:
        """Set the AC charge rate in watts (verified: 100 / 200 on unit)."""
        from .protocol import charge_rate_command

        await self.send_command(charge_rate_command(watts))

    async def stream(self) -> AsyncIterator[Telemetry]:
        """Yield telemetry packets forever, reconnecting as needed."""
        while not self._stop:
            try:
                async for telemetry in self._stream_once():
                    yield telemetry
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect on any failure
                _LOGGER.warning("connection lost (%s), reconnecting", exc)
            await asyncio.sleep(self.retry_delay)

    async def _stream_once(self) -> AsyncIterator[Telemetry]:
        if self.client_provider is not None:
            # Home Assistant mode: the caller (coordinator) manages the
            # connection via bleak_retry_connector. We subscribe and
            # consume; on exit we stop notifications but never disconnect
            # (the coordinator's next _get_client call creates a fresh
            # connection, and bleak_retry_connector pools/releases the old).
            client = await self.client_provider()
            if client is None or not client.is_connected:
                _LOGGER.warning("external client for %s not connected, retrying",
                                self.address)
                return
            try:
                async for telemetry in self._consume(client):
                    yield telemetry
            finally:
                self._client = None
            return

        # Standalone mode: try a direct connect first: a station in standby
        # may not advertise, but still answers a connect request by address.
        device = None
        try:
            client = BleakClient(self.address, timeout=20.0)
            await client.connect()
        except BleakDeviceNotFoundError:
            # bleak >= 3 resolves addresses by SCANNING, and a standby unit
            # does not advertise — even though BlueZ knows it (the D-Bus
            # device object exists). Resolve the device from BlueZ's
            # ObjectManager (no scan) and connect via the known path.
            # This preserves connect-by-address for seeded standby units.
            device = await _bluez_device_from_address(self.address)
            if device is None:
                # BlueZ has no entry for this address either. If the unit is
                # in standby it does not advertise, so a scan cannot find it
                # either. Fix: seed BlueZ's device store once
                # (scripts/seed-bluez-device.sh). After seeding, the object
                # manager resolves it and connect-by-address issues a
                # directed LE connection that succeeds when the unit's radio
                # is in its low-duty listen window.
                _LOGGER.warning(
                    "device %s unknown to BlueZ; run scripts/seed-bluez-device.sh "
                    "%s to seed it (see README), retrying", self.address, self.address
                )
                return
            client = BleakClient(device, timeout=20.0)
            await client.connect()
        except Exception:
            # Fall back to discovery (required on some adapters, and picks up
            # the D-Bus path on Linux when a cached device is found).
            device = await self._find_device()
            if device is None:
                _LOGGER.warning("device %s not found, retrying", self.address)
                return
            client = BleakClient(device, timeout=20.0)
            await client.connect()

        try:
            async for telemetry in self._consume(client):
                yield telemetry
        finally:
            await client.disconnect()
            self._client = None

    async def _consume(self, client: BleakClient) -> AsyncIterator[Telemetry]:
        """Subscribe, wake, and yield decoded telemetry on an open client.

        Never calls client.disconnect() — that is the caller's responsibility
        (_stream_once in standalone mode; the coordinator in HA mode).
        """
        _LOGGER.info("connected to %s", self.address)
        self._client = client

        def on_notify(_char, data: bytearray) -> None:
            self._last_packet = asyncio.get_event_loop().time()
            packet = decode(bytes(data))
            if packet is not None:
                self._latest = packet

        await client.start_notify(CHAR_NOTIFY, on_notify)
        self._latest = None

        # Wake the unit / keep the BMS reporting, exactly like the
        # official app: write the status query after connect, then
        # re-send it periodically in case the unit drops into standby.
        async def _wake_pump() -> None:
            while True:
                try:
                    await client.write_gatt_char(CHAR_COMMAND, WAKE_QUERY, response=False)
                except Exception:  # noqa: BLE001 - link may be gone; main loop handles it
                    _LOGGER.debug("wake query write failed", exc_info=True)
                    return
                await asyncio.sleep(WAKE_POLL_INTERVAL)

        await client.write_gatt_char(CHAR_COMMAND, WAKE_QUERY, response=False)
        wake_task = asyncio.create_task(_wake_pump())

        try:
            while True:
                await asyncio.sleep(0.25)
                if self._latest is not None:
                    yield self._latest
                    self._latest = None
                now = asyncio.get_event_loop().time()
                if now - self._last_packet > self.stale_after:
                    _LOGGER.warning("no packet for %.0fs, reconnecting",
                                    now - self._last_packet)
                    break
        finally:
            wake_task.cancel()
            await client.stop_notify(CHAR_NOTIFY)

    async def _find_device(self):
        for _ in range(3):
            found = {}

            def callback(device, advertising_data):
                if device.address.upper() == self.address:
                    found["device"] = device

            async with BleakScanner(callback) as scanner:
                await asyncio.sleep(6)
            if found:
                return found["device"]
        return None

    def stop(self) -> None:
        self._stop = True
