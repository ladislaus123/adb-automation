import mimetypes
import os
import time
import urllib.parse

from .adb import run_adb
from .appium_media import send_media_with_appium
from .config import STREAM_EXTRA, WHATSAPP_BUSINESS_PACKAGE, WHATSAPP_PACKAGES
from .errors import AutomationError

SEND_BUTTON_RESOURCE_NAME = "send"
SEND_BUTTON_DESCRIPTIONS = (
    "Send",
    "Enviar",
)
SEND_BUTTON_TIMEOUT_SECONDS = 10
WHATSAPP_ACTIVITY_WAIT_SECONDS = 2
MESSAGE_ENTRY_TIMEOUT_SECONDS = 8
DEVICE_DOWNLOAD_DIR = "/storage/emulated/0/Download"
CONTACT_PICKER_TEXTS = (
    "Send to",
    "Enviar para",
)
HUMAN_TYPE_BURST_SIZES = (3, 4, 2, 5, 3, 6)
HUMAN_TYPE_PAUSE_SECONDS = 0.35
HUMAN_CORRECTION_PAUSE_SECONDS = 0.5
HUMAN_UNICODE_SET_PAUSE_SECONDS = 0.2
HUMAN_CORRECTION_FRAGMENTS = ("teh", "kk", "..", "hm")
ADB_INPUT_SHELL_SPECIALS = set("'\"`$&|;<>()*?!#[]{}~\\")
TEXT_CHUNK_ADB = "adb"
TEXT_CHUNK_UNICODE = "unicode"


def normalize_phone(phone):
    normalized = "".join(char for char in str(phone) if char.isdigit())
    if not normalized:
        raise ValueError("phone number is required.")
    return normalized


