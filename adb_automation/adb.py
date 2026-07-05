import os
import re
import shutil
import subprocess
import sys
import time

from .errors import AdbError

SCREEN_OFF_PATTERNS = (
    re.compile(r"\bmWakefulness=Asleep\b"),
    re.compile(r"\bmInteractive=false\b"),
    re.compile(r"\bDisplay Power:\s*state=OFF\b"),
)
SCREEN_ON_PATTERNS = (
    re.compile(r"\bmWakefulness=Awake\b"),
    re.compile(r"\bmInteractive=true\b"),
    re.compile(r"\bDisplay Power:\s*state=ON\b"),
)
KEYGUARD_SHOWING_PATTERNS = (
    re.compile(r"\bmShowingLockscreen=true\b"),
    re.compile(r"\bmDreamingLockscreen=true\b"),
    re.compile(r"\bisStatusBarKeyguard=true\b"),
    re.compile(r"\bmKeyguardShowing=true\b"),
)
KEYGUARD_HIDDEN_PATTERNS = (
    re.compile(r"\bmShowingLockscreen=false\b"),
    re.compile(r"\bmDreamingLockscreen=false\b"),
    re.compile(r"\bisStatusBarKeyguard=false\b"),
    re.compile(r"\bmKeyguardShowing=false\b"),
)
WM_SIZE_PATTERN = re.compile(r"Physical size:\s*(\d+)x(\d+)")
DEFAULT_SCREEN_SIZE = (1080, 1920)
WAKE_SETTLE_SECONDS = 0.5
UNLOCK_SETTLE_SECONDS = 0.5


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


def _matches_any(output, patterns):
    output = output or ""
    return any(pattern.search(output) for pattern in patterns)


def parse_screen_awake(output):
    if _matches_any(output, SCREEN_OFF_PATTERNS):
        return False
    if _matches_any(output, SCREEN_ON_PATTERNS):
        return True
    return None


def parse_keyguard_showing(output):
    if _matches_any(output, KEYGUARD_SHOWING_PATTERNS):
        return True
    if _matches_any(output, KEYGUARD_HIDDEN_PATTERNS):
        return False
    return None


def parse_screen_size(output):
    match = WM_SIZE_PATTERN.search(output or "")
    if not match:
        return DEFAULT_SCREEN_SIZE
    return int(match.group(1)), int(match.group(2))


def screen_is_awake(serial, run_adb_command=run_adb):
    try:
        output = run_adb_command(["shell", "dumpsys", "power"], serial=serial)
    except AdbError as exc:
        print(f"[WARN] Could not read screen power state: {exc}")
        return None
    return parse_screen_awake(output)


def keyguard_is_showing(serial, run_adb_command=run_adb):
    try:
        output = run_adb_command(["shell", "dumpsys", "window"], serial=serial)
    except AdbError as exc:
        print(f"[WARN] Could not read keyguard state: {exc}")
        return None
    return parse_keyguard_showing(output)


def device_screen_size(serial, run_adb_command=run_adb):
    try:
        output = run_adb_command(["shell", "wm", "size"], serial=serial)
    except AdbError as exc:
        print(f"[WARN] Could not read screen size; using default unlock swipe: {exc}")
        return DEFAULT_SCREEN_SIZE
    return parse_screen_size(output)


def swipe_to_unlock(serial, run_adb_command=run_adb):
    width, height = device_screen_size(serial, run_adb_command=run_adb_command)
    x = width // 2
    start_y = int(height * 0.85)
    end_y = int(height * 0.25)
    run_adb_command(
        [
            "shell",
            "input",
            "swipe",
            str(x),
            str(start_y),
            str(x),
            str(end_y),
            "300",
        ],
        serial=serial,
    )


def wake_and_unlock_device(serial, run_adb_command=run_adb, sleep=time.sleep):
    awake = screen_is_awake(serial, run_adb_command=run_adb_command)
    woke_screen = awake is False

    if woke_screen:
        print(f"[*] Phone screen is off on {serial}; waking it.")
        run_adb_command(
            ["shell", "input", "keyevent", "KEYCODE_WAKEUP"],
            serial=serial,
        )
        sleep(WAKE_SETTLE_SECONDS)
    elif awake is None:
        print(f"[*] Could not determine screen state on {serial}; sending wakeup.")
        run_adb_command(
            ["shell", "input", "keyevent", "KEYCODE_WAKEUP"],
            serial=serial,
        )
        sleep(WAKE_SETTLE_SECONDS)

    keyguard_showing = keyguard_is_showing(serial, run_adb_command=run_adb_command)
    if woke_screen or keyguard_showing is True:
        print(f"[*] Unlocking {serial}.")
        swipe_to_unlock(serial, run_adb_command=run_adb_command)
        sleep(UNLOCK_SETTLE_SECONDS)


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
