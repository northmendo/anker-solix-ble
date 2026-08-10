"""Assert the HA component's vendored protocol library matches the root one.

The HA component must be self-contained (HA installs custom_components as a
folder; there is no root anker_ble/ on sys.path inside HA), so the library
is copied to custom_components/anker_solix_ble/lib/anker_ble/. This test
fails if the two drift apart, forcing a sync.
"""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB_SRC = ROOT / "anker_ble"
LIB_VENDORED = ROOT / "custom_components" / "anker_solix_ble" / "lib" / "anker_ble"


def _files_hash(directory: Path) -> dict[str, str]:
    out = {}
    for path in sorted(directory.glob("*.py")):
        out[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def test_vendored_lib_sync() -> None:
    assert LIB_SRC.is_dir(), f"missing {LIB_SRC}"
    assert LIB_VENDORED.is_dir(), f"missing {LIB_VENDORED}"
    src = _files_hash(LIB_SRC)
    vendored = _files_hash(LIB_VENDORED)
    assert set(src) == set(vendored), (
        f"file sets differ: only in root={set(src) - set(vendored)}, "
        f"only in vendored={set(vendored) - set(src)}"
    )
    drifted = [name for name in src if src[name] != vendored[name]]
    assert not drifted, (
        f"vendored protocol lib out of sync: {drifted}. "
        "Re-run the vendoring step (copy anker_ble/ into "
        "custom_components/anker_solix_ble/lib/)."
    )
    print("vendored protocol lib in sync with root")


if __name__ == "__main__":
    test_vendored_lib_sync()
    print("ALL TESTS PASSED")
