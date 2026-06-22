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
DEVICE_DOWNLOAD_DIR = "/storage/emulated/0/Download"
CONTACT_PICKER_TEXTS = (
    "Send to",
    "Enviar para",
)


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


def launch_whatsapp_text(serial, phone, text, whatsapp_package):
    print(f"[*] Launching WhatsApp chat intent for +{phone}...")
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


def send_whatsapp(serial, phone, text=None, file_path=None, business=False):
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
        launch_whatsapp_text(serial, phone, text, whatsapp_package)
        fail_on_contact_picker = False

    print("[*] Waiting for WhatsApp UI to settle...")
    time.sleep(3.5)

    print("[*] Finding WhatsApp send button with uiautomator2...")
    click_send_button(
        serial,
        whatsapp_package,
        fail_on_contact_picker=fail_on_contact_picker,
    )
    print("[+] Transmission automated successfully!")
