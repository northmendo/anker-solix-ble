"""Charge-rate select entity for Anker SOLIX F1200 / 757 PowerHouse BLE.

The unit does not report its current AC charge rate back over BLE in the
telemetry we decode, so the select can only ever report *what HA wrote*:
state is ``unknown`` until a write succeeds in this HA session, then the
last successfully written rate. It is never a guess. Writes go through the
coordinator to the command characteristic and raise if the BLE link is
down, so a failed write leaves the state untouched. Rate value is a
little-endian u16 (100-1000 W verified encoding; 100/200 W verified live on
the unit).

For automations: ``select.select_option`` succeeds only when the command
actually reached the unit, so ``is_state('select...charge_rate', '100')``
after a successful call means "100 W was written over a live link". Use an
error path (``continue_on_error`` + a notification) for the case where the
link is down, and never require this state to gate charging safety.
"""
from __future__ import annotations

import datetime

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import AnkerDataUpdateCoordinator

CHARGE_RATE_OPTIONS = [str(w) for w in range(100, 1001, 100)]  # 100..1000 W


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data["anker_solix_ble"][entry.entry_id]
    async_add_entities([ChargeRateSelect(coordinator, entry)])


class ChargeRateSelect(SelectEntity):
    """Charge-rate select that only reports rates HA has written."""

    def __init__(
        self,
        coordinator: AnkerDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        self.coordinator = coordinator
        self._entry = entry
        self._address = entry.data["address"]
        self._attr_unique_id = f"{self._address}-charge-rate"
        self._attr_name = f"Anker {entry.data.get('name', 'Power Station')} charge rate"
        self._attr_options = CHARGE_RATE_OPTIONS
        # No value until a write succeeds: defaulting to "100" made the
        # entity claim a rate the unit may never have been told (the unit
        # has no rate readback), which fooled automations that used it as
        # verification.
        self._attr_current_option = None
        self._last_write: str | None = None
        self._attr_device_info = {
            "identifiers": {("anker_solix_ble", self._address)},
            "name": entry.data.get("name", "Anker Power Station"),
            "manufacturer": "Anker",
            "model": entry.data.get("model", "SOLIX F1200 / 757 PowerHouse"),
        }

    @property
    def available(self) -> bool:
        """Only writable while the unit is connected and reporting."""
        return self.coordinator.is_fresh()

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """When the last write landed (UTC), for automations that care."""
        if self._last_write is None:
            return {}
        return {"last_write": self._last_write}

    async def async_select_option(self, option: str) -> None:
        """Write the chosen rate to the unit, then record it as written.

        Raises (HA shows a red error, automations see the failure) if the
        unit is unreachable; the state is left unchanged in that case.
        """
        watts = int(option)
        await self.coordinator.set_charge_rate(watts)
        self._attr_current_option = option
        self._last_write = datetime.datetime.now(datetime.UTC).isoformat(
            timespec="seconds"
        )
        self.async_write_ha_state()
