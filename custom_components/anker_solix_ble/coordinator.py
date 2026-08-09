"""Coordinator: keeps the BLE link to the Anker station alive and publishes
the latest telemetry to Home Assistant sensors.

Runs AnkerMonitor as a background task. The monitor writes the 10-byte wake
query to the command characteristic every 30 s (WAKE_POLL_INTERVAL) — that is
how the official app wakes a standby unit and keeps the BMS reporting — and
the ~2 Hz notification stream keeps the link alive. The coordinator restarts
the monitor if the link drops.
"""
from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from anker_ble import AnkerMonitor, Telemetry

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL_SECONDS = 10


class AnkerDataUpdateCoordinator(DataUpdateCoordinator[Telemetry | None]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="anker_solix_ble",
            update_interval=None,  # push-driven; refresh() called per packet
        )
        self.address = entry.data["address"]
        self._monitor = AnkerMonitor(address=self.address, stale_after=60.0)
        self._task: asyncio.Task | None = None
        self._latest: Telemetry | None = None
        self.data = None

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
                self.async_set_updated_data(t)
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            _LOGGER.exception("monitor crashed")
            raise UpdateFailed(f"BLE monitor failed: {exc}") from exc

    async def async_shutdown(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
