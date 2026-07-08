import hashlib
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

from .adb import connect_wifi_device, device_screen_size, run_adb, wake_and_unlock_device
from .config import (
    APPIUM_RECONNECT_ON_WEDGE_ENV_VAR,
    APPIUM_REBOOT_ON_WEDGE_ENV_VAR,
    APPIUM_SERVER_ENV_VAR,
    APPIUM_SETTLE_SECONDS_ENV_VAR,
    DEFAULT_APPIUM_SERVER,
    STREAM_EXTRA,
    env_bool,
    env_int,
)
from .errors import AutomationError

DEVICE_CAMERA_DIR = "/sdcard/DCIM/Camera"
WAIT_AFTER_PUSH = 2
MEDIA_INDEX_TIMEOUT_SECONDS = 15
MEDIA_INDEX_POLL_INTERVAL_SECONDS = 1
MEDIA_INDEX_RESCAN_EVERY_ATTEMPTS = 3
WAIT_AFTER_CHAT_OPEN = 4
WAIT_AFTER_ATTACH = 1.5
WAIT_AFTER_SELECT_MEDIA = 2
WAIT_AFTER_SEND = 2
APPIUM_NEW_COMMAND_TIMEOUT = 300
APPIUM_PRE_SESSION_WAIT_SECONDS = 2
APPIUM_POST_QUIT_WAIT_SECONDS = 1
APPIUM_SYSTEM_PORT_BASE = 8200
APPIUM_SYSTEM_PORT_SPAN = 1000
APPIUM_DEFAULT_SETTLE_SECONDS = 3
APPIUM_REBOOT_WAIT_SECONDS = 120
APPIUM_REBOOT_POLL_SECONDS = 5
DIRECT_MEDIA_PREVIEW_WAIT_SECONDS = 3.5
DIRECT_SEND_TAP_X_RATIO = 0.90
DIRECT_SEND_TAP_Y_RATIO = 0.92
U2_UIAUTOMATOR_PACKAGES = (
    "com.github.uiautomator",
    "com.github.uiautomator.test",
)
APPIUM_SERVER_PACKAGES = (
    "io.appium.uiautomator2.server",
    "io.appium.uiautomator2.server.test",
)
APPIUM_RECOVERABLE_START_MARKERS = (
    "uiautomation not connected",
    "sessionnotcreatedexception",
    "a new session could not be created",
    "instrumentation process is not running",
    "cannot start the 'io.appium.uiautomator2.server'",
)

SELECTOR_BY = {
    "id": "id",
    "accessibility": "accessibility id",
    "xpath": "xpath",
}


def appium_server_url():
    return os.environ.get(APPIUM_SERVER_ENV_VAR, DEFAULT_APPIUM_SERVER)


def appium_system_port_for_serial(serial):
    digest = hashlib.sha256(str(serial).encode("utf-8")).hexdigest()
    offset = int(digest[:8], 16) % APPIUM_SYSTEM_PORT_SPAN
    return APPIUM_SYSTEM_PORT_BASE + offset


def is_image_mime(mime_type):
    return bool(mime_type and mime_type.startswith("image/"))


def is_video_mime(mime_type):
    return bool(mime_type and mime_type.startswith("video/"))


def is_audio_mime(mime_type):
    return bool(mime_type and mime_type.startswith("audio/"))


def remote_media_prefix(mime_type):
    if is_video_mime(mime_type):
        return "VID"
    if is_audio_mime(mime_type):
        return "AUD"
    if is_image_mime(mime_type):
        return "IMG"
    return "MEDIA"


def image_output_suffix(src_path):
    suffix = Path(src_path).suffix.lower()
    if suffix in (".jpg", ".jpeg", ".png", ".webp"):
        return suffix
    return ".jpg"


def image_save_format(suffix):
    if suffix in (".jpg", ".jpeg"):
        return "JPEG"
    if suffix == ".png":
        return "PNG"
    if suffix == ".webp":
        return "WEBP"
    return "JPEG"


