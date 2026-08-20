import re
import time

from .adb import run_adb
from .adb_ui import (
    clear_stale_uiautomation,
    click_first,
    dump_ui_xml,
    find_first,
    parse_ui_dump,
    tap_point,
)
from .appium_media import (
    cleanup_staged_media,
    media_item_selectors,
    open_whatsapp_chat,
    send_selectors,
    stage_latest_media,
)
from .errors import AutomationError, WhatsAppRestrictedError

# Coordinates below were captured once, by hand, on R9XY3034HMX (SM-A065M,
# 720x1600) running WhatsApp 2.26.32.78 / Business 2.26.31.75 — the newest
# versions observed across the device fleet at capture time. The media-send
# flow used to locate every element with a fresh `adb shell uiautomator dump`
# per stage (dozens per job); since that dump tool competes with any other
# UiAutomation client (Appium, python uiautomator2) for the same single
# on-device registration slot, a job with that many dump calls kept colliding
# with leftover processes and wedging ("stale UiAutomation session"). Tapping
# fixed, pre-measured coordinates removes most of that exposure — see
# verify_media_was_sent() for one remaining dump call (safety net against a
# silently-missed tap) and select_latest_media_from_attach_menu() for the
# other (the attach sheet's resting height is NOT fixed — repeated opens on
# the same device measured 901px, 615px, and 928px, seemingly due to
# thumbnail-load timing or server-side feature flags — so the media
# thumbnail's position genuinely can't be hardcoded; it still needs a dump).
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
MEDIA_SEND_UNVERIFIED_DUMP = "debug_media_send_unverified.xml"

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


def ui_dump_has_whatsapp_restricted_text(xml_text):
    from .whatsapp import text_matches_whatsapp_restricted

    try:
        elements = parse_ui_dump(xml_text)
    except AutomationError:
        return False

    return any(
        text_matches_whatsapp_restricted(element.get(field))
        for element in elements
        for field in ("text", "content_desc")
    )


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


def select_latest_media_from_attach_menu(
    serial,
    whatsapp_package,
    run_adb_command=run_adb,
    sleep=time.sleep,
):
    tap_fixed_point(serial, ATTACH_BUTTON_COORDS, run_adb_command=run_adb_command)
    sleep(WAIT_AFTER_ATTACH_SECONDS)

    # The attach sheet's resting height varies between opens (see module
    # comment above), so the thumbnail can't be a fixed coordinate — locate
    # it by resource-id instead. Clear any leftover UiAutomation holder
    # first: this is the first dump in the job, so nothing upstream would
    # have caught a stale session yet.
    clear_stale_uiautomation(serial, run_adb_command=run_adb_command)
    selected = click_first(
        serial,
        media_item_selectors(whatsapp_package),
        timeout=MEDIA_ITEM_TIMEOUT_SECONDS,
        run_adb_command=run_adb_command,
        sleep=sleep,
    )
    if not selected:
        raise AutomationError(
            "No media_item_view found. The media strip is not visible or "
            "WhatsApp did not index the pushed media."
        )
    sleep(WAIT_AFTER_SELECT_MEDIA_SECONDS)


def enter_caption_and_send(
    serial,
    whatsapp_package,
    caption=None,
    run_adb_command=run_adb,
    sleep=time.sleep,
):
    if caption:
        tap_fixed_point(serial, CAPTION_FIELD_COORDS, run_adb_command=run_adb_command)
        sleep(CAPTION_FOCUS_SETTLE_SECONDS)
        _type_caption(serial, caption, run_adb_command=run_adb_command)

    tap_fixed_point(serial, SEND_BUTTON_COORDS, run_adb_command=run_adb_command)
    sleep(WAIT_AFTER_SEND_SECONDS)

    verify_media_was_sent(serial, whatsapp_package, run_adb_command=run_adb_command)


def write_debug_dump(filename, xml_text):
    try:
        with open(filename, "w", encoding="utf-8") as output:
            output.write(xml_text)
        print(f"[DEBUG] UI dumped to {filename}")
    except OSError as exc:
        print(f"[WARN] Could not write {filename}: {exc}")


def verify_media_was_sent(serial, whatsapp_package, run_adb_command=run_adb):
    # The only dump call left in the whole media-send flow: a single
    # safety-net check that the "send" tap actually landed, instead of
    # silently reporting success on a missed/blind tap.
    clear_stale_uiautomation(serial, run_adb_command=run_adb_command)

    try:
        xml_text = dump_ui_xml(serial, run_adb_command=run_adb_command)
    except AutomationError as exc:
        raise AutomationError(
            f"Could not verify whether the media was actually sent: {exc}"
        ) from exc

    elements = parse_ui_dump(xml_text)
    if find_first(elements, send_selectors(whatsapp_package)) is None:
        return

    if ui_dump_has_whatsapp_restricted_text(xml_text):
        raise WhatsAppRestrictedError("WhatsApp is restricted.")

    write_debug_dump(MEDIA_SEND_UNVERIFIED_DUMP, xml_text)
    raise AutomationError(
        "Media appears unsent; the send button is still showing after "
        "tapping send."
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
):
    # Always clear any leftover UiAutomation holder before a media job starts,
    # regardless of whether this particular job would otherwise hit a dump
    # first in select_latest_media_from_attach_menu() or verify_media_was_sent().
    # Best-effort and cheap: unconditionally kills any stale app_process/
    # uiautomator holder so this job never inherits a wedge from whatever ran
    # on this device before it.
    clear_stale_uiautomation(serial, run_adb_command=run_adb_command)

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
            run_adb_command=run_adb_command,
            sleep=sleep,
        )
        enter_caption_and_send(
            serial,
            whatsapp_package,
            caption=text,
            run_adb_command=run_adb_command,
            sleep=sleep,
        )
    finally:
        cleanup_staged_media(
            serial,
            remote_path,
            run_adb_command=run_adb_command,
        )
