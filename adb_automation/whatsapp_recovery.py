"""Device-side UI automation for the WhatsApp ban recovery flow.

Three jobs, all driven through the raw uiautomator-dump primitives in adb_ui.py
(so they are unit-testable without a live device or uiautomator2):

1. request_account_review  -- tap "Pedir analise" / "Request a review" on the
   restricted screen and submit the appeal.
2. registration_state      -- classify the current WhatsApp screen so the worker
   knows whether the review is still pending, the number can be registered again,
   the account is permanently banned, or we are already logged in.
3. perform_relogin         -- re-register the device's own number; WhatsApp
   auto-fills the SMS code (it holds READ_SMS on the device). read_sms_otp is a
   best-effort fallback used only if auto-fill does not complete in time.

The selector text tables below are deliberately broad (English + Brazilian
Portuguese) and are expected to be tuned against a real banned device; each can
be overridden with a comma-separated env var so tuning is a config change, not a
code change. Use capture_debug_dump() to grab the live screen XML while tuning.
"""

import os
import re
import time

from .adb import run_adb
from .adb_ui import dump_ui_xml, parse_ui_dump, tap_element
from .config import DEFAULT_OTP_WAIT_SECONDS, OTP_WAIT_SECONDS_ENV_VAR, env_int
from .errors import OtpNotReceivedError, ReviewUnavailableError, WhatsAppRecoveryError

# --- Screen text selector tables (casefold substring match) -------------------
REVIEW_BUTTON_TEXTS = (
    "Pedir análise",
    "Pedir analise",
    "Solicitar análise",
    "Solicitar revisão",
    "Request a review",
    "Request review",
)
REVIEW_SUBMIT_TEXTS = (
    "Enviar",
    "Submit",
    "Next",
    "Avançar",
    "Avancar",
    "Continuar",
    "Continue",
    "Confirmar",
    "Confirm",
    "Sim",
    "Yes",
    "OK",
)
REVIEW_PENDING_TEXTS = (
    "Estamos analisando",
    "análise em andamento",
    "analise em andamento",
    "under review",
    "reviewing your account",
    "We are reviewing",
)
PERMANENT_BAN_TEXTS = (
    "não tem mais permissão",
    "nao tem mais permissao",
    "banido",
    "You're not allowed to use WhatsApp",
    "no longer allowed to use WhatsApp",
    "not allowed to use WhatsApp",
)
AGREE_TEXTS = (
    "Agree and continue",
    "Concordar e continuar",
    "Aceitar e continuar",
)
REGISTRATION_TEXTS = (
    "Verify your phone number",
    "Enter your phone number",
    "Confirme seu número",
    "Confirme seu numero",
    "Insira seu número de telefone",
    "Insira seu numero de telefone",
)
# Markers that the chat list / home screen is showing (i.e. we are logged in).
# The bare word "WhatsApp" is intentionally not here: it also appears as a
# contact name and would classify a chat as the home screen.
HOME_TEXTS = (
    "Conversas",
    "Chats",
)
HOME_RESOURCE_SUFFIXES = (
    "fab",  # the floating "new chat" button only exists on the home screen
    "menuitem_search",
    "conversations_row_contact_name",
)
# Phone-number entry field on the registration screen.
PHONE_FIELD_RESOURCE_SUFFIXES = (
    "registration_phone",
    "phone_field",
    "phone",
)
COUNTRY_CODE_RESOURCE_SUFFIXES = (
    "registration_cc",
)
SUBMIT_RESOURCE_SUFFIXES = (
    "registration_submit",
)
# National length used when the country field is empty and the stored number
# includes a calling-code prefix. Brazilian mobiles are 55 + 11 digits.
NATIONAL_NUMBER_DIGITS = 11

OTP_CODE_PATTERN = re.compile(r"\b(\d{3}[\s-]?\d{3})\b")
# "code" alone is too broad ("bank code") and would hide a later WhatsApp SMS.
WHATSAPP_SMS_HINTS = ("whatsapp",)
OTP_SMS_HINTS = ("código", "codigo")

OPEN_SETTLE_SECONDS = 2.5
ACTION_SETTLE_SECONDS = 1.5
LOGIN_POLL_INTERVAL_SECONDS = 3