def guessed_mime_type(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type


def should_use_appium_media(mime_type):
    return bool(
        mime_type
        and (
            mime_type.startswith("image/")
            or mime_type.startswith("video/")
            or mime_type.startswith("audio/")
        )
    )


def get_whatsapp_package(serial, business=False):
    """Find regular WhatsApp or WhatsApp Business on the selected device."""
    output = run_adb(["shell", "pm", "list", "packages", "whatsapp"], serial=serial)
    installed = {
        line.split("package:", 1)[1].strip()
        for line in output.splitlines()
        if line.startswith("package:")
    }

    if business:
        if WHATSAPP_BUSINESS_PACKAGE in installed:
            return WHATSAPP_BUSINESS_PACKAGE
        return None

    for package in WHATSAPP_PACKAGES:
        if package in installed:
            return package

    return None


def connect_uiautomator_device(serial):
    """Connect to a device through uiautomator2."""
    try:
        import uiautomator2 as u2
    except ImportError as exc:
        raise AutomationError(
            "uiautomator2 is required to click the WhatsApp send button. "
            "Install it with: pip install uiautomator2"
        ) from exc

    try:
        return u2.connect(serial)
    except Exception as exc:
        raise AutomationError(
            f"Could not connect to device {serial} with uiautomator2: {exc}"
        ) from exc


def send_button_selectors(whatsapp_package):
    return (
        {"resourceId": f"{whatsapp_package}:id/{SEND_BUTTON_RESOURCE_NAME}"},
        {"resourceIdMatches": rf".*:id/{SEND_BUTTON_RESOURCE_NAME}"},
        *({"description": description} for description in SEND_BUTTON_DESCRIPTIONS),
        *(
            {"descriptionContains": description}
            for description in SEND_BUTTON_DESCRIPTIONS
        ),
    )


def message_entry_selectors(whatsapp_package):
    return (
        {"resourceId": f"{whatsapp_package}:id/entry"},
        {"resourceId": f"{whatsapp_package}:id/mentionable_entry"},
        {"resourceIdMatches": r".*:id/entry"},
        {"resourceIdMatches": r".*:id/mentionable_entry"},
        {"className": "android.widget.EditText"},
        {"classNameMatches": r".*EditText"},
    )


def contact_picker_selectors():
    return (
        *({"text": text} for text in CONTACT_PICKER_TEXTS),
        *({"textContains": text} for text in CONTACT_PICKER_TEXTS),
    )


def selector_exists(selector):
    exists = getattr(selector, "exists", False)
    if callable(exists):
        return bool(exists())
    return bool(exists)


def wait_for_whatsapp_activity(device, whatsapp_package):
    wait_activity = getattr(device, "wait_activity", None)
    if not callable(wait_activity):
        return

    try:
        wait_activity(whatsapp_package, timeout=WHATSAPP_ACTIVITY_WAIT_SECONDS)
    except Exception:
        return


def is_contact_picker_visible(device):
    for selector_kwargs in contact_picker_selectors():
        selector = device(**selector_kwargs)
        if selector_exists(selector):
            return True
    return False


def focus_message_entry(
    serial,
    whatsapp_package,
    timeout=MESSAGE_ENTRY_TIMEOUT_SECONDS,
    device_connector=None,
):
    if device_connector is None:
        device_connector = connect_uiautomator_device

    device = device_connector(serial)
    wait_for_whatsapp_activity(device, whatsapp_package)
    deadline = time.monotonic() + timeout
    last_error = None

    while True:
        for selector_kwargs in message_entry_selectors(whatsapp_package):
            try:
                selector = device(**selector_kwargs)
                if selector_exists(selector):
                    selector.click()
                    time.sleep(0.4)
                    return selector
            except Exception as exc:
                last_error = exc

        if time.monotonic() >= deadline:
            break
        time.sleep(0.25)

    details = (
        f" Last uiautomator2 error: {last_error}"
        if last_error is not None
        else ""
    )
    raise AutomationError(
        "Could not find the WhatsApp message compose field with uiautomator2."
        + details
    )


def click_send_button(
    serial,
    whatsapp_package,
    timeout=SEND_BUTTON_TIMEOUT_SECONDS,
    device_connector=None,
    fail_on_contact_picker=False,
):
    if device_connector is None:
        device_connector = connect_uiautomator_device

    device = device_connector(serial)
    wait_for_whatsapp_activity(device, whatsapp_package)
    deadline = time.monotonic() + timeout
    last_error = None

    while True:
        if fail_on_contact_picker:
            try:
                if is_contact_picker_visible(device):
                    raise AutomationError(
                        "WhatsApp opened the contact picker instead of the direct "
                        "chat media preview. The direct jid intent was not honored."
                    )
            except AutomationError:
                raise
            except Exception as exc:
                last_error = exc

        for selector_kwargs in send_button_selectors(whatsapp_package):
            try:
                selector = device(**selector_kwargs)
                if selector_exists(selector):
                    selector.click()
                    return
            except Exception as exc:
                last_error = exc

        if time.monotonic() >= deadline:
            break
        time.sleep(0.25)

    details = (
        f" Last uiautomator2 error: {last_error}"
        if last_error is not None
        else ""
    )
    raise AutomationError(
        "Could not find the WhatsApp send button with uiautomator2." + details
    )


def launch_whatsapp_direct_media(
    serial,
    phone,
    text,
    file_path,
    whatsapp_package,
    mime_type,
):
    filename = os.path.basename(file_path)
    remote_path = f"{DEVICE_DOWNLOAD_DIR}/{filename}"
    stream_uri = f"file://{remote_path}"
    if not mime_type:
        mime_type = "image/jpeg"

    print(f"[*] Pushing {filename} to device storage ({mime_type})...")
    run_adb(["push", file_path, remote_path], serial=serial)

    print(f"[*] Launching WhatsApp media intent for +{phone}...")
    intent_cmd = [
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.SEND",
        "-t",
        mime_type,
        "--es",
        "jid",
        f"{phone}@s.whatsapp.net",
        "--eu",
        STREAM_EXTRA,
        stream_uri,
    ]
    if text:
        intent_cmd.extend(["--es", "android.intent.extra.TEXT", text])
    intent_cmd.extend(["-p", whatsapp_package])
    run_adb(intent_cmd, serial=serial)


def launch_whatsapp_text(serial, phone, whatsapp_package):
    print(f"[*] Launching WhatsApp chat intent for +{phone}...")

    run_adb(
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
            "-f",
            "0x14000000",
        ],
        serial=serial,
    )


def launch_whatsapp_prefilled_text(serial, phone, text, whatsapp_package):
    print(f"[*] Falling back to WhatsApp prefilled text intent for +{phone}...")
    encoded_text = urllib.parse.quote(text)
    whatsapp_url = f"https://wa.me/{phone}?text={encoded_text}"

    run_adb(
        [
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            whatsapp_url,
            "-p",
            whatsapp_package,
            "-f",
            "0x14000000",
        ],
        serial=serial,
    )


