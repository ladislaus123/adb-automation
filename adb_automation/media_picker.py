import re
import time

from .adb import run_adb
from .adb_ui import tap_point
from .appium_media import (
    cleanup_staged_media,
    open_whatsapp_chat,
    stage_latest_media,
    stop_u2_uiautomator,
)
from .errors import AutomationError

# Coordinates below were captured once, by hand, on R9XY3034HMX (SM-A065M,
# 720x1600) running WhatsApp 2.26.32.78 / Business 2.26.31.75 — the newest
# versions observed across the device fleet at capture time. The media-send
# flow used to locate every element with a fresh `adb shell uiautomator dump`
# per stage (dozens per job); since that dump tool competes with any other
# UiAutomation client (Appium, python uiautomator2) for the same single
# on-device registration slot, a job with that many dump calls kept colliding
# with leftover processes and wedging ("stale UiAutomation session"). Tapping
# fixed, pre-measured coordinates removes most of that exposure. The two
# remaining variable-position lookups (the media thumbnail in
# select_latest_media_from_attach_menu, and the post-send confirmation in
# verify_media_was_sent) go through the same uiautomator2 client the text-send
# flow uses (see whatsapp.py) instead of a raw `uiautomator dump` -- that
# keeps this flow to a single well-behaved UiAutomation consumer per job
# instead of mixing it with the raw dump tool.
REFERENCE_SCREEN_SIZE = (720, 1600)
ATTACH_BUTTON_COORDS = (461, 1456)
CAPTION_FIELD_COORDS = (326, 1450)
SEND_BUTTON_COORDS = (660, 1450)

WAIT_AFTER_ATTACH_SECONDS = 1.5
WAIT_AFTER_SELECT_MEDIA_SECONDS = 2
WAIT_AFTER_SEND_SECONDS = 2
CAPTION_FOCUS_SETTLE_SECONDS = 0.4
CHAT_READY_SETTLE_SECONDS = 1.0
MEDIA_ITEM_TIMEOUT_SECONDS = 6
SOURCE_TIMEOUT_SECONDS = 2
SEND_CONFIRM_TIMEOUT_SECONDS = 5
SEND_CONFIRM_POLL_SECONDS = 0.2
SELECTOR_RETRY_INTERVAL_SECONDS = 0.25

SCREEN_SIZE_PATTERN = re.compile(r"(\d+)x(\d+)")


def device_screen_size(serial, run_adb_command=run_adb):
    try:
        output = run_adb_command(["shell", "wm", "size"], serial=serial)
    except AutomationError:
        return REFERENCE_SCREEN_SIZE

    match = SCREEN_SIZE_PATTERN.search(str(output or ""))
    if not match:
        return REFERENCE_SCREEN_SIZE
    return (int(match.group(1)), int(match.group(2)))


def scaled_point(serial, coords, run_adb_command=run_adb):
    width, height = device_screen_size(serial, run_adb_command=run_adb_command)
    reference_width, reference_height = REFERENCE_SCREEN_SIZE
    x, y = coords
    return (
        round(x * width / reference_width),
        round(y * height / reference_height),
    )


def tap_fixed_point(serial, coords, run_adb_command=run_adb):
    x, y = scaled_point(serial, coords, run_adb_command=run_adb_command)
    tap_point(serial, x, y, run_adb_command=run_adb_command)


def verify_whatsapp_chat_ready(
    serial,
    whatsapp_package,
    run_adb_command=run_adb,
    sleep=time.sleep,
):
    # open_whatsapp_chat() already settles for WAIT_AFTER_CHAT_OPEN seconds;
    # this is just a small extra buffer, not a dump-based readiness check —
    # see the module docstring-style comment above for why.
    sleep(CHAT_READY_SETTLE_SECONDS)


def _type_caption(serial, caption, run_adb_command=run_adb):
    from .whatsapp import escape_adb_input_text, is_adb_safe_input_text

    if not is_adb_safe_input_text(caption):
        print(
            "[WARN] Caption has characters that can't be typed directly over ADB; "
            "sending media without a caption."
        )
        return
    run_adb_command(
        ["shell", "input", "text", escape_adb_input_text(caption)],
        serial=serial,
    )


def media_item_selector_kwargs(whatsapp_package):
    return ({"resourceId": f"{whatsapp_package}:id/media_item_view"},)


def gallery_media_source_selector_kwargs(whatsapp_package):
    return (
        {"resourceId": f"{whatsapp_package}:id/pickfiletype_gallery_holder"},
        {"description": "Galeria"},
        {"description": "Gallery"},
    )


def audio_media_source_selector_kwargs(whatsapp_package):
    return (
        {"resourceId": f"{whatsapp_package}:id/pickfiletype_audio_holder"},
        {"description": "Áudio"},
        {"description": "Audio"},
    )


def media_source_selector_kwargs(whatsapp_package, mime_type):
    from .appium_media import is_audio_mime, is_image_mime, is_video_mime

    if is_audio_mime(mime_type):
        return audio_media_source_selector_kwargs(whatsapp_package)
    if is_image_mime(mime_type) or is_video_mime(mime_type):
        return gallery_media_source_selector_kwargs(whatsapp_package)
    return ()


def wait_and_click_first(device, selector_kwargs_list, timeout, sleep=time.sleep):
    """Poll `selector_kwargs_list` with uiautomator2 until one exists, click it.

    Mirrors whatsapp.click_send_button's own retry loop so this flow shares
    its resilience to a slow-to-render UI, instead of the old
    dump-then-parse-then-tap approach.
    """
    from .whatsapp import raise_if_whatsapp_restricted, selector_exists

    deadline = time.monotonic() + timeout
    while True:
        raise_if_whatsapp_restricted(device)
        for selector_kwargs in selector_kwargs_list:
            try:
                selector = device(**selector_kwargs)
                if selector_exists(selector):
                    selector.click()
                    return True
            except Exception:
                continue
        if time.monotonic() >= deadline:
            return False
        sleep(SELECTOR_RETRY_INTERVAL_SECONDS)