def _env_texts(env_var, default):
    raw = os.environ.get(env_var)
    if not raw or not raw.strip():
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _selector_texts(env_var, default):
    return _env_texts(env_var, default)


def _casefold(value):
    return " ".join(str(value or "").split()).casefold()


def element_text_blob(element):
    return " ".join(
        _casefold(element.get(field))
        for field in ("text", "content_desc")
    )


def find_element_by_texts(elements, texts):
    """First element whose text or content-desc contains any of `texts`."""
    wanted = [_casefold(text) for text in texts if text]
    for element in elements:
        blob = element_text_blob(element)
        if not blob:
            continue
        if any(text and text in blob for text in wanted):
            return element
    return None


def find_element_by_resource_suffixes(elements, suffixes):
    for element in elements:
        resource_id = element.get("resource_id") or ""
        if any(resource_id.endswith(f":id/{suffix}") for suffix in suffixes):
            return element
    return None


def any_text_present(elements, texts):
    return find_element_by_texts(elements, texts) is not None


def dump_elements(serial, adb_transport="wifi", run_adb_command=run_adb, sleep=time.sleep):
    xml_text = dump_ui_xml(
        serial,
        run_adb_command=run_adb_command,
        sleep=sleep,
        adb_transport=adb_transport,
    )
    return parse_ui_dump(xml_text)


def open_whatsapp(serial, whatsapp_package, run_adb_command=run_adb, sleep=time.sleep):
    """Bring WhatsApp to the foreground via the launcher intent."""
    run_adb_command(
        [
            "shell",
            "monkey",
            "-p",
            whatsapp_package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        ],
        serial=serial,
    )
    sleep(OPEN_SETTLE_SECONDS)


# --- Screen classification ----------------------------------------------------
RECOVERY_SCREEN_LOGGED_IN = "logged_in"
RECOVERY_SCREEN_RESTRICTED = "restricted"
RECOVERY_SCREEN_REVIEW_PENDING = "review_pending"
RECOVERY_SCREEN_PERMANENT_BAN = "permanent_ban"
RECOVERY_SCREEN_CAN_REGISTER = "can_register"
RECOVERY_SCREEN_UNKNOWN = "unknown"


def classify_elements(elements):
    """Classify a parsed screen into one RECOVERY_SCREEN_* state.

    Order matters: permanent ban and review-pending are checked before the
    generic restricted/registration markers because the ban/review screens also
    carry restriction-like wording.
    """
    from .whatsapp import WHATSAPP_RESTRICTED_TEXTS

    if any_text_present(elements, _selector_texts("ADB_AUTOMATION_PERMANENT_BAN_TEXTS", PERMANENT_BAN_TEXTS)):
        return RECOVERY_SCREEN_PERMANENT_BAN
    if any_text_present(elements, _selector_texts("ADB_AUTOMATION_REVIEW_PENDING_TEXTS", REVIEW_PENDING_TEXTS)):
        return RECOVERY_SCREEN_REVIEW_PENDING
    if any_text_present(elements, _selector_texts("ADB_AUTOMATION_REVIEW_BUTTON_TEXTS", REVIEW_BUTTON_TEXTS)):
        return RECOVERY_SCREEN_RESTRICTED
    if any_text_present(elements, WHATSAPP_RESTRICTED_TEXTS):
        return RECOVERY_SCREEN_RESTRICTED
    if any_text_present(elements, _selector_texts("ADB_AUTOMATION_REGISTRATION_TEXTS", REGISTRATION_TEXTS)) or any_text_present(elements, _selector_texts("ADB_AUTOMATION_AGREE_TEXTS", AGREE_TEXTS)):
        return RECOVERY_SCREEN_CAN_REGISTER
    if find_element_by_resource_suffixes(elements, HOME_RESOURCE_SUFFIXES) is not None:
        return RECOVERY_SCREEN_LOGGED_IN
    if any_text_present(elements, _selector_texts("ADB_AUTOMATION_HOME_TEXTS", HOME_TEXTS)):
        return RECOVERY_SCREEN_LOGGED_IN
    return RECOVERY_SCREEN_UNKNOWN


def registration_state(
    serial,
    whatsapp_package,
    adb_transport="wifi",
    run_adb_command=run_adb,
    sleep=time.sleep,
    open_app=True,
):
    if open_app:
        open_whatsapp(serial, whatsapp_package, run_adb_command=run_adb_command, sleep=sleep)
    elements = dump_elements(
        serial, adb_transport=adb_transport, run_adb_command=run_adb_command, sleep=sleep
    )
    return classify_elements(elements)


# --- Requesting the review ("pedir analise") ----------------------------------
def request_account_review(
    serial,
    whatsapp_package,
    adb_transport="wifi",
    run_adb_command=run_adb,
    sleep=time.sleep,
):
    """Tap the review button on the restricted screen and submit the appeal.

    Returns the resulting RECOVERY_SCREEN_* state. Raises ReviewUnavailableError
    if no review action can be found.
    """
    open_whatsapp(serial, whatsapp_package, run_adb_command=run_adb_command, sleep=sleep)
    elements = dump_elements(
        serial, adb_transport=adb_transport, run_adb_command=run_adb_command, sleep=sleep
    )

    state = classify_elements(elements)
    if state in (
        RECOVERY_SCREEN_REVIEW_PENDING,
        RECOVERY_SCREEN_CAN_REGISTER,
        RECOVERY_SCREEN_LOGGED_IN,
        RECOVERY_SCREEN_PERMANENT_BAN,
    ):
        # Nothing to tap: the appeal is already in, registration is open, the
        # account is already logged in, or the ban cannot be appealed.
        return state

    review_button = find_element_by_texts(
        elements, _selector_texts("ADB_AUTOMATION_REVIEW_BUTTON_TEXTS", REVIEW_BUTTON_TEXTS)
    )
    if review_button is None:
        raise ReviewUnavailableError(
            "Could not find a 'request a review' button on the restricted screen."
        )
    tap_element(serial, review_button, run_adb_command=run_adb_command)
    sleep(ACTION_SETTLE_SECONDS)

    # The review may present a confirmation / form screen with a submit button.
    _tap_through_submit(serial, adb_transport, run_adb_command, sleep)

    return registration_state(
        serial,
        whatsapp_package,
        adb_transport=adb_transport,
        run_adb_command=run_adb_command,
        sleep=sleep,
        open_app=False,
    )


def _tap_through_submit(serial, adb_transport, run_adb_command, sleep, max_taps=3):
    """Best-effort: click any submit/continue button on the post-review screens."""
    for _ in range(max_taps):
        elements = dump_elements(
            serial, adb_transport=adb_transport, run_adb_command=run_adb_command, sleep=sleep
        )
        state = classify_elements(elements)
        if state in (
            RECOVERY_SCREEN_REVIEW_PENDING,
            RECOVERY_SCREEN_CAN_REGISTER,
            RECOVERY_SCREEN_LOGGED_IN,
            RECOVERY_SCREEN_PERMANENT_BAN,
        ):
            return
        submit = find_element_by_texts(
            elements, _selector_texts("ADB_AUTOMATION_REVIEW_SUBMIT_TEXTS", REVIEW_SUBMIT_TEXTS)
        )
        if submit is None:
            submit = find_element_by_resource_suffixes(elements, SUBMIT_RESOURCE_SUFFIXES)
        if submit is None:
            return
        tap_element(serial, submit, run_adb_command=run_adb_command)
        sleep(ACTION_SETTLE_SECONDS)


# --- Re-login / re-registration ----------------------------------------------
def otp_wait_seconds():
    return env_int(OTP_WAIT_SECONDS_ENV_VAR, DEFAULT_OTP_WAIT_SECONDS)


def split_country_and_national(digits, existing_country_code=""):
    """Split a stored E.164 number into the registration form's two fields.

    When the country field already shows a calling code and the stored number
    starts with it, that prefix is stripped. An empty country field with a
    Brazilian 55 prefix (12 or 13 digits total) keeps 55 as the country code.
    Otherwise a number longer than a national number yields its leading digits
    as the country code and the last 11 as the national number.
    """
    digits = "".join(char for char in str(digits or "") if char.isdigit())
    country = "".join(char for char in str(existing_country_code or "") if char.isdigit())
    if country and digits.startswith(country) and len(digits) > len(country):
        return country, digits[len(country):]
    if country:
        return country, digits
    if digits.startswith("55") and len(digits) in (12, 13):
        return "55", digits[2:]
    if len(digits) > NATIONAL_NUMBER_DIGITS:
        return digits[:-NATIONAL_NUMBER_DIGITS], digits[-NATIONAL_NUMBER_DIGITS:]
    return "", digits


