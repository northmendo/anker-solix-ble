"""Coordinator for Anker SOLIX F1200 / 757 PowerHouse BLE in Home Assistant.

Uses HA's built-in Bluetooth integration (bluetooth.async_ble_device_from_address)
plus bleak_retry_connector for connection management, instead of opening a raw
BleakClient. This lets HA pool the BLE connection with other Bluetooth
integrations and handles retries/backoff natively.
"""
from __future__ import annotations

import asyncio
import logging

from bleak import BleakClient
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .lib.anker_ble import Telemetry, AnkerMonitor

_LOGGER = logging.getLogger(__name__)


class AnkerDataUpdateCoordinator(DataUpdateCoordinator[Telemetry | None]):
    """Push-driven coordinator that consumes the BLE telemetry stream."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="anker_solix_ble",
            update_interval=None,  # push-driven; refresh() called per packet
        )
        self.address = entry.data["address"]
        self._entry = entry
        self._monitor = AnkerMonitor(
            address=self.address,
            stale_after=60.0,
            retry_delay=5.0,
            client_provider=self._get_client,
        )
        self._task: asyncio.Task | None = None
        self._latest: Telemetry | None = None
        self._current_client: BleakClient | None = None
        self._last_packet: float = 0.0
        self.data = None

    async def _get_client(self) -> BleakClient | None:
        """Return an established connection, retrying as needed.

        Uses HA's Bluetooth integration to resolve the address to a BLEDevice
        (so it can connect even when the unit is not advertising, as long as
        HA has ever seen it), then bleak_retry_connector for the connection
        with backoff. This is the standard HA BLE pattern.
        """
        # Disconnect any previous client before establishing a new one:
        # the unit accepts only one connection at a time.
        if self._current_client is not None:
            try:
                await self._current_client.disconnect()
            except Exception:
                _LOGGER.debug("failed to disconnect previous client", exc_info=True)
            self._current_client = None

        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            # Not in HA's Bluetooth registry yet. HA keeps scanning, so it
            # may appear; the monitor retries on our behalf.
            _LOGGER.debug(
                "device %s not in HA Bluetooth registry yet, retrying",
                self.address,
            )
            return None
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                self._entry.entry_id,
            )
            self._current_client = client
            return client
        except Exception as exc:
            _LOGGER.warning("BLE connect to %s failed: %s", self.address, exc)
            return None

    async def _async_update_data(self) -> Telemetry | None:
        """Return the latest packet (pull model for sensor reads)."""
        return self._latest

    async def async_start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="anker-ble-monitor")

    async def _run(self) -> None:
        """Consume the monitor stream, pushing every packet into HA."""
        try:
            async for t in self._monitor.stream():
                self._latest = t
                self.data = t
                self._last_packet = self.hass.loop.time()
                self.async_set_updated_data(t)
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("monitor crashed")
            raise UpdateFailed(f"BLE monitor failed: {exc}") from exc

    def is_fresh(self, grace: float = 5.0) -> bool:
        """True while a telemetry packet arrived recently enough to trust.

        The unit pushes ~2 Hz when connected, so anything older than
        ``stale_after`` plus a small grace means the link is down or the
        unit went to standby: report unavailable instead of stale values.
        """
        if self._last_packet <= 0:
            return False
        return (self.hass.loop.time() - self._last_packet) < (
            self._monitor.stale_after + grace
        )

    async def set_charge_rate(self, watts: int) -> None:
        """Set the AC charge rate in watts (verified: 100 / 200 on unit)."""
        await self._monitor.set_charge_rate(watts)

    async def async_shutdown(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._current_client is not None:
            try:
                await self._current_client.disconnect()
            except Exception:
                pass
            self._current_client = None
