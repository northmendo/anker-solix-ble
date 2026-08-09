"""BLE monitor for Anker SOLIX F1200 / 757 PowerHouse.

Maintains the connection to the notify characteristic and yields decoded
telemetry. Includes automatic reconnect with backoff.

Keep-alive notes (documented in docs/PROTOCOL.md):
- The device itself pushes telemetry at ~2 Hz once subscribed. This keeps the
  BLE link alive at the L2CAP level; no periodic writes to the command
  characteristic are required for monitoring.
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

from bleak import BleakClient, BleakScanner

from .protocol import CHAR_NOTIFY, SERVICE_UUID, Telemetry, decode

_LOGGER = logging.getLogger(__name__)


class AnkerMonitor:
    """Async BLE monitor for an Anker power station.

    Args:
        address: BLE MAC address (e.g. "E8:EE:CC:00:00:01").
        stale_after: seconds without a packet before forcing a reconnect.
        retry_delay: base seconds between reconnect attempts (exponential
            backoff, capped).
    """

    def __init__(
        self,
        address: str,
        stale_after: float = 30.0,
        retry_delay: float = 5.0,
    ) -> None:
        self.address = address.upper()
        self.stale_after = stale_after
        self.retry_delay = retry_delay
        self._last_packet = 0.0
        self._stop = False

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
        # Try a direct connect first: a station in standby may not advertise,
        # but still answers a connect request by address.
        device = None
        try:
            client = BleakClient(self.address, timeout=20.0)
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
            _LOGGER.info("connected to %s", self.address)

            def on_notify(_char, data: bytearray) -> None:
                self._last_packet = asyncio.get_event_loop().time()
                packet = decode(bytes(data))
                if packet is not None:
                    # Store latest and let the poll loop emit it.
                    self._latest = packet

            await client.start_notify(CHAR_NOTIFY, on_notify)
            self._latest = None
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
                await client.stop_notify(CHAR_NOTIFY)
        finally:
            await client.disconnect()

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