def perform_relogin(
    serial,
    whatsapp_package,
    phone,
    adb_transport="wifi",
    run_adb_command=run_adb,
    sleep=time.sleep,
    monotonic=None,
):
    """Re-register `phone` on the device and confirm we land logged in.

    WhatsApp is expected to auto-fill the SMS code (it holds READ_SMS). If the
    home screen is not reached within otp_wait_seconds(), read_sms_otp is tried
    as a best-effort fallback. Raises OtpNotReceivedError if login is never
    confirmed.
    """
    if not phone:
        raise WhatsAppRecoveryError(
            "device has no whatsapp_phone configured for re-login."
        )
    digits = "".join(ch for ch in str(phone) if ch.isdigit())

    open_whatsapp(serial, whatsapp_package, run_adb_command=run_adb_command, sleep=sleep)
    _tap_text(serial, adb_transport, run_adb_command, sleep,
              _selector_texts("ADB_AUTOMATION_AGREE_TEXTS", AGREE_TEXTS))

    _enter_phone_number(serial, digits, adb_transport, run_adb_command, sleep)

    submit_texts = _selector_texts("ADB_AUTOMATION_REVIEW_SUBMIT_TEXTS", REVIEW_SUBMIT_TEXTS)
    _tap_text(
        serial, adb_transport, run_adb_command, sleep, submit_texts,
        resource_suffixes=SUBMIT_RESOURCE_SUFFIXES,
    )
    # A confirm dialog ("Is this number correct?") often follows the number.
    _tap_text(serial, adb_transport, run_adb_command, sleep, submit_texts)

    if _wait_for_login(
        serial, whatsapp_package, adb_transport, run_adb_command, sleep, monotonic=monotonic
    ):
        return RECOVERY_SCREEN_LOGGED_IN

    # Fallback: WhatsApp did not auto-fill. Try reading the code off the device.
    code = read_sms_otp(serial, run_adb_command=run_adb_command)
    if code:
        _type_otp_code(serial, code, adb_transport, run_adb_command, sleep)
        if _wait_for_login(
            serial, whatsapp_package, adb_transport, run_adb_command, sleep, monotonic=monotonic
        ):
            return RECOVERY_SCREEN_LOGGED_IN

    raise OtpNotReceivedError(
        "Re-login was not confirmed: WhatsApp did not reach the home screen and "
        "no SMS code could be auto-filled or read back in time."
    )


def _tap_text(serial, adb_transport, run_adb_command, sleep, texts, resource_suffixes=()):
    elements = dump_elements(
        serial, adb_transport=adb_transport, run_adb_command=run_adb_command, sleep=sleep
    )
    element = find_element_by_texts(elements, texts)
    if element is None and resource_suffixes:
        element = find_element_by_resource_suffixes(elements, resource_suffixes)
    if element is None:
        return False
    tap_element(serial, element, run_adb_command=run_adb_command)
    sleep(ACTION_SETTLE_SECONDS)
    return True


def element_digits(element):
    return "".join(char for char in str((element or {}).get("text") or "") if char.isdigit())


def _replace_field_digits(serial, digits, run_adb_command, existing_digits=""):
    """Clear a focused field, then type `digits`.

    `adb shell input text` appends, so leftover characters from a previous
    attempt would corrupt the number. Move to the end and delete first.
    """
    deletes = max(len(existing_digits) + 2, 16)
    run_adb_command(
        ["shell", "input", "keyevent", "123", *["67"] * deletes],
        serial=serial,
    )
    if digits:
        run_adb_command(["shell", "input", "text", digits], serial=serial)


