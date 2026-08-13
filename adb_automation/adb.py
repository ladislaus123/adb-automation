import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager

from .devices import ADB_TRANSPORT_USB, ADB_TRANSPORT_WIFI, normalize_adb_transport
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
ROTATION_SETTINGS = ("accelerometer_rotation", "user_rotation")
PORTRAIT_USER_ROTATION = "0"
LANDSCAPE_ROTATIONS = (1, 3)
DISPLAY_ROTATION_PATTERNS = (
    re.compile(r"SurfaceOrientation:\s*(\d)"),
    re.compile(r"mRotation=(\d)\b"),
    re.compile(r"mRotation=ROTATION_(\d+)\b"),
)
ROTATION_DEGREES_TO_INDEX = {0: 0, 90: 1, 180: 2, 270: 3}
ENSURE_PORTRAIT_ATTEMPTS = 3
ENSURE_PORTRAIT_RETRY_DELAY_SECONDS = 0.6


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
            encoding="utf-8",
            errors="replace",
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


def require_visible_device(serial):
    states = get_connected_device_states()
    state = states.get(serial)
    if state == "device":
        return states

    if state:
        raise AdbError(
            f"device {serial} is {state}. Check authorization on the phone."
        )
    raise AdbError(f"device {serial} is not visible in adb devices.")


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


def parse_display_rotation(output):
    output = output or ""
    for pattern in DISPLAY_ROTATION_PATTERNS:
        match = pattern.search(output)
        if not match:
            continue
        value = int(match.group(1))
        if pattern is DISPLAY_ROTATION_PATTERNS[-1]:
            return ROTATION_DEGREES_TO_INDEX.get(value)
        return value
    return None


def read_rotation_settings(serial, run_adb_command=run_adb):
    settings = {}
    for name in ROTATION_SETTINGS:
        output = run_adb_command(
            ["shell", "settings", "get", "system", name],
            serial=serial,
        )
        settings[name] = output.strip()
    return settings


def force_portrait_orientation(serial, run_adb_command=run_adb):
    run_adb_command(
        ["shell", "settings", "put", "system", "accelerometer_rotation", "0"],
        serial=serial,
    )
    run_adb_command(
        [
            "shell",
            "settings",
            "put",
            "system",
            "user_rotation",
            PORTRAIT_USER_ROTATION,
        ],
        serial=serial,
    )


def restore_rotation_settings(serial, settings, run_adb_command=run_adb):
    for name, value in settings.items():
        if value == "":
            continue
        run_adb_command(
            ["shell", "settings", "put", "system", name, value],
            serial=serial,
        )


def set_ignore_orientation_request(serial, ignore, run_adb_command=run_adb):
    run_adb_command(
        [
            "shell",
            "cmd",
            "window",
            "set-ignore-orientation-request",
            "true" if ignore else "false",
        ],
        serial=serial,
    )


def set_fix_to_user_rotation(serial, enabled, run_adb_command=run_adb):
    """Force the display to stay at the user-locked rotation.

    The `cmd window` subcommand for this was renamed from
    `set-fix-to-user-rotation` to `fixed-to-user-rotation` in newer Android
    releases (observed on Android 16). Try the modern name first and fall back
    to the legacy one so this keeps working on older Android/OEM builds too.
    """
    value = "enabled" if enabled else "disabled"
    try:
        run_adb_command(
            ["shell", "cmd", "window", "fixed-to-user-rotation", value],
            serial=serial,
        )
    except AdbError as exc:
        if "Unknown command" not in str(exc):
            raise
        run_adb_command(
            ["shell", "cmd", "window", "set-fix-to-user-rotation", value],
            serial=serial,
        )


def read_display_rotation(serial, run_adb_command=run_adb):
    output = run_adb_command(["shell", "dumpsys", "input"], serial=serial)
    rotation = parse_display_rotation(output)
    if rotation is not None:
        return rotation

    output = run_adb_command(["shell", "dumpsys", "window"], serial=serial)
    return parse_display_rotation(output)


def ensure_portrait_orientation(
    serial,
    run_adb_command=run_adb,
    attempts=ENSURE_PORTRAIT_ATTEMPTS,
    delay=ENSURE_PORTRAIT_RETRY_DELAY_SECONDS,
    sleep=time.sleep,
):
    """Force portrait and verify it actually took effect.

    A landscape reading triggers a retry; an unreadable rotation does not,
    since dumpsys output formats vary too much across OEMs/Android versions
    to treat "couldn't parse it" as "it's landscape" without risking pointless
    retries (and sleeps) on every send.
    """
    for attempt in range(attempts):
        try:
            force_portrait_orientation(serial, run_adb_command=run_adb_command)
        except AdbError as exc:
            print(f"[WARN] Could not force portrait orientation: {exc}")

        try:
            set_ignore_orientation_request(
                serial, True, run_adb_command=run_adb_command
            )
        except AdbError as exc:
            print(
                "[WARN] Could not force WindowManager to ignore app orientation "
                f"requests: {exc}"
            )

        try:
            set_fix_to_user_rotation(serial, True, run_adb_command=run_adb_command)
        except AdbError as exc:
            print(f"[WARN] Could not fix WindowManager to the user rotation: {exc}")

        try:
            rotation = read_display_rotation(serial, run_adb_command=run_adb_command)
        except AdbError as exc:
            print(f"[WARN] Could not read display rotation: {exc}")
            rotation = None

        if rotation is None or rotation not in LANDSCAPE_ROTATIONS:
            return

        if attempt < attempts - 1:
            sleep(delay)

    print(
        "[WARN] Device is still reporting a landscape rotation after "
        f"{attempts} attempts to force portrait."
    )


@contextmanager
def portrait_orientation_guard(serial, run_adb_command=run_adb):
    original_settings = None
    try:
        original_settings = read_rotation_settings(
            serial,
            run_adb_command=run_adb_command,
        )
    except AdbError as exc:
        print(f"[WARN] Could not read rotation settings: {exc}")

    ensure_portrait_orientation(serial, run_adb_command=run_adb_command)

    try:
        yield
    finally:
        if original_settings is not None:
            try:
                restore_rotation_settings(
                    serial,
                    original_settings,
                    run_adb_command=run_adb_command,
                )
            except AdbError as exc:
                print(f"[WARN] Could not restore rotation settings: {exc}")

        try:
            set_ignore_orientation_request(
                serial, False, run_adb_command=run_adb_command
            )
        except AdbError as exc:
            print(
                "[WARN] Could not restore WindowManager orientation-request "
                f"handling: {exc}"
            )

        try:
            set_fix_to_user_rotation(serial, False, run_adb_command=run_adb_command)
        except AdbError as exc:
            print(
                "[WARN] Could not restore WindowManager fix-to-user-rotation "
                f"handling: {exc}"
            )


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


def ensure_device_ready(serial, adb_transport=ADB_TRANSPORT_WIFI):
    transport = normalize_adb_transport(adb_transport)
    if transport == ADB_TRANSPORT_WIFI:
        connect_wifi_device(serial)
    elif transport != ADB_TRANSPORT_USB:
        raise AdbError(f"unsupported adb transport: {adb_transport}")

    require_visible_device(serial)