def make_fresh_image_without_exif(src_path):
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(f"Local image not found: {src_path}")

    try:
        from PIL import Image
    except ImportError as exc:
        raise AutomationError(
            "Pillow is required to prepare image media for WhatsApp. "
            "Install it with: pip install Pillow"
        ) from exc

    suffix = image_output_suffix(src)
    output = tempfile.NamedTemporaryFile(
        delete=False,
        prefix="adb_automation_media_",
        suffix=suffix,
    )
    output_path = output.name
    output.close()

    try:
        with Image.open(src) as image:
            save_format = image_save_format(suffix)
            if save_format == "JPEG":
                image = image.convert("RGB")
                image.save(output_path, save_format, quality=95)
            else:
                image.save(output_path, save_format)
    except Exception as exc:
        remove_file_if_exists(output_path)
        raise AutomationError(f"Could not prepare image media for WhatsApp: {exc}") from exc

    print(f"[MEDIA] Created fresh no-EXIF image: {output_path}")
    return output_path


def remove_file_if_exists(path):
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        print(f"[WARN] Could not remove temporary media file {path}: {exc}")


def run_best_effort_adb(command, serial, run_adb_command=run_adb):
    try:
        return run_adb_command(command, serial=serial)
    except AutomationError as exc:
        print(f"[WARN] Ignoring non-critical ADB failure: {exc}")
        return None


def cleanup_staged_media(serial, remote_path, run_adb_command=run_adb):
    if not remote_path:
        return

    print(f"[*] Cleaning staged media from device: {remote_path}")
    run_best_effort_adb(
        ["shell", "rm", "-f", remote_path],
        serial,
        run_adb_command=run_adb_command,
    )
    run_best_effort_adb(
        [
            "shell",
            "am",
            "broadcast",
            "-a",
            "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
            "-d",
            f"file://{remote_path}",
        ],
        serial,
        run_adb_command=run_adb_command,
    )


def broadcast_media_scan(serial, remote_path, run_adb_command=run_adb):
    run_best_effort_adb(
        [
            "shell",
            "am",
            "broadcast",
            "-a",
            "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
            "-d",
            f"file://{remote_path}",
        ],
        serial,
        run_adb_command=run_adb_command,
    )


def media_is_indexed(serial, remote_path, run_adb_command=run_adb):
    # Match on the (unique, timestamped) display name rather than _data:
    # MediaStore stores the canonical /storage/emulated/0/... path while we
    # push via the /sdcard/... symlink, so a _data match would spuriously fail.
    filename = Path(remote_path).name
    try:
        output = run_adb_command(
            [
                "shell",
                "content",
                "query",
                "--uri",
                "content://media/external/file",
                "--projection",
                "_id:_display_name",
                "--where",
                f"_display_name='{filename}'",
            ],
            serial=serial,
        )
    except Exception as exc:
        print(f"[WARN] MediaStore index query failed: {exc}")
        return False

    text = str(output or "")
    return "_id=" in text or text.strip().startswith("Row:")


def wait_for_media_indexed(
    serial,
    remote_path,
    run_adb_command=run_adb,
    sleep=time.sleep,
    timeout=MEDIA_INDEX_TIMEOUT_SECONDS,
    interval=MEDIA_INDEX_POLL_INTERVAL_SECONDS,
    rescan_every=MEDIA_INDEX_RESCAN_EVERY_ATTEMPTS,
):
    attempts = max(1, int(timeout / interval))
    for attempt in range(attempts):
        if media_is_indexed(serial, remote_path, run_adb_command=run_adb_command):
            return True
        if rescan_every and attempt and attempt % rescan_every == 0:
            broadcast_media_scan(serial, remote_path, run_adb_command=run_adb_command)
        sleep(interval)

    print(
        f"[WARN] Media not confirmed in the gallery index after {timeout}s: {remote_path}"
    )
    return False


def build_remote_media_path(local_path, mime_type, now):
    suffix = Path(local_path).suffix or ".bin"
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    prefix = remote_media_prefix(mime_type)
    return f"{DEVICE_CAMERA_DIR}/{prefix}_{timestamp}{suffix}"


