"""Anker SOLIX F1200 / 757 PowerHouse BLE integration for Home Assistant."""
import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import AnkerDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SELECT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    # Refuse to set up if HA's Bluetooth integration is not available
    # (no BLE adapter or not configured). This gives the user a clear
    # error instead of a silently failing coordinator.
    if not bluetooth.async_scanner_count(hass, connectable=True):
        raise ConfigEntryNotReady("No Bluetooth adapter available (bluetooth integration)")
    coordinator = AnkerDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    await coordinator.async_start()
    hass.data.setdefault("anker_solix_ble", {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data["anker_solix_ble"].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok
