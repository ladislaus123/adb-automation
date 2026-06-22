import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

from .adb import run_adb
from .config import APPIUM_SERVER_ENV_VAR, DEFAULT_APPIUM_SERVER
from .errors import AutomationError

DEVICE_CAMERA_DIR = "/sdcard/DCIM/Camera"
WAIT_AFTER_PUSH = 2
WAIT_AFTER_CHAT_OPEN = 4
WAIT_AFTER_ATTACH = 1.5
WAIT_AFTER_SELECT_MEDIA = 2
WAIT_AFTER_SEND = 2
APPIUM_NEW_COMMAND_TIMEOUT = 300

SELECTOR_BY = {
    "id": "id",
    "accessibility": "accessibility id",
    "xpath": "xpath",
}


def appium_server_url():
    return os.environ.get(APPIUM_SERVER_ENV_VAR, DEFAULT_APPIUM_SERVER)


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

        time.sleep(wait_after_push)
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

    try:
        return webdriver.Remote(server_url or appium_server_url(), options=options)
    except Exception as exc:
        raise AutomationError(f"Could not start Appium driver: {exc}") from exc


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


def send_latest_visible_media(
    driver,
    whatsapp_package,
    caption=None,
    attach_timeout=6,
    media_timeout=6,
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
):
    remote_path = stage_latest_media(
        serial,
        file_path,
        mime_type,
        run_adb_command=run_adb_command,
    )
    print(f"[OK] Remote media: {remote_path}")

    try:
        open_whatsapp_chat(
            serial,
            phone,
            whatsapp_package,
            run_adb_command=run_adb_command,
        )

        driver = driver_factory(serial, appium_server or appium_server_url())
        try:
            send_latest_visible_media(driver, whatsapp_package, caption=text)
        finally:
            try:
                driver.quit()
            except Exception as exc:
                print(f"[WARN] Could not quit Appium driver cleanly: {exc}")
    finally:
        cleanup_staged_media(
            serial,
            remote_path,
            run_adb_command=run_adb_command,
        )