def stage_latest_media(
    serial,
    file_path,
    mime_type,
    run_adb_command=run_adb,
    now_provider=datetime.now,
    fresh_image_factory=make_fresh_image_without_exif,
    remove_local_file=remove_file_if_exists,
    wait_after_push=WAIT_AFTER_PUSH,
    sleep=time.sleep,
    index_timeout=MEDIA_INDEX_TIMEOUT_SECONDS,
    index_interval=MEDIA_INDEX_POLL_INTERVAL_SECONDS,
):
    if not os.path.exists(file_path):
        raise ValueError(f"media file not found: {file_path}")

    local_to_push = file_path
    temporary_media = None

    if is_image_mime(mime_type):
        temporary_media = fresh_image_factory(file_path)
        local_to_push = temporary_media

    try:
        now = now_provider()
        remote_path = build_remote_media_path(local_to_push, mime_type, now)
        print(f"[*] Pushing media to device camera roll: {remote_path}")
        run_adb_command(["push", local_to_push, remote_path], serial=serial)

        touch_timestamp = now_provider().strftime("%Y%m%d%H%M.%S")
        run_best_effort_adb(
            ["shell", "toybox", "touch", "-t", touch_timestamp, remote_path],
            serial,
            run_adb_command=run_adb_command,
        )
        broadcast_media_scan(serial, remote_path, run_adb_command=run_adb_command)

        sleep(wait_after_push)
        if wait_for_media_indexed(
            serial,
            remote_path,
            run_adb_command=run_adb_command,
            sleep=sleep,
            timeout=index_timeout,
            interval=index_interval,
        ):
            print(f"[OK] Media indexed in gallery: {remote_path}")
        else:
            print("[WARN] Proceeding without confirmed gallery index.")
        return remote_path
    finally:
        if temporary_media:
            remove_local_file(temporary_media)


def open_whatsapp_chat(
    serial,
    phone,
    whatsapp_package,
    run_adb_command=run_adb,
    wait_after_open=WAIT_AFTER_CHAT_OPEN,
):
    run_adb_command(
        [
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            f"https://wa.me/{phone}",
            "-p",
            whatsapp_package,
        ],
        serial=serial,
    )
    time.sleep(wait_after_open)


def start_appium_driver(serial, server_url=None):
    try:
        from appium import webdriver
        from appium.options.android import UiAutomator2Options
    except ImportError as exc:
        raise AutomationError(
            "Appium-Python-Client is required to send media through Appium. "
            "Install it with: pip install Appium-Python-Client"
        ) from exc

    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.automation_name = "UiAutomator2"
    options.udid = serial
    options.no_reset = True
    options.new_command_timeout = APPIUM_NEW_COMMAND_TIMEOUT
    options.set_capability("dontStopAppOnReset", True)
    options.set_capability("systemPort", appium_system_port_for_serial(serial))

    try:
        return webdriver.Remote(server_url or appium_server_url(), options=options)
    except Exception as exc:
        raise AutomationError(f"Could not start Appium driver: {exc}") from exc


def is_recoverable_appium_start_error(exc):
    message = str(exc).lower()
    return any(marker in message for marker in APPIUM_RECOVERABLE_START_MARKERS)


def appium_settle_seconds():
    return env_int(APPIUM_SETTLE_SECONDS_ENV_VAR, APPIUM_DEFAULT_SETTLE_SECONDS)


def stop_u2_uiautomator(serial, run_adb_command=run_adb):
    print("[*] Stopping openatx uiautomator packages...")
    for package in U2_UIAUTOMATOR_PACKAGES:
        run_best_effort_adb(
            ["shell", "am", "force-stop", package],
            serial,
            run_adb_command=run_adb_command,
        )


def stop_appium_uiautomator_server(serial, run_adb_command=run_adb):
    print("[*] Stopping Appium UiAutomator2 server packages...")
    for package in APPIUM_SERVER_PACKAGES:
        run_best_effort_adb(
            ["shell", "am", "force-stop", package],
            serial,
            run_adb_command=run_adb_command,
        )


