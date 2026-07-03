import os
import shutil
import subprocess
import sys

from .errors import AdbError


def _find_adb():
    adb = shutil.which("adb")
    if adb:
        return adb
    android_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if android_home:
        suffix = ".exe" if sys.platform == "win32" else ""
        candidate = os.path.join(android_home, "platform-tools", f"adb{suffix}")
        if os.path.isfile(candidate):
            return candidate
    return "adb"


_ADB = _find_adb()


def run_adb(command_list, serial=None):
    command = [_ADB]
    if serial:
        command.extend(["-s", serial])
    command.extend(command_list)

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        return result.stdout
    except FileNotFoundError as exc:
        raise AdbError(
            "ADB was not found. Install Android platform-tools or add adb to PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        details = "\n".join(
            part for part in (exc.stderr.strip(), exc.stdout.strip()) if part
        )
        if not details:
            details = f"command failed: {' '.join(command)}"
        raise AdbError(details) from exc


def get_connected_device_states():
    """Return ADB serials mapped to connection states."""
    output = run_adb(["devices"])
    devices = {}

    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            devices[parts[0]] = parts[1]

    return devices


def connect_wifi_device(serial):
    print(f"[*] Connecting to Wi-Fi device {serial}...")
    output = run_adb(["connect", serial]).strip()
    if output:
        print(f"[*] adb connect: {output}")
    return output


def pair_wifi_device(ip, port, pairing_code):
    endpoint = f"{ip}:{port}"
    print(f"[*] Pairing Wi-Fi device {endpoint}...")
    output = run_adb(["pair", endpoint, str(pairing_code).strip()]).strip()
    if output:
        print(f"[*] adb pair: {output}")
    return output


def ensure_device_ready(serial):
    connect_wifi_device(serial)
    states = get_connected_device_states()
    state = states.get(serial)
    if state == "device":
        return

    if state:
        raise AdbError(
            f"device {serial} is {state}. Check authorization on the phone."
        )
    raise AdbError(f"device {serial} is not visible in adb devices.")
