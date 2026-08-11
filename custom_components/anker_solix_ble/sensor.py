"""Sensors for Anker SOLIX F1200 / 757 PowerHouse BLE."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import AnkerDataUpdateCoordinator

SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="soc",
        name="Battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
    SensorEntityDescription(
        key="ac_output_w",
        name="AC output",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="total_output_w",
        name="Total output",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="ac_input_w",
        name="AC input",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="dc_input_w",
        name="DC input",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="net_w",
        name="Net power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data["anker_solix_ble"][entry.entry_id]
    async_add_entities(
        [AnkerSensor(coordinator, entry, description) for description in SENSORS]
        + [AnkerMacSensor(entry)]
    )


class AnkerMacSensor(SensorEntity):
    """Diagnostic sensor exposing the BLE MAC (copy-paste from HA)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:bluetooth"

    def __init__(self, entry: ConfigEntry) -> None:
        self._address = entry.data["address"]
        self._attr_unique_id = f"{self._address}-mac"
        self._attr_name = "MAC address"
        self._attr_native_value = self._address
        self._attr_device_info = {
            "identifiers": {("anker_solix_ble", self._address)},
            "name": entry.data.get("name", "Anker Power Station"),
            "manufacturer": "Anker",
            "model": entry.data.get("model", "SOLIX F1200 / 757 PowerHouse"),
        }


class AnkerSensor(CoordinatorEntity[AnkerDataUpdateCoordinator], SensorEntity):
    def __init__(
        self,
        coordinator: AnkerDataUpdateCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._address = entry.data["address"]
        # Stable identity: key off the MAC (the config-entry unique_id),
        # not entry.entry_id, so re-adding the integration does not orphan
        # the device or create duplicate entities.
        self._attr_unique_id = f"{self._address}-{description.key}"
        self._attr_name = f"Anker {entry.data.get('name', 'Power Station')} {description.name}"
        self._attr_device_info = {
            "identifiers": {("anker_solix_ble", self._address)},
            "name": entry.data.get("name", "Anker Power Station"),
            "manufacturer": "Anker",
            "model": entry.data.get("model", "SOLIX F1200 / 757 PowerHouse"),
        }

    @property
    def available(self) -> bool:
        """Entity is available only while the coordinator has fresh data.

        Without this, a unit that dropped to standby leaves the sensor
        frozen on its last value and HA treats it as current.
        """
        return self.coordinator.is_fresh()

    @property
    def native_value(self):
        data = self.coordinator.data
        if data is None:
            return None
        return getattr(data, self.entity_description.key)
