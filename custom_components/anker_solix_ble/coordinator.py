"""Coordinator for Anker SOLIX F1200 / 757 PowerHouse BLE in Home Assistant.

Uses HA's built-in Bluetooth integration (bluetooth.async_ble_device_from_address)
plus bleak_retry_connector for connection management, instead of opening a raw
BleakClient. This lets HA pool the BLE connection with other Bluetooth
integrations and handles retries/backoff natively.

Two failure modes are handled explicitly, both seen in the field:

- A unit in standby stops advertising, so HA's Bluetooth registry cannot
  resolve it (it only knows addresses it has seen in advertisements). The
  coordinator then falls back to BlueZ's device store, which is what the
  standalone CLI monitor does.
- The consumer loop is supervised: if the monitor stream dies, the
  coordinator logs it and starts a fresh stream instead of leaving the
  integration frozen until the next HA restart.
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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .lib.anker_ble import AnkerMonitor, Telemetry, bluez_device_from_address

_LOGGER = logging.getLogger(__name__)

# How long to wait before restarting the monitor stream if the consumer loop
# itself dies. The monitor reconnects internally, so this only covers a crash
# of the loop (otherwise the integration would silently stop updating until
# the next HA restart).
STREAM_RESTART_DELAY = 30.0


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
        self._closing = False
        self._restart_delay = STREAM_RESTART_DELAY
        self.data = None

    async def _get_client(self) -> BleakClient | None:
        """Return an established connection, retrying as needed.

        Uses HA's Bluetooth integration to resolve the address to a BLEDevice,
        then bleak_retry_connector for the connection with backoff. HA only
        resolves addresses it has *seen advertising*, so a unit sitting in
        standby (radio silent) falls back to BlueZ's device store; see the
        module docstring.
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
            # HA's Bluetooth registry only resolves addresses it has seen
            # advertising. A station in standby stops advertising entirely,
            # so fall back to BlueZ's device store (D-Bus ObjectManager) and
            # connect through the known path — the same resolution the
            # standalone CLI monitor uses. Without this the integration
            # retries forever while the unit sits in standby.
            device = await bluez_device_from_address(self.address)
            if device is not None:
                _LOGGER.info(
                    "device %s is not advertising; resolved it from the BlueZ "
                    "device store instead",
                    self.address,
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
        """Consume the monitor stream, pushing every packet into HA.

        Supervised: the monitor reconnects internally, so this loop only has
        to cover a crash of the stream itself. Without the retry a died
        stream would leave every entity frozen on its last value (or
        unavailable) until the next HA restart.
        """
        while not self._closing:
            try:
                async for t in self._monitor.stream():
                    self._latest = t
                    self.data = t
                    self._last_packet = self.hass.loop.time()
                    self.async_set_updated_data(t)
                    await asyncio.sleep(0)
                # stream() only returns when the monitor was told to stop.
                return
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - restart the stream on any crash
                _LOGGER.exception(
                    "BLE monitor for %s crashed; restarting in %.0fs",
                    self.address,
                    self._restart_delay,
                )
                await asyncio.sleep(self._restart_delay)

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

    async def set_ac_output(self, on: bool) -> None:
        """Turn the AC output on/off (app-captured cmd 0x86)."""
        await self._monitor.set_ac_output(on)

    async def set_dc_output(self, on: bool) -> None:
        """Turn the DC output on/off (app-captured cmd 0x87)."""
        await self._monitor.set_dc_output(on)

    async def async_shutdown(self) -> None:
        self._closing = True
        self._monitor.stop()
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
