"""Config flow for Anker SOLIX F1200 / 757 PowerHouse BLE."""
from __future__ import annotations

import re

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

DOMAIN = "anker_solix_ble"

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


class AnkerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input["address"].upper()
            if not MAC_RE.match(address):
                errors["address"] = "invalid_mac"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                # Read-only environment checks (never modify the host).
                if not bluetooth.async_scanner_count(self.hass, connectable=True):
                    self.flow_warnings.append(
                        "No Bluetooth adapter detected by Home Assistant. "
                        "Install/enable the Bluetooth integration first, "
                        "then add this integration."
                    )
                elif bluetooth.async_ble_device_from_address(
                    self.hass, address, connectable=True
                ) is None:
                    self.flow_warnings.append(
                        "The station was not seen by HA's Bluetooth scanner "
                        "yet. If it is in standby it may not advertise - "
                        "wake it with the Anker app once, or keep this entry "
                        "and the coordinator will retry."
                    )
                return self.async_create_entry(
                    title=user_input.get("name") or address,
                    data={
                        "address": address,
                        "name": user_input.get("name") or "",
                        "model": user_input.get("model") or "SOLIX F1200 / 757 PowerHouse",
                    },
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("address"): str,
                    vol.Optional("name", default="Power Station"): str,
                    vol.Optional(
                        "model", default="SOLIX F1200 / 757 PowerHouse"
                    ): str,
                }
            ),
            errors=errors,
        )
