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
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import AnkerDataUpdateCoordinator

SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="battery_soc",
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
        AnkerSensor(coordinator, entry, description)
        for description in SENSORS
    )


class AnkerSensor(CoordinatorEntity[AnkerDataUpdateCoordinator], SensorEntity):
    def __init__(
        self,
        coordinator: AnkerDataUpdateCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}-{description.key}"
        self._attr_name = f"Anker {entry.data.get('name', 'Power Station')} {description.name}"
        self._attr_device_info = {
            "identifiers": {("anker_solix_ble", entry.entry_id)},
            "name": entry.data.get("name", "Anker Power Station"),
            "manufacturer": "Anker",
            "model": entry.data.get("model", "SOLIX F1200 / 757 PowerHouse"),
        }

    @property
    def native_value(self):
        data = self.coordinator.data
        if data is None:
            return None
        return getattr(data, self.entity_description.key)