def select_latest_media_from_attach_menu(
    serial,
    whatsapp_package,
    mime_type=None,
    run_adb_command=run_adb,
    sleep=time.sleep,
    adb_transport="wifi",
    device_connector=None,
):
    from .whatsapp import connect_uiautomator_device, wait_for_whatsapp_activity

    if device_connector is None:
        device_connector = connect_uiautomator_device

    tap_fixed_point(serial, ATTACH_BUTTON_COORDS, run_adb_command=run_adb_command)
    sleep(WAIT_AFTER_ATTACH_SECONDS)

    device = device_connector(serial)
    wait_for_whatsapp_activity(device, whatsapp_package)

    selected = wait_and_click_first(
        device,
        media_item_selector_kwargs(whatsapp_package),
        MEDIA_ITEM_TIMEOUT_SECONDS,
        sleep=sleep,
    )
    if not selected:
        # On some devices/WhatsApp versions the attach sheet's "recent media"
        # strip isn't shown by default and the "Galeria" tile has to be
        # tapped first to reveal it.
        source_kwargs = media_source_selector_kwargs(whatsapp_package, mime_type)
        if source_kwargs and wait_and_click_first(
            device, source_kwargs, SOURCE_TIMEOUT_SECONDS, sleep=sleep
        ):
            sleep(WAIT_AFTER_ATTACH_SECONDS)
            selected = wait_and_click_first(
                device,
                media_item_selector_kwargs(whatsapp_package),
                MEDIA_ITEM_TIMEOUT_SECONDS,
                sleep=sleep,
            )

    if not selected:
        raise AutomationError(
            "No media_item_view found. The media strip is not visible or "
            "WhatsApp did not index the pushed media."
        )
    sleep(WAIT_AFTER_SELECT_MEDIA_SECONDS)


def wait_for_send_button_gone(
    device,
    whatsapp_package,
    timeout=SEND_CONFIRM_TIMEOUT_SECONDS,
    sleep=time.sleep,
):
    from .whatsapp import selector_exists, send_button_selectors

    deadline = time.monotonic() + timeout
    while True:
        still_showing = False
        for selector_kwargs in send_button_selectors(whatsapp_package):
            try:
                if selector_exists(device(**selector_kwargs)):
                    still_showing = True
                    break
            except Exception:
                continue
        if not still_showing:
            return True
        if time.monotonic() >= deadline:
            return False
        sleep(SEND_CONFIRM_POLL_SECONDS)


def verify_media_was_sent(
    serial,
    whatsapp_package,
    run_adb_command=run_adb,
    sleep=time.sleep,
    adb_transport="wifi",
    device_connector=None,
):
    from .whatsapp import connect_uiautomator_device, raise_if_whatsapp_restricted

    if device_connector is None:
        device_connector = connect_uiautomator_device

    device = device_connector(serial)
    if wait_for_send_button_gone(device, whatsapp_package, sleep=sleep):
        return

    raise_if_whatsapp_restricted(device)
    raise AutomationError(
        "Media appears unsent; the send button is still showing after "
        "tapping send."
    )


def enter_caption_and_send(
    serial,
    whatsapp_package,
    caption=None,
    run_adb_command=run_adb,
    sleep=time.sleep,
    adb_transport="wifi",
    device_connector=None,
):
    if caption:
        tap_fixed_point(serial, CAPTION_FIELD_COORDS, run_adb_command=run_adb_command)
        sleep(CAPTION_FOCUS_SETTLE_SECONDS)
        _type_caption(serial, caption, run_adb_command=run_adb_command)

    tap_fixed_point(serial, SEND_BUTTON_COORDS, run_adb_command=run_adb_command)
    sleep(WAIT_AFTER_SEND_SECONDS)

    verify_media_was_sent(
        serial,
        whatsapp_package,
        run_adb_command=run_adb_command,
        sleep=sleep,
        adb_transport=adb_transport,
        device_connector=device_connector,
    )


def send_media_via_gallery_picker(
    serial,
    phone,
    file_path,
    whatsapp_package,
    text=None,
    mime_type=None,
    run_adb_command=run_adb,
    sleep=time.sleep,
    adb_transport="wifi",
    device_connector=None,
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
        verify_whatsapp_chat_ready(
            serial,
            whatsapp_package,
            run_adb_command=run_adb_command,
            sleep=sleep,
        )
        select_latest_media_from_attach_menu(
            serial,
            whatsapp_package,
            mime_type=mime_type,
            run_adb_command=run_adb_command,
            sleep=sleep,
            adb_transport=adb_transport,
            device_connector=device_connector,
        )
        enter_caption_and_send(
            serial,
            whatsapp_package,
            caption=text,
            run_adb_command=run_adb_command,
            sleep=sleep,
            adb_transport=adb_transport,
            device_connector=device_connector,
        )
    finally:
        # This flow now registers its own on-device UiAutomation connection
        # via uiautomator2 (see select_latest_media_from_attach_menu /
        # verify_media_was_sent), the same as the text-send flow -- force-stop
        # it once we're done so it doesn't poison the next job's raw
        # `uiautomator dump` calls (e.g. chat_navigation.py's debug dumps).
        stop_u2_uiautomator(serial)
        cleanup_staged_media(
            serial,
            remote_path,
            run_adb_command=run_adb_command,
        )