def remove_appium_forward(serial, run_adb_command=run_adb):
    port = appium_system_port_for_serial(serial)
    run_best_effort_adb(
        ["forward", "--remove", f"tcp:{port}"],
        serial,
        run_adb_command=run_adb_command,
    )


def prepare_appium_session(
    serial,
    run_adb_command=run_adb,
    sleep=time.sleep,
):
    # Only evict the competing openatx u2 UiAutomation consumer. The Appium
    # server packages stay untouched: force-stopping a live instrumentation
    # leaves UiAutomation stale in system_server on API 36+, which is exactly
    # the wedge the recovery ladder exists to clear.
    stop_u2_uiautomator(serial, run_adb_command=run_adb_command)
    sleep(APPIUM_PRE_SESSION_WAIT_SECONDS)


def recover_appium_level_1(serial, run_adb_command=run_adb, sleep=time.sleep):
    print("[*] Appium recovery level 1: stopping UiAutomation consumers...")
    stop_u2_uiautomator(serial, run_adb_command=run_adb_command)
    stop_appium_uiautomator_server(serial, run_adb_command=run_adb_command)
    run_best_effort_adb(
        ["shell", "pkill", "-f", "uiautomator"],
        serial,
        run_adb_command=run_adb_command,
    )
    remove_appium_forward(serial, run_adb_command=run_adb_command)
    sleep(appium_settle_seconds())


def recover_appium_level_2(serial, run_adb_command=run_adb, sleep=time.sleep):
    print("[*] Appium recovery level 2: reinstalling UiAutomator2 server packages...")
    stop_u2_uiautomator(serial, run_adb_command=run_adb_command)
    stop_appium_uiautomator_server(serial, run_adb_command=run_adb_command)
    run_best_effort_adb(
        ["shell", "pkill", "-f", "uiautomator"],
        serial,
        run_adb_command=run_adb_command,
    )
    remove_appium_forward(serial, run_adb_command=run_adb_command)
    for package in APPIUM_SERVER_PACKAGES:
        run_best_effort_adb(
            ["uninstall", package],
            serial,
            run_adb_command=run_adb_command,
        )
    sleep(appium_settle_seconds())


def recover_appium_level_3(serial, run_adb_command=run_adb, sleep=time.sleep):
    print(f"[*] Appium recovery level 3: reconnecting ADB transport for {serial}...")
    run_best_effort_adb(["reconnect"], serial, run_adb_command=run_adb_command)
    sleep(appium_settle_seconds())
    try:
        connect_wifi_device(serial)
    except AutomationError as exc:
        print(f"[WARN] Could not re-establish Wi-Fi ADB connection: {exc}")
    sleep(appium_settle_seconds())


def recover_appium_level_4(serial, run_adb_command=run_adb, sleep=time.sleep):
    print(f"[*] Appium recovery level 4: rebooting {serial} (last resort)...")
    run_best_effort_adb(["reboot"], serial, run_adb_command=run_adb_command)
    attempts = APPIUM_REBOOT_WAIT_SECONDS // APPIUM_REBOOT_POLL_SECONDS
    for _ in range(attempts):
        sleep(APPIUM_REBOOT_POLL_SECONDS)
        try:
            connect_wifi_device(serial)
        except AutomationError:
            continue
        boot_completed = run_best_effort_adb(
            ["shell", "getprop", "sys.boot_completed"],
            serial,
            run_adb_command=run_adb_command,
        )
        if boot_completed and boot_completed.strip() == "1":
            break
    else:
        print(
            f"[WARN] Device {serial} did not come back within "
            f"{APPIUM_REBOOT_WAIT_SECONDS}s after reboot"
        )
        return
    sleep(appium_settle_seconds())
    try:
        wake_and_unlock_device(serial, run_adb_command=run_adb_command, sleep=sleep)
    except AutomationError as exc:
        print(f"[WARN] Could not wake/unlock {serial} after reboot: {exc}")


