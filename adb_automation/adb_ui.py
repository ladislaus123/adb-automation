import re
import time
import xml.etree.ElementTree as ET

from .adb import connect_wifi_device, run_adb, wake_and_unlock_device
from .config import (
    APPIUM_RECONNECT_ON_WEDGE_ENV_VAR,
    APPIUM_REBOOT_ON_WEDGE_ENV_VAR,
    APPIUM_SETTLE_SECONDS_ENV_VAR,
    env_bool,
    env_int,
)
from .errors import AdbError, AutomationError

DUMP_REMOTE_PATH = "/sdcard/window_dump.xml"
BOUNDS_PATTERN = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


STALE_CLEAR_SETTLE_SECONDS = 0.3
UIAUTOMATION_SETTLE_SECONDS_DEFAULT = 3
UIAUTOMATION_REBOOT_WAIT_SECONDS = 120
UIAUTOMATION_REBOOT_POLL_SECONDS = 5
# Covers both a stray Appium UiAutomator2 server and an openatx
# python-uiautomator2 agent -- either one left installed can re-register the
# on-device UiAutomation connection the moment it's poked (e.g. by another
# job on the same device), which a plain process kill won't prevent.
UIAUTOMATION_TEST_PACKAGES = (
    "io.appium.uiautomator2.server",
    "io.appium.uiautomator2.server.test",
    "com.github.uiautomator",
    "com.github.uiautomator.test",
)


def is_wifi_adb_transport(adb_transport):
    return str(adb_transport or "wifi").strip().lower() == "wifi"


def uiautomation_settle_seconds():
    return env_int(APPIUM_SETTLE_SECONDS_ENV_VAR, UIAUTOMATION_SETTLE_SECONDS_DEFAULT)


def uninstall_uiautomation_test_packages(serial, run_adb_command=run_adb):
    print("[*] Uninstalling leftover UiAutomator2/uiautomator test packages...")
    for package in UIAUTOMATION_TEST_PACKAGES:
        try:
            run_adb_command(["uninstall", package], serial=serial)
        except AutomationError:
            pass


def reconnect_adb_transport(serial, run_adb_command=run_adb, adb_transport="wifi"):
    """Re-establish the adb transport without touching the cable.

    `adb reconnect` asks adbd to drop and reopen its connection to the host
    over whatever transport is already in use -- USB included -- so it's the
    software equivalent of unplugging and replugging the cable. Wi-Fi devices
    additionally get a plain `adb connect host:port`, since their transport
    can also drop at the TCP layer, which a bare `reconnect` doesn't re-dial.
    """
    try:
        run_adb_command(["reconnect"], serial=serial)
    except AutomationError as exc:
        print(f"[WARN] adb reconnect failed: {exc}")

    if is_wifi_adb_transport(adb_transport):
        try:
            connect_wifi_device(serial)
        except AutomationError as exc:
            print(f"[WARN] Could not re-establish Wi-Fi ADB connection: {exc}")


def reboot_device_and_wait(
    serial,
    run_adb_command=run_adb,
    sleep=time.sleep,
    adb_transport="wifi",
):
    print(
        f"[*] Rebooting {serial} to clear a wedged UiAutomation registration "
        "(last resort)..."
    )
    try:
        run_adb_command(["reboot"], serial=serial)
    except AutomationError as exc:
        print(f"[WARN] adb reboot failed: {exc}")
        return

    attempts = UIAUTOMATION_REBOOT_WAIT_SECONDS // UIAUTOMATION_REBOOT_POLL_SECONDS
    for _ in range(attempts):
        sleep(UIAUTOMATION_REBOOT_POLL_SECONDS)
        if is_wifi_adb_transport(adb_transport):
            try:
                connect_wifi_device(serial)
            except AutomationError:
                continue
        try:
            boot_completed = run_adb_command(
                ["shell", "getprop", "sys.boot_completed"], serial=serial
            )
        except AutomationError:
            continue
        if boot_completed and boot_completed.strip() == "1":
            break
    else:
        print(
            f"[WARN] {serial} did not come back within "
            f"{UIAUTOMATION_REBOOT_WAIT_SECONDS}s after reboot"
        )
        return

    sleep(uiautomation_settle_seconds())
    try:
        wake_and_unlock_device(serial, run_adb_command=run_adb_command, sleep=sleep)
    except AutomationError as exc:
        print(f"[WARN] Could not wake/unlock {serial} after reboot: {exc}")


