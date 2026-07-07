import random
import re
import time

from .adb import run_adb
from .appium_media import appium_server_url, prepare_appium_session, start_appium_driver
from .config import WHATSAPP_BUSINESS_PACKAGE, WHATSAPP_MESSENGER_PACKAGE
from .errors import AutomationError

WHATSAPP_PACKAGES_TO_CLOSE = (
    WHATSAPP_MESSENGER_PACKAGE,
    WHATSAPP_BUSINESS_PACKAGE,
)
AUTOMATION_PACKAGES = (
    "io.appium",
    "io.appium.uiautomator2.server",
    "io.appium.uiautomator2.server.test",
    "com.github.uiautomator",
    "com.github.uiautomator.test",
)
EXCLUDED_PACKAGE_PREFIXES = (
    "android",
    "com.android.",
    "com.google.android.",
    "com.samsung.android.",
    "com.sec.android.",
    "com.miui.",
    "com.huawei.",
    "com.coloros.",
    "com.oplus.",
    "com.motorola.",
)
PACKAGE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")
ACTIVITY_PACKAGE_PATTERNS = (
    re.compile(r"\bpackageName=([A-Za-z0-9_.$]+)"),
    re.compile(r"\bcmp=([A-Za-z0-9_.$]+)/"),
    re.compile(r"\s([A-Za-z0-9_.$]+)/[A-Za-z0-9_.$]+"),
)
WAIT_AFTER_HOME_SECONDS = 4.0
WAIT_AFTER_APP_OPEN_SECONDS = 15.0
WAIT_AFTER_APP_CLOSE_SECONDS = 3.0
WAIT_AFTER_SCREEN_OFF_SECONDS = 8.0
WAIT_AFTER_WAKE_SECONDS = 4.0


def run_best_effort_adb(command, serial, run_adb_command=run_adb):
    try:
        return run_adb_command(command, serial=serial)
    except AutomationError as exc:
        print(f"[WARN] Ignoring non-critical stochastic ADB failure: {exc}")
        return ""


def shell_result_output(result):
    if isinstance(result, dict):
        for key in ("stdout", "output", "value"):
            if result.get(key) is not None:
                return str(result[key])
        return ""
    if result is None:
        return ""
    return str(result)


def appium_shell(driver, command, args):
    return shell_result_output(
        driver.execute_script(
            "mobile: shell",
            {
                "command": command,
                "args": list(args),
            },
        )
    )


def inspect_with_appium_or_adb(
    driver,
    serial,
    command,
    args,
    run_adb_command=run_adb,
):
    try:
        return appium_shell(driver, command, args)
    except Exception as exc:
        print(f"[WARN] Appium shell inspection failed; falling back to ADB: {exc}")
        return run_adb_command(["shell", command, *args], serial=serial)


def adb_shell(serial, command, args, run_adb_command=run_adb):
    return run_adb_command(["shell", command, *args], serial=serial)


def parse_pm_list_packages(output):
    packages = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("package:"):
            continue
        package = line.split("package:", 1)[1].strip()
        if PACKAGE_PATTERN.match(package):
            packages.append(package)
    return packages


def parse_query_activities_packages(output):
    packages = []
    seen = set()
    for line in output.splitlines():
        for pattern in ACTIVITY_PACKAGE_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            package = match.group(1)
            if PACKAGE_PATTERN.match(package) and package not in seen:
                packages.append(package)
                seen.add(package)
            break
    return packages


def is_safe_app_package(package):
    if package in WHATSAPP_PACKAGES_TO_CLOSE or package in AUTOMATION_PACKAGES:
        return False
    return not any(
        package == prefix or package.startswith(prefix)
        for prefix in EXCLUDED_PACKAGE_PREFIXES
    )


def discover_launchable_apps_from_outputs(third_party_output, launchable_output):
    third_party = set(parse_pm_list_packages(third_party_output))
    launchable = parse_query_activities_packages(launchable_output)

    if third_party and launchable:
        candidates = [package for package in launchable if package in third_party]
    elif launchable:
        candidates = launchable
    else:
        candidates = sorted(third_party)

    return [package for package in candidates if is_safe_app_package(package)]


def discover_launchable_apps_with_adb(serial, run_adb_command=run_adb):
    third_party_output = adb_shell(
        serial,
        "pm",
        ["list", "packages", "-3"],
        run_adb_command=run_adb_command,
    )

    launchable_output = adb_shell(
        serial,
        "cmd",
        [
            "package",
            "query-activities",
            "-a",
            "android.intent.action.MAIN",
            "-c",
            "android.intent.category.LAUNCHER",
        ],
        run_adb_command=run_adb_command,
    )

    return discover_launchable_apps_from_outputs(third_party_output, launchable_output)


