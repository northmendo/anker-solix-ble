#!/usr/bin/env bash
# purge-bluez-device.sh - remove a device entry from BlueZ's persistent store.
#
# Use this when a device is "stuck": it was seeded (seed-bluez-device.sh) or
# discovered at some point, so bluetoothd keeps a store entry and connect-by-
# address keeps targeting it. Remove the entry, restart bluetoothd, and the
# device is forgotten until it advertises again (or is re-seeded).
#
# Usage (run as root, or with sudo):
#   sudo scripts/purge-bluez-device.sh E8:EE:CC:C7:68:28
#
# Idempotent: safe to re-run; exits 0 even if the device was not present.

set -euo pipefail

MAC="${1:-}"
if [[ -z "$MAC" ]]; then
    echo "usage: $0 <MAC>" >&2
    exit 1
fi
MAC="$(echo "$MAC" | tr '[:lower:]' '[:upper:]')"

ADAPTER_DIR="$(find /var/lib/bluetooth -maxdepth 1 -type d -name '??:??:??:??:??:??' | head -1)"
if [[ -z "$ADAPTER_DIR" ]]; then
    echo "error: no BlueZ adapter storage dir found under /var/lib/bluetooth" >&2
    echo "  (is bluetoothd running? check: systemctl status bluetooth)" >&2
    exit 1
fi

DEV_DIR="$ADAPTER_DIR/$MAC"
CACHE_ENTRY="$ADAPTER_DIR/cache/$MAC"

removed=0
if [[ -d "$DEV_DIR" ]]; then
    rm -rf "$DEV_DIR"
    echo "removed store entry $DEV_DIR"
    removed=1
fi
if [[ -f "$CACHE_ENTRY" ]]; then
    rm -f "$CACHE_ENTRY"
    echo "removed cache entry $CACHE_ENTRY"
    removed=1
fi

# Restart so bluetoothd re-reads the store (it only loads entries at init).
systemctl restart bluetooth
sleep 2

if [[ "$removed" -eq 1 ]]; then
    echo "purged $MAC from BlueZ (adapter $ADAPTER_DIR)"
    if bluetoothctl info "$MAC" >/dev/null 2>&1; then
        echo "warning: $MAC still visible to bluetoothctl" >&2
    else
        echo "OK: $MAC no longer known to BlueZ"
    fi
else
    echo "$MAC was not present in BlueZ store ($ADAPTER_DIR); nothing to do"
fi