def build_uiautomation_recovery_ladder():
    """Escalating recovery steps for a wedged on-device UiAutomation slot.

    Level 1 (kill) alone is not reliable on newer Android (observed on API
    36+): force-stopping the client that registered the UiAutomation
    connection can leave the registration stale in system_server even though
    the client process is gone. Each further level is a strictly bigger
    hammer, tried only after the previous one failed to unwedge the device.
    """

    def level_kill(serial, run_adb_command, sleep, adb_transport):
        clear_stale_uiautomation(serial, run_adb_command=run_adb_command)
        sleep(STALE_CLEAR_SETTLE_SECONDS)

    def level_uninstall(serial, run_adb_command, sleep, adb_transport):
        uninstall_uiautomation_test_packages(serial, run_adb_command=run_adb_command)
        sleep(STALE_CLEAR_SETTLE_SECONDS)

    def level_reconnect(serial, run_adb_command, sleep, adb_transport):
        reconnect_adb_transport(
            serial,
            run_adb_command=run_adb_command,
            adb_transport=adb_transport,
        )
        sleep(uiautomation_settle_seconds())

    def level_reboot(serial, run_adb_command, sleep, adb_transport):
        reboot_device_and_wait(
            serial,
            run_adb_command=run_adb_command,
            sleep=sleep,
            adb_transport=adb_transport,
        )

    ladder = [level_kill, level_uninstall]
    if env_bool(APPIUM_RECONNECT_ON_WEDGE_ENV_VAR, True):
        ladder.append(level_reconnect)
    if env_bool(APPIUM_REBOOT_ON_WEDGE_ENV_VAR, False):
        ladder.append(level_reboot)
    return ladder


def dump_ui_xml(serial, run_adb_command=run_adb, sleep=time.sleep, adb_transport="wifi"):
    try:
        run_adb_command(
            ["shell", "uiautomator", "dump", DUMP_REMOTE_PATH], serial=serial
        )
        return run_adb_command(["shell", "cat", DUMP_REMOTE_PATH], serial=serial)
    except AdbError as exc:
        last_error = exc

    # A stale UiAutomation registration (leftover uiautomator2/Appium
    # instrumentation) makes the dump above crash with "already registered"
    # and no output. Escalate through the recovery ladder, retrying the dump
    # after each level, instead of giving up after one quick kill+retry --
    # see build_uiautomation_recovery_ladder() for why a kill alone isn't
    # always enough on newer Android.
    ladder = build_uiautomation_recovery_ladder()
    for level, recover in enumerate(ladder, start=1):
        print(
            f"[WARN] uiautomator dump failed (stale UiAutomation?); "
            f"running recovery level {level}/{len(ladder)}: {last_error}"
        )
        recover(serial, run_adb_command, sleep, adb_transport)
        try:
            run_adb_command(
                ["shell", "uiautomator", "dump", DUMP_REMOTE_PATH], serial=serial
            )
            return run_adb_command(["shell", "cat", DUMP_REMOTE_PATH], serial=serial)
        except AdbError as exc:
            last_error = exc

    raise last_error


def is_stale_uiautomation_error(exc):
    """True for the signature "uiautomator dump" leaves when a leftover

    uiautomator2/Appium instrumentation process already holds the on-device
    UiAutomation registration: the adb command exits non-zero with no
    stdout and no stderr at all, so run_adb() falls back to its generic
    "command failed: ..." message. See clear_stale_uiautomation below.
    """
    return str(exc).startswith("command failed:")


STALE_APP_PROCESS_NAMES = ("app_process", "app_process32", "app_process64")