def discover_launchable_apps_with_appium(driver, serial, run_adb_command=run_adb):
    third_party_output = inspect_with_appium_or_adb(
        driver,
        serial,
        "pm",
        ["list", "packages", "-3"],
        run_adb_command=run_adb_command,
    )
    launchable_output = inspect_with_appium_or_adb(
        driver,
        serial,
        "cmd",
        [
            "package",
            "query-activities",
            "-a",
            "android.intent.action.MAIN",
            "-c",
            "android.intent.category.LAUNCHER",
        ],
        run_adb_command=run_adb_command,
    )
    return discover_launchable_apps_from_outputs(third_party_output, launchable_output)


def discover_launchable_apps(driver, serial, run_adb_command=run_adb):
    if driver is None:
        return discover_launchable_apps_with_adb(
            serial,
            run_adb_command=run_adb_command,
        )

    return discover_launchable_apps_with_appium(
        driver,
        serial,
        run_adb_command=run_adb_command,
    )


def start_optional_appium_driver(
    serial,
    driver_factory=start_appium_driver,
    run_adb_command=run_adb,
    sleep=time.sleep,
):
    try:
        prepare_appium_session(serial, run_adb_command=run_adb_command, sleep=sleep)
        return driver_factory(serial, appium_server_url())
    except AutomationError as exc:
        print(f"[WARN] Appium unavailable for stochastic inspection; using ADB: {exc}")
        return None


def choose_random_apps(packages, count=2, rng=random):
    if not packages:
        return []
    unique_packages = list(dict.fromkeys(packages))
    sample_size = min(count, len(unique_packages))
    return rng.sample(unique_packages, sample_size)


def press_home(serial, run_adb_command=run_adb):
    run_best_effort_adb(
        ["shell", "input", "keyevent", "KEYCODE_HOME"],
        serial,
        run_adb_command=run_adb_command,
    )


def force_stop_package(serial, package, run_adb_command=run_adb):
    run_best_effort_adb(
        ["shell", "am", "force-stop", package],
        serial,
        run_adb_command=run_adb_command,
    )


def open_app(serial, package, run_adb_command=run_adb):
    run_adb_command(
        [
            "shell",
            "monkey",
            "-p",
            package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        ],
        serial=serial,
    )


def sleep_and_wake_screen(serial, run_adb_command=run_adb, sleep=time.sleep):
    run_best_effort_adb(
        ["shell", "input", "keyevent", "KEYCODE_SLEEP"],
        serial,
        run_adb_command=run_adb_command,
    )
    sleep(WAIT_AFTER_SCREEN_OFF_SECONDS)
    run_best_effort_adb(
        ["shell", "input", "keyevent", "KEYCODE_WAKEUP"],
        serial,
        run_adb_command=run_adb_command,
    )
    sleep(WAIT_AFTER_WAKE_SECONDS)
    press_home(serial, run_adb_command=run_adb_command)


def run_stochastic_actions(
    serial,
    app_count=2,
    rng=random,
    run_adb_command=run_adb,
    driver_factory=start_appium_driver,
    sleep=time.sleep,
):
    print(f"[*] Running stochastic phone activity on {serial}...")
    for package in WHATSAPP_PACKAGES_TO_CLOSE:
        force_stop_package(serial, package, run_adb_command=run_adb_command)
    press_home(serial, run_adb_command=run_adb_command)
    sleep(WAIT_AFTER_HOME_SECONDS)

    driver = None
    try:
        try:
            candidates = discover_launchable_apps_with_adb(
                serial,
                run_adb_command=run_adb_command,
            )
        except AutomationError as exc:
            print(f"[WARN] ADB app discovery failed: {exc}")
            driver = start_optional_appium_driver(
                serial,
                driver_factory=driver_factory,
                run_adb_command=run_adb_command,
                sleep=sleep,
            )
            if driver is None:
                candidates = []
            else:
                try:
                    candidates = discover_launchable_apps_with_appium(
                        driver,
                        serial,
                        run_adb_command=run_adb_command,
                    )
                except AutomationError as appium_exc:
                    print(f"[WARN] Appium app discovery failed: {appium_exc}")
                    candidates = []
        selected = choose_random_apps(candidates, count=app_count, rng=rng)
        if not selected:
            print("[WARN] No safe launchable apps found for stochastic activity.")

        for package in selected:
            print(f"[*] Opening random app: {package}")
            open_app(serial, package, run_adb_command=run_adb_command)
            sleep(WAIT_AFTER_APP_OPEN_SECONDS)
            force_stop_package(serial, package, run_adb_command=run_adb_command)
            sleep(WAIT_AFTER_APP_CLOSE_SECONDS)
            press_home(serial, run_adb_command=run_adb_command)
            sleep(WAIT_AFTER_HOME_SECONDS)

        sleep_and_wake_screen(serial, run_adb_command=run_adb_command, sleep=sleep)
        print("[+] Stochastic phone activity completed.")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception as exc:
                print(f"[WARN] Could not quit stochastic Appium driver cleanly: {exc}")