def _enter_phone_number(serial, digits, adb_transport, run_adb_command, sleep):
    elements = dump_elements(
        serial, adb_transport=adb_transport, run_adb_command=run_adb_command, sleep=sleep
    )
    country_field = find_element_by_resource_suffixes(elements, COUNTRY_CODE_RESOURCE_SUFFIXES)
    phone_field = find_element_by_resource_suffixes(elements, PHONE_FIELD_RESOURCE_SUFFIXES)
    if phone_field is None:
        # Country code is usually the first EditText and the phone the last.
        edits = [
            element for element in elements
            if str(element.get("class_name") or "").endswith("EditText")
            and element is not country_field
        ]
        phone_field = edits[-1] if edits else None

    existing_country = element_digits(country_field) if country_field else ""
    country, national = split_country_and_national(digits, existing_country)
    if country_field is not None and country and country != existing_country:
        tap_element(serial, country_field, run_adb_command=run_adb_command)
        sleep(0.4)
        _replace_field_digits(serial, country, run_adb_command, existing_country)
        sleep(0.3)
    if phone_field is not None:
        tap_element(serial, phone_field, run_adb_command=run_adb_command)
        sleep(0.4)
        _replace_field_digits(
            serial, national, run_adb_command, element_digits(phone_field)
        )
    else:
        _replace_field_digits(serial, national, run_adb_command, "")
    sleep(ACTION_SETTLE_SECONDS)


def _type_otp_code(serial, code, adb_transport, run_adb_command, sleep):
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    run_adb_command(["shell", "input", "text", digits], serial=serial)
    sleep(ACTION_SETTLE_SECONDS)


def _wait_for_login(
    serial, whatsapp_package, adb_transport, run_adb_command, sleep, monotonic=None
):
    clock = monotonic or time.monotonic
    deadline = clock() + otp_wait_seconds()
    while True:
        elements = dump_elements(
            serial, adb_transport=adb_transport, run_adb_command=run_adb_command, sleep=sleep
        )
        if classify_elements(elements) == RECOVERY_SCREEN_LOGGED_IN:
            return True
        if clock() >= deadline:
            return False
        sleep(LOGIN_POLL_INTERVAL_SECONDS)


def read_sms_otp(serial, run_adb_command=run_adb):
    """Best-effort: read the most recent WhatsApp SMS and extract the code.

    Depends on the device's `shell` user being allowed to read content://sms;
    returns None cleanly (never raises) when that is not permitted, so the
    primary "rely on WhatsApp auto-fill" path is unaffected.
    """
    try:
        output = run_adb_command(
            [
                "shell",
                "content",
                "query",
                "--uri",
                "content://sms/inbox",
                "--projection",
                "address:body:date",
                "--sort",
                "date DESC",
            ],
            serial=serial,
        )
    except Exception:
        return None
    return extract_otp_from_sms_dump(output)


def extract_otp_from_sms_dump(output):
    """Pull a 6-digit WhatsApp verification code out of a `content query`
    dump of content://sms.

    A row that names WhatsApp wins over an earlier unrelated SMS, even when
    that SMS also contains the word "code". Portuguese "código" rows are next.
    Any other 6-digit code is only a last resort.
    """
    if not output:
        return None
    whatsapp_code = None
    hinted_code = None
    fallback = None
    for line in str(output).splitlines():
        match = OTP_CODE_PATTERN.search(line)
        if not match:
            continue
        code = re.sub(r"[\s-]", "", match.group(1))
        lowered = line.casefold()
        if any(hint in lowered for hint in WHATSAPP_SMS_HINTS):
            if whatsapp_code is None:
                whatsapp_code = code
            continue
        if any(hint in lowered for hint in OTP_SMS_HINTS):
            if hinted_code is None:
                hinted_code = code
            continue
        if fallback is None:
            fallback = code
    return whatsapp_code or hinted_code or fallback


def capture_debug_dump(serial, label, directory=None, adb_transport="wifi",
                       run_adb_command=run_adb, sleep=time.sleep):
    """Save the current screen's uiautomator XML for offline selector tuning.

    Returns the path written. Mirrors the repo's debug_nav_*.xml captures.
    """
    xml_text = dump_ui_xml(
        serial, run_adb_command=run_adb_command, sleep=sleep, adb_transport=adb_transport
    )
    directory = directory or os.getcwd()
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(label))
    path = os.path.join(directory, f"debug_recovery_{safe}.xml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(xml_text)
    return path
