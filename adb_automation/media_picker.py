import time

from .adb import run_adb
from .adb_ui import (
    click_first,
    dump_ui_xml,
    parse_ui_dump,
    tap_element,
    wait_for_first,
)
from .appium_media import (
    attach_selectors,
    caption_selectors,
    cleanup_staged_media,
    media_item_selectors,
    media_source_selectors,
    open_whatsapp_chat,
    send_selectors,
    stage_latest_media,
)
from .errors import AutomationError, WhatsAppRestrictedError

ATTACH_TIMEOUT_SECONDS = 6
MEDIA_ITEM_TIMEOUT_SECONDS = 6
SOURCE_TIMEOUT_SECONDS = 2
CAPTION_TIMEOUT_SECONDS = 2
SEND_TIMEOUT_SECONDS = 7
WAIT_AFTER_ATTACH_SECONDS = 1.5
WAIT_AFTER_SELECT_MEDIA_SECONDS = 2
WAIT_AFTER_SEND_SECONDS = 2
CAPTION_FOCUS_SETTLE_SECONDS = 0.4


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


def raise_if_whatsapp_restricted_dump(serial, run_adb_command=run_adb):
    try:
        xml_text = dump_ui_xml(serial, run_adb_command=run_adb_command)
    except Exception:
        return

    if ui_dump_has_whatsapp_restricted_text(xml_text):
        raise WhatsAppRestrictedError("WhatsApp is restricted.")


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
    mime_type=None,
    run_adb_command=run_adb,
    sleep=time.sleep,
):
    attached = click_first(
        serial,
        attach_selectors(whatsapp_package),
        timeout=ATTACH_TIMEOUT_SECONDS,
        run_adb_command=run_adb_command,
        sleep=sleep,
    )
    if not attached:
        raise_if_whatsapp_restricted_dump(
            serial,
            run_adb_command=run_adb_command,
        )
        raise AutomationError("Attach button not found.")
    sleep(WAIT_AFTER_ATTACH_SECONDS)

    selected = click_first(
        serial,
        media_item_selectors(whatsapp_package),
        timeout=MEDIA_ITEM_TIMEOUT_SECONDS,
        run_adb_command=run_adb_command,
        sleep=sleep,
    )
    if not selected:
        source_selectors = media_source_selectors(whatsapp_package, mime_type)
        if source_selectors and click_first(
            serial,
            source_selectors,
            timeout=SOURCE_TIMEOUT_SECONDS,
            run_adb_command=run_adb_command,
            sleep=sleep,
        ):
            sleep(WAIT_AFTER_ATTACH_SECONDS)
            selected = click_first(
                serial,
                media_item_selectors(whatsapp_package),
                timeout=MEDIA_ITEM_TIMEOUT_SECONDS,
                run_adb_command=run_adb_command,
                sleep=sleep,
            )

    if not selected:
        raise_if_whatsapp_restricted_dump(
            serial,
            run_adb_command=run_adb_command,
        )
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
        caption_element = wait_for_first(
            serial,
            caption_selectors(whatsapp_package),
            timeout=CAPTION_TIMEOUT_SECONDS,
            run_adb_command=run_adb_command,
            sleep=sleep,
        )
        if caption_element is not None:
            tap_element(serial, caption_element, run_adb_command=run_adb_command)
            sleep(CAPTION_FOCUS_SETTLE_SECONDS)
            _type_caption(serial, caption, run_adb_command=run_adb_command)
        else:
            print("[WARN] Caption field not found; sending media without caption.")

    sent = click_first(
        serial,
        send_selectors(whatsapp_package),
        timeout=SEND_TIMEOUT_SECONDS,
        run_adb_command=run_adb_command,
        sleep=sleep,
    )
    if not sent:
        raise_if_whatsapp_restricted_dump(
            serial,
            run_adb_command=run_adb_command,
        )
        raise AutomationError("Send button not found after selecting media.")
    sleep(WAIT_AFTER_SEND_SECONDS)


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
        select_latest_media_from_attach_menu(
            serial,
            whatsapp_package,
            mime_type=mime_type,
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
