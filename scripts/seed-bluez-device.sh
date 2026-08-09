#!/usr/bin/env bash
# seed-bluez-device.sh - make BlueZ aware of an Anker power station that is
# currently in standby and NOT advertising.
#
# Why this is needed (Linux/BlueZ only; phones do not need it):
#   The 757/F1200 in standby keeps its radio in a low-duty listen window:
#   it does NOT advertise, but it WILL answer a directed connection request
#   by address. Android/iOS stacks allow that directly. BlueZ, however,
#   refuses to connect to an address it has no device entry for ("Device
#   ... not available"). It keeps persistent entries in
#   /var/lib/bluetooth/<adapter>/<MAC>/info (no "devices" subdir), but only
#   writes them for devices it has actually seen advertising, and drops
#   unbonded ones when they disappear.
#
#   This script creates the entry manually (device name, LE, public address
#   type, trusted) so `bluetoothctl connect <MAC>` and bleak connect-by-
#   address issue a real directed LE connection, which succeeds once the
#   unit's radio is in its listen window.
#
# Usage (run as root, or with sudo):
#   sudo scripts/seed-bluez-device.sh E8:EE:CC:00:00:01 [NAME]
#
# Idempotent: safe to re-run after BlueZ restarts, reboots, or upgrades.

set -euo pipefail

MAC="${1:-}"
NAME="${2:-757_PowerHouse}"

if [[ -z "$MAC" ]]; then
    echo "usage: $0 <MAC> [NAME]" >&2
    exit 1
fi

# Normalize to uppercase, colon-separated.
MAC="$(echo "$MAC" | tr '[:lower:]' '[:upper:]')"

# Find the adapter storage directory (first BT adapter, e.g. hci0).
ADAPTER_DIR="$(find /var/lib/bluetooth -maxdepth 1 -type d -name '??:??:??:??:??:??' | head -1)"
if [[ -z "$ADAPTER_DIR" ]]; then
    echo "error: no BlueZ adapter storage dir found under /var/lib/bluetooth" >&2
    echo "  (is bluetoothd running? check: systemctl status bluetooth)" >&2
    exit 1
fi

DEV_DIR="$ADAPTER_DIR/$MAC"
INFO="$DEV_DIR/info"

mkdir -p "$DEV_DIR"
cat > "$INFO" <<EOF
[General]
Name=$NAME
Class=0x000000
SupportedTechnologies=LE
AddressType=public
Trusted=true
Blocked=false
EOF

# Restart bluetoothd so it re-reads the device store. (Restarting the
# service is required: BlueZ only loads devices/ entries at adapter init.)
systemctl restart bluetooth
sleep 2

echo "seeded $MAC as known LE device in $DEV_DIR"
if bluetoothctl info "$MAC" >/dev/null 2>&1; then
    echo "OK: bluetoothctl now knows $MAC (connect-by-address will work)"
else
    echo "warning: device not visible to bluetoothctl yet; check bluetoothd" >&2
    exit 1
fi
