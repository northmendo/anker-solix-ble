"""AC/DC output switches for Anker SOLIX F1200 / 757 PowerHouse BLE.

Commands are the app-captured payloads (cmd 0x86 = AC, cmd 0x87 = DC,
0x01 = on, 0x00 = off) — see docs/PROTOCOL.md. The coordinator sends
CONTROL_QUERY before each toggle, mirroring the app's write pattern.

NOTE: the toggle was captured from the app and ACKed by the unit, but has
not been live-verified from HA yet (probes without CONTROL_QUERY were
ignored by the unit; with the query, pending on-unit verification).
"""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import AnkerDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data["anker_solix_ble"][entry.entry_id]
    async_add_entities(
        [
            AnkerOutputSwitch(coordinator, entry, "ac_output", "AC output"),
            AnkerOutputSwitch(coordinator, entry, "dc_output", "DC output"),
        ]
    )


class AnkerOutputSwitch(SwitchEntity):
    """Optimistic switch for an AC/DC output on the unit."""

    def __init__(
        self,
        coordinator: AnkerDataUpdateCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
    ) -> None:
        self.coordinator = coordinator
        self._entry = entry
        self._key = key
        self._address = entry.data["address"]
        self._attr_unique_id = f"{self._address}-{key}"
        self._attr_name = f"Anker {entry.data.get('name', 'Power Station')} {name}"
        self._attr_device_info = {
            "identifiers": {("anker_solix_ble", self._address)},
            "name": entry.data.get("name", "Anker Power Station"),
            "manufacturer": "Anker",
            "model": entry.data.get("model", "SOLIX F1200 / 757 PowerHouse"),
        }
        # Unit does not report output state in decoded telemetry; optimistic.
        self._attr_is_on = None

    @property
    def available(self) -> bool:
        return self.coordinator.is_fresh()

    async def async_turn_on(self, **_: object) -> None:
        await self._set(True)

    async def async_turn_off(self, **_: object) -> None:
        await self._set(False)

    async def _set(self, on: bool) -> None:
        if self._key == "ac_output":
            await self.coordinator.set_ac_output(on)
        else:
            await self.coordinator.set_dc_output(on)
        self._attr_is_on = on
        self.async_write_ha_state()
