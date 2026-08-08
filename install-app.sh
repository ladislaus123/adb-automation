#!/usr/bin/env bash
# =============================================================================
# install-app.sh
# Installs the notification-listener-app APK onto a device already registered
# in adb-automation (see: python -m adb_automation devices list).
#
# Usage:
#   ./install-app.sh --device=32
#   ./install-app.sh --device my-phone --apk path/to/app-debug.apk
# =============================================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APK_PATH="$SCRIPT_DIR/notification-listener-app/app/build/outputs/apk/debug/app-debug.apk"
DEVICE=""

usage() {
  cat >&2 <<EOF
Usage: $0 --device=<id|name> [--apk=<path>]

  --device   Device id or name registered in adb-automation
             (list them with: python -m adb_automation devices list)
  --apk      Path to the APK to install
             (default: notification-listener-app/app/build/outputs/apk/debug/app-debug.apk)
EOF
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --device=*) DEVICE="${1#*=}"; shift ;;
    --device) DEVICE="${2:-}"; shift 2 ;;
    --apk=*) APK_PATH="${1#*=}"; shift ;;
    --apk) APK_PATH="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "[-] Unknown argument: $1" >&2; usage ;;
  esac
done

if [ -z "$DEVICE" ]; then
  echo "[-] --device is required." >&2
  usage
fi

if [ ! -f "$APK_PATH" ]; then
  echo "[-] APK not found at: $APK_PATH" >&2
  echo "    Build it first: (cd notification-listener-app && ./gradlew assembleDebug)" >&2
  exit 1
fi

echo "[*] Resolving ADB serial for device '$DEVICE'..."
SERIAL="$(cd "$SCRIPT_DIR" && python - "$DEVICE" <<'PY'
import sys

from adb_automation.db import init_database, open_database
from adb_automation.devices import device_serial, find_device

conn = open_database()
try:
    init_database(conn)
    device = find_device(conn, sys.argv[1])
    if not device:
        sys.exit(1)
    sys.stdout.write(device_serial(device))
finally:
    conn.close()
PY
)"
STATUS=$?

if [ $STATUS -ne 0 ] || [ -z "$SERIAL" ]; then
  echo "[-] No registered device matches '$DEVICE'." >&2
  echo "    Check: python -m adb_automation devices list" >&2
  exit 1
fi

echo "[*] Resolved to $SERIAL"

if [[ "$SERIAL" == *:* ]]; then
  echo "[*] Wi-Fi device detected — connecting..."
  adb connect "$SERIAL"
fi

echo "[*] Installing $(basename "$APK_PATH") to $SERIAL..."
if ! adb -s "$SERIAL" install -r "$APK_PATH"; then
  echo "[-] adb install failed." >&2
  exit 1
fi

echo "[+] Installed. On the phone, open 'Notif Listener' and:"
echo "    1. Enter the server URL and the ADB_AUTOMATION_API_KEY value, then Save"
echo "    2. Tap 'Grant notification access' and enable it in system settings"
