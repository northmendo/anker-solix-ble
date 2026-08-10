"""Validate HA integration wiring against the protocol library.

Catches the class of bug where a sensor key does not match a Telemetry
field (e.g. 'battery_soc' vs 'soc'), which in HA manifests as an entity
stuck unavailable while the data is flowing fine. Also guards against
drift between the vendored lib copy and the top-level library.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from anker_ble import Telemetry  # noqa: E402

SENSOR_FILE = ROOT / "custom_components" / "anker_solix_ble" / "sensor.py"


def sensor_keys() -> list[str]:
    """Extract the key=... values from SENSORS in sensor.py via AST.

    We can't import sensor.py directly here: it imports homeassistant,
    which is not installed in the protocol test venv. AST extraction keeps
    this test dependency-free while still catching key/field mismatches.
    """
    tree = ast.parse(SENSOR_FILE.read_text())
    keys: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "SensorEntityDescription":
                for kw in node.keywords:
                    if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                        keys.append(kw.value.value)
    return keys


def test_sensor_keys_match_telemetry() -> None:
    """Every sensor key must be a field or property of a Telemetry."""
    # Dataclass fields with no default are not class attributes, so check
    # the dataclass field registry plus any @property on the class.
    valid = set(Telemetry.__dataclass_fields__)
    valid |= {n for n, v in vars(Telemetry).items() if isinstance(v, property)}
    missing = [k for k in sensor_keys() if k not in valid]
    assert not missing, (
        f"sensor keys with no Telemetry field/property: {missing} "
        "(would raise AttributeError in HA and leave the entity unavailable)"
    )
    print(f"sensor keys all resolve on Telemetry: {sensor_keys()}")


def test_vendored_lib_matches_top_level() -> None:
    """The HA component's vendored copy must not drift from anker_ble."""
    top = ROOT / "anker_ble"
    vendored = ROOT / "custom_components" / "anker_solix_ble" / "lib" / "anker_ble"
    drifted = []
    for name in ("protocol.py", "monitor.py", "__init__.py"):
        a = (top / name).read_text()
        b = (vendored / name).read_text()
        if a != b:
            drifted.append(name)
    assert not drifted, (
        f"vendored lib drifted from anker_ble: {drifted} "
        "(run the sync step after editing anker_ble)"
    )
    print("vendored lib identical to anker_ble")


if __name__ == "__main__":
    test_sensor_keys_match_telemetry()
    test_vendored_lib_matches_top_level()
    print("WIRING TESTS PASSED")
