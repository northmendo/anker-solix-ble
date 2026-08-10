"""Charge-rate select entity for Anker SOLIX F1200 / 757 PowerHouse BLE.

The unit does not report its current AC charge rate back over BLE in the
telemetry we decode, so the select is optimistic: HA shows the last value
the user chose. Writes go through the coordinator to the command
characteristic. Rate value is a little-endian u16 (100-1000 W verified
encoding; 100/200 W verified live on the unit).
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import AnkerDataUpdateCoordinator

CHARGE_RATE_OPTIONS = [str(w) for w in range(100, 1001, 100)]  # 100..1000 W
DEFAULT_CHARGE_RATE = "100"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data["anker_solix_ble"][entry.entry_id]
    async_add_entities([ChargeRateSelect(coordinator, entry)])


class ChargeRateSelect(SelectEntity):
    """Optimistic select for the AC charge rate."""

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
        self._attr_current_option = DEFAULT_CHARGE_RATE
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

    async def async_select_option(self, option: str) -> None:
        """Write the chosen rate to the unit, then optimistically update."""
        watts = int(option)
        await self.coordinator.set_charge_rate(watts)
        self._attr_current_option = option
        self.async_write_ha_state()