def escape_adb_input_text(text):
    escaped = []
    for char in text:
        if char == " ":
            escaped.append("%s")
        elif char in ADB_INPUT_SHELL_SPECIALS:
            escaped.append("\\" + char)
        else:
            escaped.append(char)
    return "".join(escaped)


def is_adb_safe_input_char(char):
    codepoint = ord(char)
    return char == " " or 0x21 <= codepoint <= 0x7E


def is_adb_safe_input_text(text):
    return all(is_adb_safe_input_char(char) for char in text)


def split_adb_safe_text(text):
    chunks = []
    current_kind = None
    current_text = []

    for char in text:
        kind = (
            TEXT_CHUNK_ADB
            if is_adb_safe_input_char(char)
            else TEXT_CHUNK_UNICODE
        )
        if kind != current_kind and current_text:
            chunks.append((current_kind, "".join(current_text)))
            current_text = []
        current_kind = kind
        current_text.append(char)

    if current_text:
        chunks.append((current_kind, "".join(current_text)))

    return tuple(chunks)


def type_text_chunk(serial, text):
    if not text:
        return
    if not is_adb_safe_input_text(text):
        raise AutomationError("ADB input text cannot type Unicode safely.")
    run_adb(["shell", "input", "text", escape_adb_input_text(text)], serial=serial)


def press_backspace(serial, count=1):
    for _ in range(count):
        run_adb(["shell", "input", "keyevent", "KEYCODE_DEL"], serial=serial)
        time.sleep(0.08)


def clear_message_draft(serial, text):
    delete_count = max(20, len(text) + 12)
    command = ["shell", "input", "keyevent"]
    command.extend(["KEYCODE_DEL"] * delete_count)

    try:
        run_adb(command, serial=serial)
        time.sleep(0.2)
    except AutomationError as exc:
        print(f"[WARN] Batched draft clear failed; retrying slowly: {exc}")
        try:
            press_backspace(serial, delete_count)
        except AutomationError as retry_exc:
            print(f"[WARN] Could not fully clear partial draft: {retry_exc}")