def build_recovery_ladder():
    ladder = [recover_appium_level_1, recover_appium_level_2]
    if env_bool(APPIUM_RECONNECT_ON_WEDGE_ENV_VAR, True):
        ladder.append(recover_appium_level_3)
    if env_bool(APPIUM_REBOOT_ON_WEDGE_ENV_VAR, False):
        ladder.append(recover_appium_level_4)
    return ladder


def start_appium_driver_with_recovery(
    serial,
    server_url,
    run_adb_command=run_adb,
    driver_factory=start_appium_driver,
    sleep=time.sleep,
):
    prepare_appium_session(
        serial,
        run_adb_command=run_adb_command,
        sleep=sleep,
    )
    last_error = None
    for recover in (None, *build_recovery_ladder()):
        if recover is not None:
            print(
                "[WARN] Appium UiAutomation startup failed; "
                f"running {recover.__name__}: {last_error}"
            )
            recover(serial, run_adb_command=run_adb_command, sleep=sleep)
        try:
            return driver_factory(serial, server_url)
        except AutomationError as exc:
            if not is_recoverable_appium_start_error(exc):
                print(f"[WARN] Appium driver unavailable; using direct media intent: {exc}")
                return None
            last_error = exc

    print(f"[WARN] Appium recovery exhausted; using direct media intent: {last_error}")
    return None


def find_element(driver, selector):
    kind, value = selector
    by = SELECTOR_BY.get(kind)
    if not by:
        raise ValueError(f"Unknown selector kind: {kind}")
    return driver.find_element(by, value)


def click_if_exists(driver, selectors, timeout=5, interval=0.3):
    deadline = time.monotonic() + timeout
    last_error = None

    while True:
        for selector in selectors:
            try:
                element = find_element(driver, selector)
                element.click()
                print(f"[CLICK] Clicked: {selector}")
                return True
            except Exception as exc:
                last_error = exc

        if time.monotonic() >= deadline:
            if last_error is not None:
                print(f"[WARN] Last selector error: {last_error}")
            return False

        time.sleep(interval)


def find_first_element(driver, selectors, timeout=2, interval=0.3):
    deadline = time.monotonic() + timeout

    while True:
        for selector in selectors:
            try:
                return find_element(driver, selector)
            except Exception:
                pass

        if time.monotonic() >= deadline:
            return None

        time.sleep(interval)


def dump_ui(driver, filename):
    source = driver.page_source
    with open(filename, "w", encoding="utf-8") as output:
        output.write(source)
    print(f"[DEBUG] UI dumped to {filename}")


def tap(driver, x, y):
    print(f"[TAP] x={x}, y={y}")
    driver.execute_script("mobile: clickGesture", {"x": x, "y": y})


def attach_selectors(whatsapp_package):
    return (
        ("id", f"{whatsapp_package}:id/input_attach_button"),
        ("accessibility", "Anexar"),
        ("accessibility", "Attach"),
    )


def media_item_selectors(whatsapp_package):
    return (
        ("xpath", f"(//*[@resource-id='{whatsapp_package}:id/media_item_view'])[1]"),
        ("id", f"{whatsapp_package}:id/media_item_view"),
    )


def gallery_attachment_selectors(whatsapp_package):
    return (
        ("id", f"{whatsapp_package}:id/pickfiletype_gallery_holder"),
        ("accessibility", "Galeria"),
        ("accessibility", "Gallery"),
        ("xpath", "//*[@content-desc='Galeria']"),
        ("xpath", "//*[@content-desc='Gallery']"),
        ("xpath", "//*[@text='Galeria']"),
        ("xpath", "//*[@text='Gallery']"),
    )


def audio_attachment_selectors(whatsapp_package):
    return (
        ("id", f"{whatsapp_package}:id/pickfiletype_audio_holder"),
        ("accessibility", "Áudio"),
        ("accessibility", "Audio"),
        ("xpath", "//*[@content-desc='Áudio']"),
        ("xpath", "//*[@content-desc='Audio']"),
        ("xpath", "//*[@text='Áudio']"),
        ("xpath", "//*[@text='Audio']"),
    )


