"""Config flow for Anker SOLIX F1200 / 757 PowerHouse BLE."""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfo,
    async_discovered_service_info,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

DOMAIN = "anker_solix_ble"
MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

SERVICE_UUID = "0159f5da-0000-1000-8000-00805f9b34fb"


def _address_from_discovery(
    services: list[BluetoothServiceInfo],
) -> str | None:
    """Return the address of the first discovered Anker station, if any."""
    for svc in services:
        if any(SERVICE_UUID in u for u in svc.service_uuids):
            return svc.address
    return None


class AnkerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for the Anker SOLIX BLE integration."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_address: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input["address"].upper()
            if not MAC_RE.match(address):
                errors["address"] = "invalid_mac"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get("name") or address,
                    data={
                        "address": address,
                        "name": user_input.get("name") or "",
                        "model": user_input.get("model")
                        or "SOLIX F1200 / 757 PowerHouse",
                    },
                )
        # Pre-fill address if HA has discovered an Anker station.
        if self._discovered_address is None:
            services = async_discovered_service_info(self.hass)
            self._discovered_address = _address_from_discovery(list(services))
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "address",
                        default=self._discovered_address or "",
                    ): str,
                    vol.Optional("name", default="Power Station"): str,
                    vol.Optional(
                        "model", default="SOLIX F1200 / 757 PowerHouse"
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfo
    ) -> FlowResult:
        """Handle a Bluetooth discovery (the station advertising)."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovered_address = discovery_info.address
        return await self.async_step_user()