def clear_stale_uiautomation(serial, run_adb_command=run_adb):
    """Kill any process still holding the on-device UiAutomation connection.

    `uiautomator dump` needs to register its own UiAutomation session; a
    leftover uiautomator2/Appium instrumentation process from an earlier
    session (which can run as a bare `app_process`, not an installed
    package) makes every dump crash with "UiAutomationService ... already
    registered!" and exit non-zero with no output at all.

    `pkill -f uiautomator` only catches the leftover when Android kept the
    `--nice-name=uiautomator` label in its command line. Instrumentation
    processes that never renamed argv0 still show up as the literal name
    `app_process`(32/64) instead, so they're killed by exact name too. Real
    app processes are always renamed off `app_process` by Zygote before they
    run any code, and Zygote itself shows up as `zygote`/`zygote64`, so this
    can't accidentally kill an unrelated app or the Zygote/system server.

    Best-effort: there may be nothing to kill.
    """
    try:
        run_adb_command(["shell", "pkill", "-f", "uiautomator"], serial=serial)
    except AutomationError:
        pass
    for name in STALE_APP_PROCESS_NAMES:
        try:
            run_adb_command(["shell", "pkill", "-9", "-x", name], serial=serial)
        except AutomationError:
            pass


def parse_bounds(bounds):
    match = BOUNDS_PATTERN.match(bounds or "")
    if not match:
        return None
    x1, y1, x2, y2 = (int(value) for value in match.groups())
    return (x1, y1, x2, y2)


def bounds_center(bounds):
    parsed = parse_bounds(bounds)
    if not parsed:
        return None
    x1, y1, x2, y2 = parsed
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def parse_ui_dump(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise AutomationError(f"Could not parse uiautomator dump: {exc}") from exc

    elements = []
    for node in root.iter("node"):
        elements.append(
            {
                "resource_id": node.get("resource-id") or "",
                "text": node.get("text") or "",
                "content_desc": node.get("content-desc") or "",
                "class_name": node.get("class") or "",
                "clickable": node.get("clickable") == "true",
                "bounds": node.get("bounds") or "",
            }
        )
    return elements


def element_matches(element, selector):
    kind, value = selector
    if kind == "id":
        return element["resource_id"] == value
    if kind == "accessibility":
        return element["content_desc"] == value
    if kind == "text":
        return element["text"] == value
    return False


def find_first(elements, selectors):
    for selector in selectors:
        for element in elements:
            if element_matches(element, selector):
                return element
    return None


def tap_point(serial, x, y, run_adb_command=run_adb):
    run_adb_command(
        ["shell", "input", "tap", str(int(x)), str(int(y))],
        serial=serial,
    )


def tap_element(serial, element, run_adb_command=run_adb):
    center = bounds_center(element.get("bounds"))
    if not center:
        raise AutomationError(f"Element has no usable bounds: {element}")
    tap_point(serial, center[0], center[1], run_adb_command=run_adb_command)
    return center


def wait_for_first(
    serial,
    selectors,
    timeout=6,
    interval=0.3,
    run_adb_command=run_adb,
    sleep=time.sleep,
    adb_transport="wifi",
):
    deadline = time.monotonic() + timeout
    while True:
        xml_text = dump_ui_xml(
            serial,
            run_adb_command=run_adb_command,
            sleep=sleep,
            adb_transport=adb_transport,
        )
        elements = parse_ui_dump(xml_text)
        found = find_first(elements, selectors)
        if found is not None:
            return found
        if time.monotonic() >= deadline:
            return None
        sleep(interval)


def click_first(
    serial,
    selectors,
    timeout=6,
    interval=0.3,
    run_adb_command=run_adb,
    sleep=time.sleep,
    adb_transport="wifi",
):
    element = wait_for_first(
        serial,
        selectors,
        timeout=timeout,
        interval=interval,
        run_adb_command=run_adb_command,
        sleep=sleep,
        adb_transport=adb_transport,
    )
    if element is None:
        return False
    tap_element(serial, element, run_adb_command=run_adb_command)
    return True
