#!/usr/bin/env python3
import os
import time
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy

from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException


# ---------------- CONFIG ----------------

DEVICE = "192.168.15.39:45695"

# WhatsApp Business
WA_PKG = "com.whatsapp.w4b"

TARGET_PHONE = "5547997571861"

LOCAL_IMAGE = "gauge.jpg"

APPIUM_SERVER = "http://127.0.0.1:4723"

WAIT_AFTER_PUSH = 2
WAIT_AFTER_CHAT_OPEN = 4
WAIT_AFTER_ATTACH = 1.5
WAIT_AFTER_SELECT_MEDIA = 2
WAIT_AFTER_SEND = 2

# ----------------------------------------


def adb(*args, check=True, capture=True):
    cmd = ["adb", "-s", DEVICE, *map(str, args)]
    print("[ADB]", " ".join(cmd))

    result = subprocess.run(
        cmd,
        text=True,
        capture_output=capture,
        check=False,
    )

    if check and result.returncode != 0:
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        raise RuntimeError(f"ADB command failed: {' '.join(cmd)}")

    return result


def make_fresh_image_without_exif(src_path):
    """
    Creates a fresh JPG without EXIF metadata.
    This helps WhatsApp/Android treat it as a new image instead of sorting by old EXIF date.
    """
    src = Path(src_path)

    if not src.exists():
        raise FileNotFoundError(f"Local image not found: {src_path}")

    fresh_name = f"fresh_gauge_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    fresh_path = src.parent / fresh_name

    img = Image.open(src).convert("RGB")
    img.save(fresh_path, "JPEG", quality=95)

    print(f"[MEDIA] Created fresh no-EXIF image: {fresh_path}")
    return str(fresh_path)


def push_latest_media():
    """
    Push image to DCIM/Camera with a fresh timestamped filename.
    Then force Android media scanner to index it.
    """
    adb("connect", DEVICE, check=False)

    fresh_local = make_fresh_image_without_exif(LOCAL_IMAGE)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    remote_image = f"/sdcard/DCIM/Camera/IMG_{timestamp}_gauge.jpg"

    adb("push", fresh_local, remote_image)

    # Try to update Android file modified time as well.
    # Some devices support toybox touch; if not, ignore.
    touch_timestamp = datetime.now().strftime("%Y%m%d%H%M.%S")
    adb(
        "shell",
        "toybox",
        "touch",
        "-t",
        touch_timestamp,
        remote_image,
        check=False,
    )

    # Force media scan. Deprecated in Android APIs, but still often works from ADB.
    adb(
        "shell",
        "am",
        "broadcast",
        "-a",
        "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
        "-d",
        f"file://{remote_image}",
        check=False,
    )

    time.sleep(WAIT_AFTER_PUSH)
    return remote_image


def open_whatsapp_chat():
    """
    Opens the exact WhatsApp Business chat using wa.me.
    """
    adb(
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.VIEW",
        "-d",
        f"https://wa.me/{TARGET_PHONE}",
        "-p",
        WA_PKG,
    )

    time.sleep(WAIT_AFTER_CHAT_OPEN)


def start_appium_driver():
    options = UiAutomator2Options()

    options.platform_name = "Android"
    options.automation_name = "UiAutomator2"
    options.udid = DEVICE
    options.no_reset = True
    options.new_command_timeout = 300

    # Important: do not reset/stop WhatsApp after opening the chat with ADB.
    options.set_capability("dontStopAppOnReset", True)

    driver = webdriver.Remote(APPIUM_SERVER, options=options)
    return driver


def find_element(driver, selector):
    kind, value = selector

    if kind == "id":
        return driver.find_element(AppiumBy.ID, value)

    if kind == "accessibility":
        return driver.find_element(AppiumBy.ACCESSIBILITY_ID, value)

    if kind == "xpath":
        return driver.find_element(AppiumBy.XPATH, value)

    raise ValueError(f"Unknown selector kind: {kind}")


def click_if_exists(driver, selectors, timeout=5):
    """
    Tries several selectors and clicks the first one found.
    """
    end_time = time.time() + timeout

    while time.time() < end_time:
        for selector in selectors:
            try:
                el = find_element(driver, selector)
                el.click()
                print(f"[CLICK] Clicked: {selector}")
                return True
            except NoSuchElementException:
                pass
            except Exception as e:
                print(f"[WARN] Selector failed {selector}: {e}")

        time.sleep(0.3)

    return False


def dump_ui(driver, filename="appium_page_source.xml"):
    source = driver.page_source

    with open(filename, "w", encoding="utf-8") as f:
        f.write(source)

    print(f"[DEBUG] UI dumped to {filename}")


def tap(driver, x, y):
    print(f"[TAP] x={x}, y={y}")
    driver.execute_script("mobile: clickGesture", {"x": x, "y": y})


def send_latest_visible_media(driver):
    """
    WhatsApp layout from your dump:
    - Tap Anexar
    - Do NOT tap Galeria
    - Select first media_item_view from the bottom media strip
    - Tap Enviar
    """

    # 1. Tap Anexar
    attached = click_if_exists(driver, [
        ("id", f"{WA_PKG}:id/input_attach_button"),
        ("accessibility", "Anexar"),
        ("accessibility", "Attach"),
    ], timeout=6)

    if not attached:
        dump_ui(driver, "debug_attach_not_found.xml")
        raise RuntimeError("Attach button not found.")

    time.sleep(WAIT_AFTER_ATTACH)

    # 2. Select the first/latest visible media thumbnail.
    # Based on your window.xml, the thumbnails have:
    # resource-id="com.whatsapp.w4b:id/media_item_view"
    selected = click_if_exists(driver, [
        ("xpath", f"(//*[@resource-id='{WA_PKG}:id/media_item_view'])[1]"),
        ("id", f"{WA_PKG}:id/media_item_view"),
    ], timeout=6)

    if not selected:
        dump_ui(driver, "debug_media_item_not_found.xml")
        raise RuntimeError(
            "No media_item_view found. The media strip is not visible or WhatsApp did not index the pushed image."
        )

    time.sleep(WAIT_AFTER_SELECT_MEDIA)

    # 3. Tap Send / Enviar in the media preview.
    sent = click_if_exists(driver, [
        ("id", f"{WA_PKG}:id/send"),
        ("id", f"{WA_PKG}:id/send_button"),
        ("id", f"{WA_PKG}:id/send_media_btn"),
        ("accessibility", "Enviar"),
        ("accessibility", "Send"),
        ("xpath", "//*[@content-desc='Enviar']"),
        ("xpath", "//*[@content-desc='Send']"),
    ], timeout=7)

    if not sent:
        # Safer fallback only for final send button.
        # This is usually bottom-right in WhatsApp media preview.
        dump_ui(driver, "debug_send_not_found.xml")

        size = driver.get_window_size()
        tap(driver, int(size["width"] * 0.90), int(size["height"] * 0.92))

    time.sleep(WAIT_AFTER_SEND)


def main():
    print("[STEP] Push latest media")
    remote_image = push_latest_media()
    print(f"[OK] Remote image: {remote_image}")

    print("[STEP] Open WhatsApp chat")
    open_whatsapp_chat()

    print("[STEP] Start Appium")
    driver = start_appium_driver()

    try:
        print("[STEP] Send latest visible media")
        send_latest_visible_media(driver)
        print("[DONE] Media send flow completed.")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()