def correction_positions(text):
    if not text:
        return ()
    if len(text) <= 2:
        return (0,)

    correction_count = max(1, min(4, (len(text) // 18) + 1))
    positions = []
    for index in range(correction_count):
        position = int(((index + 1) * len(text)) / (correction_count + 1))
        positions.append(max(1, min(len(text) - 1, position)))
    return tuple(sorted(set(positions)))


def type_visible_text(serial, text, sleep_interval=HUMAN_TYPE_PAUSE_SECONDS):
    cursor = 0
    burst_index = 0
    while cursor < len(text):
        burst_size = HUMAN_TYPE_BURST_SIZES[burst_index % len(HUMAN_TYPE_BURST_SIZES)]
        chunk = text[cursor : cursor + burst_size]
        type_text_chunk(serial, chunk)
        cursor += len(chunk)
        burst_index += 1
        time.sleep(sleep_interval)


def inject_visible_correction(serial, correction_index):
    fragment = HUMAN_CORRECTION_FRAGMENTS[
        correction_index % len(HUMAN_CORRECTION_FRAGMENTS)
    ]
    type_text_chunk(serial, fragment)
    time.sleep(HUMAN_CORRECTION_PAUSE_SECONDS)
    press_backspace(serial, len(fragment))
    time.sleep(HUMAN_CORRECTION_PAUSE_SECONDS)


def set_message_entry_text(message_entry, text):
    errors = []
    set_text = getattr(message_entry, "set_text", None)
    if callable(set_text):
        try:
            set_text(text)
            time.sleep(HUMAN_UNICODE_SET_PAUSE_SECONDS)
            return
        except Exception as exc:
            errors.append(f"set_text: {exc}")

    send_keys = getattr(message_entry, "send_keys", None)
    if callable(send_keys):
        for clear_method_name in ("clear_text", "clear"):
            clear_text = getattr(message_entry, clear_method_name, None)
            if not callable(clear_text):
                continue
            try:
                clear_text()
                send_keys(text)
                time.sleep(HUMAN_UNICODE_SET_PAUSE_SECONDS)
                return
            except Exception as exc:
                errors.append(f"{clear_method_name}+send_keys: {exc}")

    details = f" Details: {'; '.join(errors)}" if errors else ""
    raise AutomationError(
        "Could not insert Unicode text into WhatsApp compose field." + details
    )


def human_type_unicode_text(serial, text, message_entry):
    if message_entry is None:
        raise AutomationError(
            "Unicode text requires an active WhatsApp compose field."
        )

    accumulated = ""
    correction_index = 0
    correction_count = len(correction_positions(text))

    for kind, chunk in split_adb_safe_text(text):
        if kind == TEXT_CHUNK_ADB:
            if correction_index < correction_count:
                inject_visible_correction(serial, correction_index)
                correction_index += 1
            type_visible_text(serial, chunk)
            accumulated += chunk
            continue

        accumulated += chunk
        set_message_entry_text(message_entry, accumulated)

    set_message_entry_text(message_entry, text)


def human_type_text(serial, text, message_entry=None):
    if not text:
        return

    if not is_adb_safe_input_text(text):
        human_type_unicode_text(serial, text, message_entry)
        return

    cursor = 0
    for correction_index, position in enumerate(correction_positions(text)):
        if position > cursor:
            type_visible_text(serial, text[cursor:position])
            cursor = position
        inject_visible_correction(serial, correction_index)

    if cursor < len(text):
        type_visible_text(serial, text[cursor:])


def send_whatsapp(
    serial,
    phone,
    text=None,
    file_path=None,
    business=False,
    known_contact=None,
):
    phone = normalize_phone(phone)
    if not text and not file_path:
        raise ValueError("you must provide either text or a valid file path.")

    whatsapp_package = get_whatsapp_package(serial, business=business)
    if not whatsapp_package:
        if business:
            raise AutomationError(
                "WhatsApp Business is not installed. Expected com.whatsapp.w4b."
            )
        raise AutomationError("WhatsApp is not installed. Expected com.whatsapp.")
    print(f"[*] Using WhatsApp package: {whatsapp_package}")

    run_adb(["shell", "input", "keyevent", "KEYCODE_WAKEUP"], serial=serial)

    if file_path and not os.path.exists(file_path):
        raise ValueError(f"media file not found: {file_path}")

    if file_path:
        mime_type = guessed_mime_type(file_path)
        if should_use_appium_media(mime_type):
            print(
                f"[*] Sending {os.path.basename(file_path)} through "
                f"Appium media picker ({mime_type})..."
            )
            send_media_with_appium(
                serial,
                phone,
                file_path,
                whatsapp_package,
                text=text,
                mime_type=mime_type,
                known_contact=known_contact,
            )
            print("[+] Transmission automated successfully!")
            return

        launch_whatsapp_direct_media(
            serial,
            phone,
            text,
            file_path,
            whatsapp_package,
            mime_type,
        )
        fail_on_contact_picker = True
    else:
        from .chat_navigation import open_chat_via_ui

        if not open_chat_via_ui(serial, phone, whatsapp_package, known_contact):
            launch_whatsapp_text(serial, phone, whatsapp_package)
        fail_on_contact_picker = False

    print("[*] Waiting for WhatsApp UI to settle...")
    time.sleep(3.5)

    if not file_path:
        print("[*] Focusing WhatsApp message field...")
        try:
            message_entry = focus_message_entry(serial, whatsapp_package)
        except AutomationError as exc:
            print(f"[WARN] {exc}")
            launch_whatsapp_prefilled_text(serial, phone, text, whatsapp_package)
            print("[*] Waiting for WhatsApp prefilled text UI to settle...")
            time.sleep(3.5)
        else:
            print("[*] Typing message with human-like pacing...")
            try:
                human_type_text(serial, text, message_entry=message_entry)
            except AutomationError as exc:
                print(f"[WARN] Human-like typing failed; falling back: {exc}")
                clear_message_draft(serial, text)
                launch_whatsapp_prefilled_text(serial, phone, text, whatsapp_package)
                print("[*] Waiting for WhatsApp prefilled text UI to settle...")
                time.sleep(3.5)

    print("[*] Finding WhatsApp send button with uiautomator2...")
    click_send_button(
        serial,
        whatsapp_package,
        fail_on_contact_picker=fail_on_contact_picker,
    )
    print("[+] Transmission automated successfully!")