def media_source_selectors(whatsapp_package, mime_type):
    if is_audio_mime(mime_type):
        return audio_attachment_selectors(whatsapp_package)
    if is_image_mime(mime_type) or is_video_mime(mime_type):
        return gallery_attachment_selectors(whatsapp_package)
    return ()


def caption_selectors(whatsapp_package):
    return (
        ("id", f"{whatsapp_package}:id/caption"),
        ("id", f"{whatsapp_package}:id/mentionable_entry"),
        ("id", f"{whatsapp_package}:id/entry"),
        ("xpath", "//android.widget.EditText"),
    )


def send_selectors(whatsapp_package):
    return (
        ("id", f"{whatsapp_package}:id/send"),
        ("id", f"{whatsapp_package}:id/send_button"),
        ("id", f"{whatsapp_package}:id/send_media_btn"),
        ("accessibility", "Enviar"),
        ("accessibility", "Send"),
        ("xpath", "//*[@content-desc='Enviar']"),
        ("xpath", "//*[@content-desc='Send']"),
    )


def enter_caption_if_present(driver, whatsapp_package, caption, timeout=2):
    if not caption:
        return False

    element = find_first_element(
        driver,
        caption_selectors(whatsapp_package),
        timeout=timeout,
    )
    if element is None:
        print("[WARN] Caption field not found; sending media without caption.")
        return False

    try:
        element.click()
    except Exception:
        pass

    element.send_keys(caption)
    print("[CAPTION] Caption entered.")
    return True


def open_attachment_media_source(driver, whatsapp_package, mime_type, timeout=2):
    selectors = media_source_selectors(whatsapp_package, mime_type)
    if not selectors:
        return False
    return click_if_exists(driver, selectors, timeout=timeout)


def send_latest_visible_media(
    driver,
    whatsapp_package,
    caption=None,
    mime_type=None,
    attach_timeout=6,
    media_timeout=6,
    source_timeout=2,
    caption_timeout=2,
    send_timeout=7,
):
    attached = click_if_exists(
        driver,
        attach_selectors(whatsapp_package),
        timeout=attach_timeout,
    )
    if not attached:
        dump_ui(driver, "debug_attach_not_found.xml")
        raise AutomationError("Attach button not found.")

    time.sleep(WAIT_AFTER_ATTACH)

    selected = click_if_exists(
        driver,
        media_item_selectors(whatsapp_package),
        timeout=media_timeout,
    )
    if not selected and open_attachment_media_source(
        driver,
        whatsapp_package,
        mime_type,
        timeout=source_timeout,
    ):
        time.sleep(WAIT_AFTER_ATTACH)
        selected = click_if_exists(
            driver,
            media_item_selectors(whatsapp_package),
            timeout=media_timeout,
        )

    if not selected:
        dump_ui(driver, "debug_media_item_not_found.xml")
        raise AutomationError(
            "No media_item_view found. The media strip is not visible or "
            "WhatsApp did not index the pushed media."
        )

    time.sleep(WAIT_AFTER_SELECT_MEDIA)
    enter_caption_if_present(
        driver,
        whatsapp_package,
        caption,
        timeout=caption_timeout,
    )

    sent = click_if_exists(
        driver,
        send_selectors(whatsapp_package),
        timeout=send_timeout,
    )
    if not sent:
        dump_ui(driver, "debug_send_not_found.xml")
        size = driver.get_window_size()
        tap(driver, int(size["width"] * 0.90), int(size["height"] * 0.92))

    time.sleep(WAIT_AFTER_SEND)


