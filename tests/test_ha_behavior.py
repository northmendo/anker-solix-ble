"""Behavioural tests for the HA component.

Covers the three fixes that came out of the 2026-09-27 field incident
(details in docs/ARCHITECTURE.md):

1. the charge-rate select must never report a rate that was not written
   (it defaulted to "100", which made automations "verify" a value the unit
   was never told);
2. the coordinator must resolve a standby unit through BlueZ when HA's own
   Bluetooth registry cannot (a unit in standby does not advertise at all);
3. the telemetry consumer loop is supervised, so a crashed monitor stream
   restarts instead of leaving every entity frozen until an HA restart.

The component imports homeassistant and bleak at import time, and neither is
installed in the test venv. This file installs minimal stubs for exactly the
attributes the component touches, then imports and exercises the real
component code unchanged (same dependency-free approach as
test_ha_wiring.py).

Run directly: ``python3 tests/test_ha_behavior.py``
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ADDRESS = "E8:EE:CC:C7:68:28"


# --------------------------------------------------------------------------
# minimal stubs for the Home Assistant / bleak API surface the component uses
# --------------------------------------------------------------------------
class _Subscriptable:
    """Stub base so ``SomeClass[X]`` works on the stub classes."""

    def __class_getitem__(cls, item):  # noqa: N805 - classmethod semantics
        return cls


class _StubEntity(_Subscriptable):
    def async_write_ha_state(self) -> None:
        pass


class SelectEntity(_StubEntity):
    @property
    def current_option(self):
        return getattr(self, "_attr_current_option", None)


class SensorEntity(_StubEntity):
    pass


class SwitchEntity(_StubEntity):
    pass


class SensorEntityDescription(_Subscriptable):
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class CoordinatorEntity(_Subscriptable):
    def __init__(self, coordinator, *args, **kwargs):
        self.coordinator = coordinator


class DataUpdateCoordinator(_Subscriptable):
    def __init__(self, hass, logger=None, *, name=None, update_interval=None):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None
        self.last_update_success = True

    def async_set_updated_data(self, data):
        self.data = data

    async def async_config_entry_first_refresh(self):
        return None

    async def async_shutdown(self):
        return None


class BleakClient:
    def __init__(self, *args, **kwargs):
        self.is_connected = False

    async def connect(self):
        self.is_connected = True


class BleakScanner:
    def __init__(self, *args, **kwargs):
        pass


class BleakDeviceNotFoundError(Exception):
    pass


class _Platform:
    SENSOR = "sensor"
    SELECT = "select"
    SWITCH = "switch"


def _mod(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def install_stubs() -> None:
    """Register the stub modules the component imports."""
    ha = _mod("homeassistant")
    components = _mod("homeassistant.components")
    helpers = _mod("homeassistant.helpers")

    _mod(
        "homeassistant.components.bluetooth",
        async_ble_device_from_address=lambda hass, address, connectable=True: None,
        async_scanner_count=lambda hass, connectable=True: 1,
    )
    _mod("homeassistant.components.select", SelectEntity=SelectEntity)
    _mod(
        "homeassistant.components.sensor",
        SensorDeviceClass=_Subscriptable,
        SensorEntity=SensorEntity,
        SensorEntityDescription=SensorEntityDescription,
        SensorStateClass=_Subscriptable,
    )
    _mod("homeassistant.components.switch", SwitchEntity=SwitchEntity)
    _mod("homeassistant.config_entries", ConfigEntry=object)
    _mod(
        "homeassistant.const",
        PERCENTAGE="%",
        UnitOfPower=_Subscriptable,
        Platform=_Platform,
    )
    _mod("homeassistant.core", HomeAssistant=object)
    _mod("homeassistant.exceptions", ConfigEntryNotReady=Exception)
    _mod("homeassistant.helpers.entity", EntityCategory=_Subscriptable)
    _mod("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    _mod(
        "homeassistant.helpers.update_coordinator",
        CoordinatorEntity=CoordinatorEntity,
        DataUpdateCoordinator=DataUpdateCoordinator,
    )

    _mod("bleak", BleakClient=BleakClient, BleakScanner=BleakScanner)
    _mod("bleak.exc", BleakDeviceNotFoundError=BleakDeviceNotFoundError)
    _mod(
        "bleak_retry_connector",
        BleakClientWithServiceCache=BleakClient,
        establish_connection=None,  # patched per test
    )

    # make `from homeassistant.components import bluetooth` work
    ha.components = components
    components.bluetooth = sys.modules["homeassistant.components.bluetooth"]
    helpers.update_coordinator = sys.modules["homeassistant.helpers.update_coordinator"]


install_stubs()


# --------------------------------------------------------------------------
# test doubles
# --------------------------------------------------------------------------
class FakeLoop:
    def __init__(self) -> None:
        self._now = 1_000.0

    def time(self) -> float:
        return self._now


class FakeHass:
    def __init__(self) -> None:
        self.loop = FakeLoop()
        self.data: dict = {}


class FakeEntry:
    entry_id = "test-entry"
    data = {"address": ADDRESS, "name": "Anker F1200"}


class FakeCoordinator:
    """Just the coordinator surface the select entity uses."""

    def __init__(self, fresh: bool = True) -> None:
        self.fresh = fresh
        self.fail = False
        self.rates: list[int] = []

    def is_fresh(self) -> bool:
        return self.fresh

    async def set_charge_rate(self, watts: int) -> None:
        if self.fail:
            raise ConnectionError("monitor is not connected")
        self.rates.append(watts)


class FlakyMonitor:
    """Monitor whose stream crashes once, then yields a packet forever."""

    stale_after = 30.0

    def __init__(self, packet) -> None:
        self.packet = packet
        self.stream_calls = 0
        self.stopped = False

    async def stream(self):
        self.stream_calls += 1
        if self.stream_calls == 1:
            raise RuntimeError("simulated monitor crash")
        while not self.stopped:
            yield self.packet
            await asyncio.sleep(0.01)

    def stop(self) -> None:
        self.stopped = True


# --------------------------------------------------------------------------
# tests: the select must not invent a charge rate
# --------------------------------------------------------------------------
def test_select_starts_without_a_rate() -> None:
    from custom_components.anker_solix_ble.select import ChargeRateSelect

    entity = ChargeRateSelect(FakeCoordinator(), FakeEntry())
    assert entity.current_option is None, (
        "charge rate must be unknown until a write succeeds, not defaulted "
        "to 100 (the unit has no rate readback; the fake value made "
        "automations treat never-sent rates as verified)"
    )
    assert entity.extra_state_attributes == {}
    assert entity.available is True


def test_select_reports_only_written_rates() -> None:
    from custom_components.anker_solix_ble.select import ChargeRateSelect

    coordinator = FakeCoordinator()
    entity = ChargeRateSelect(coordinator, FakeEntry())

    asyncio.run(entity.async_select_option("100"))
    assert entity.current_option == "100"
    assert coordinator.rates == [100]
    assert "last_write" in entity.extra_state_attributes

    coordinator.fail = True
    try:
        asyncio.run(entity.async_select_option("700"))
    except ConnectionError:
        pass
    else:
        raise AssertionError("a failed write must raise, not silently pass")
    assert entity.current_option == "100", "failed write changed the state"
    assert coordinator.rates == [100]


def test_select_unavailable_without_fresh_telemetry() -> None:
    from custom_components.anker_solix_ble.select import ChargeRateSelect

    entity = ChargeRateSelect(FakeCoordinator(fresh=False), FakeEntry())
    assert entity.available is False


# --------------------------------------------------------------------------
# tests: standby unit resolution + supervised stream
# --------------------------------------------------------------------------
def test_coordinator_resolves_standby_unit_through_bluez() -> None:
    from custom_components.anker_solix_ble import coordinator as coord_mod

    coordinator = coord_mod.AnkerDataUpdateCoordinator(FakeHass(), FakeEntry())
    bluez_device = object()
    seen: dict = {}

    def ha_lookup(hass, address, connectable=True):
        seen["ha_lookup"] = address
        return None  # standby unit: not advertising, unknown to HA

    async def bluez_lookup(address):
        seen["bluez_lookup"] = address
        return bluez_device

    async def establish(client_class, device, name):
        seen["device"] = device
        return "connected-client"

    original = (
        coord_mod.bluetooth.async_ble_device_from_address,
        coord_mod.bluez_device_from_address,
        coord_mod.establish_connection,
    )
    coord_mod.bluetooth.async_ble_device_from_address = ha_lookup
    coord_mod.bluez_device_from_address = bluez_lookup
    coord_mod.establish_connection = establish
    try:
        client = asyncio.run(coordinator._get_client())
    finally:
        (
            coord_mod.bluetooth.async_ble_device_from_address,
            coord_mod.bluez_device_from_address,
            coord_mod.establish_connection,
        ) = original

    assert client == "connected-client"
    assert seen["ha_lookup"] == ADDRESS
    assert seen["bluez_lookup"] == ADDRESS
    assert seen["device"] is bluez_device, (
        "the connection must be established with the device resolved from "
        "BlueZ when HA's registry has no entry"
    )


def test_coordinator_gives_up_when_nobody_knows_the_device() -> None:
    from custom_components.anker_solix_ble import coordinator as coord_mod

    coordinator = coord_mod.AnkerDataUpdateCoordinator(FakeHass(), FakeEntry())
    original = (coord_mod.bluez_device_from_address, coord_mod.establish_connection)

    async def bluez_lookup(address):
        return None

    async def establish(client_class, device, name):  # pragma: no cover
        raise AssertionError("must not connect without a device")

    coord_mod.bluez_device_from_address = bluez_lookup
    coord_mod.establish_connection = establish
    try:
        client = asyncio.run(coordinator._get_client())
    finally:
        coord_mod.bluez_device_from_address, coord_mod.establish_connection = original

    assert client is None, "must retry later, not crash"


def test_coordinator_supervises_the_monitor_stream() -> None:
    from anker_ble import Telemetry
    from custom_components.anker_solix_ble.coordinator import AnkerDataUpdateCoordinator

    packet = Telemetry(
        ac_output_w=0,
        total_output_w=295,
        ac_input_w=420,
        dc_input_w=0,
        soc=50,
        serial="TEST",
        checksum_ok=True,
        raw=b"",
    )

    async def scenario() -> None:
        coordinator = AnkerDataUpdateCoordinator(FakeHass(), FakeEntry())
        coordinator._restart_delay = 0.01  # don't wait 30 s in a test
        monitor = FlakyMonitor(packet)
        coordinator._monitor = monitor

        await coordinator.async_start()
        await asyncio.sleep(0.2)
        assert monitor.stream_calls >= 2, (
            "a crashed monitor stream was not restarted: the integration "
            "would stay frozen until the next HA restart"
        )
        assert coordinator.data is packet, "no telemetry after the restart"
        assert coordinator.is_fresh() is True
        await coordinator.async_shutdown()
        assert monitor.stopped is True

        await asyncio.sleep(0.05)
        calls_at_shutdown = monitor.stream_calls
        await asyncio.sleep(0.05)
        assert monitor.stream_calls == calls_at_shutdown, (
            "the stream restarted after shutdown"
        )

    asyncio.run(scenario())


if __name__ == "__main__":
    test_select_starts_without_a_rate()
    print("select starts without a rate: ok")
    test_select_reports_only_written_rates()
    print("select reports only written rates: ok")
    test_select_unavailable_without_fresh_telemetry()
    print("select unavailable without fresh telemetry: ok")
    test_coordinator_resolves_standby_unit_through_bluez()
    print("standby unit resolved through BlueZ: ok")
    test_coordinator_gives_up_when_nobody_knows_the_device()
    print("unknown device retries instead of crashing: ok")
    test_coordinator_supervises_the_monitor_stream()
    print("monitor stream supervised: ok")
    print("HA BEHAVIOUR TESTS PASSED")