def launch_direct_media_intent(
    serial,
    phone,
    remote_path,
    whatsapp_package,
    caption=None,
    mime_type=None,
    run_adb_command=run_adb,
):
    if not mime_type:
        mime_type = "*/*"

    stream_uri = f"file://{remote_path}"
    command = [
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.SEND",
        "-t",
        mime_type,
        "--grant-read-uri-permission",
        "--es",
        "jid",
        f"{phone}@s.whatsapp.net",
        "--eu",
        STREAM_EXTRA,
        stream_uri,
    ]
    if caption:
        command.extend(["--es", "android.intent.extra.TEXT", caption])
    command.extend(["-p", whatsapp_package])
    run_adb_command(command, serial=serial)


def tap_direct_send_fallback(serial, run_adb_command=run_adb):
    width, height = device_screen_size(serial, run_adb_command=run_adb_command)
    run_adb_command(
        [
            "shell",
            "input",
            "tap",
            str(int(width * DIRECT_SEND_TAP_X_RATIO)),
            str(int(height * DIRECT_SEND_TAP_Y_RATIO)),
        ],
        serial=serial,
    )


def click_direct_media_send(
    serial,
    whatsapp_package,
    run_adb_command=run_adb,
    sleep=time.sleep,
):
    sleep(DIRECT_MEDIA_PREVIEW_WAIT_SECONDS)
    try:
        from .whatsapp import click_send_button

        click_send_button(
            serial,
            whatsapp_package,
            fail_on_contact_picker=True,
        )
    except AutomationError as exc:
        if "contact picker" in str(exc).lower():
            raise
        print(f"[WARN] Could not click direct media send button; tapping: {exc}")
        tap_direct_send_fallback(serial, run_adb_command=run_adb_command)


def send_direct_media_fallback(
    serial,
    phone,
    remote_path,
    whatsapp_package,
    caption=None,
    mime_type=None,
    run_adb_command=run_adb,
    sleep=time.sleep,
):
    print("[*] Sending media through direct Android intent fallback...")
    launch_direct_media_intent(
        serial,
        phone,
        remote_path,
        whatsapp_package,
        caption=caption,
        mime_type=mime_type,
        run_adb_command=run_adb_command,
    )
    click_direct_media_send(
        serial,
        whatsapp_package,
        run_adb_command=run_adb_command,
        sleep=sleep,
    )


def send_media_with_appium(
    serial,
    phone,
    file_path,
    whatsapp_package,
    text=None,
    mime_type=None,
    appium_server=None,
    run_adb_command=run_adb,
    driver_factory=start_appium_driver,
    sleep=time.sleep,
    known_contact=None,
):
    from .chat_navigation import open_chat_via_ui

    remote_path = stage_latest_media(
        serial,
        file_path,
        mime_type,
        run_adb_command=run_adb_command,
    )
    print(f"[OK] Remote media: {remote_path}")

    try:
        # UI navigation must finish before start_appium_driver_with_recovery:
        # prepare_appium_session force-stops the openatx u2 agent it relies on.
        if not open_chat_via_ui(
            serial,
            phone,
            whatsapp_package,
            known_contact,
            run_adb_command=run_adb_command,
        ):
            open_whatsapp_chat(
                serial,
                phone,
                whatsapp_package,
                run_adb_command=run_adb_command,
            )

        driver = start_appium_driver_with_recovery(
            serial,
            appium_server or appium_server_url(),
            run_adb_command=run_adb_command,
            driver_factory=driver_factory,
            sleep=sleep,
        )
        if driver is None:
            send_direct_media_fallback(
                serial,
                phone,
                remote_path,
                whatsapp_package,
                caption=text,
                mime_type=mime_type,
                run_adb_command=run_adb_command,
                sleep=sleep,
            )
            return

        try:
            send_latest_visible_media(
                driver,
                whatsapp_package,
                caption=text,
                mime_type=mime_type,
            )
        finally:
            try:
                driver.quit()
            except Exception as exc:
                print(f"[WARN] Could not quit Appium driver cleanly: {exc}")
            # Let the driver finish its own instrumentation shutdown; no
            # force-stop here — that poisons the next UiAutomation connect.
            sleep(APPIUM_POST_QUIT_WAIT_SECONDS)
    finally:
        cleanup_staged_media(
            serial,
            remote_path,
            run_adb_command=run_adb_command,
        )
