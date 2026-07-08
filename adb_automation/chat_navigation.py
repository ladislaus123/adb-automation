import time

from .adb import run_adb
from .whatsapp import (
    connect_uiautomator_device,
    normalize_phone,
    selector_exists,
)

HOME_READY_TIMEOUT_SECONDS = 8
HOME_RETRY_TIMEOUT_SECONDS = 4
HOME_QUICK_CHECK_SECONDS = 2
HOME_BACK_ATTEMPTS = 3
NAV_STEP_TIMEOUT_SECONDS = 8
SNACKBAR_CHAT_TIMEOUT_SECONDS = 8
SNACKBAR_POLL_INTERVAL_SECONDS = 0.2
SEARCH_RESULT_TIMEOUT_SECONDS = 8
CHAT_OPEN_VERIFY_TIMEOUT_SECONDS = 10
POLL_INTERVAL_SECONDS = 0.25
FORCE_STOP_SETTLE_SECONDS = 1
TYPE_SETTLE_SECONDS = 0.3
NUMBER_VALIDATION_SETTLE_SECONDS = 2
SEARCH_SETTLE_SECONDS = 1.5
SEARCH_SUFFIX_DIGITS = 8
RESULT_ROW_MAX_INSTANCES = 6

NEW_CHAT_FAB_TEXTS = (
    "Nova conversa",
    "New chat",
    "Enviar mensagem",
    "Send message",
)
NEW_CONTACT_ROW_TEXTS = ("Novo contato", "New contact")
CONTACT_PHONE_FIELD_TEXTS = ("Telefone", "Phone")
CONTACT_SAVE_TEXTS = ("SALVAR", "Salvar", "SAVE", "Save")
SNACKBAR_CHAT_TEXTS = ("Conversar", "Chat", "Message")
HOME_SEARCH_DESCRIPTIONS = ("Pesquisar", "Search")
PERMISSION_ALLOW_TEXTS = ("Permitir", "PERMITIR", "Allow", "ALLOW")
NON_CHAT_SEARCH_ACTION_TEXTS = (
    "CONVIDAR",
    "Convidar",
    "INVITE",
    "Invite",
)
NOT_ON_WHATSAPP_TEXTS = (
    "não está no WhatsApp",
    "isn't on WhatsApp",
    "is not on WhatsApp",
)
COUNTRY_CODE_TEXT_PATTERN = r"[A-Z]{2} \+\d+.*"
COUNTRY_CODE_DESCRIPTIONS = ("código do país", "country code")
HOME_ACTIVITY_COMPONENTS = (
    "com.whatsapp.HomeActivity",
    "com.whatsapp.home.ui.HomeActivity",
)


def digits_only(value):
    return "".join(char for char in str(value or "") if char.isdigit())


def strip_country_code(digits, cc_digits):
    if not cc_digits or not digits.startswith(cc_digits):
        return None
    local_digits = digits[len(cc_digits):]
    return local_digits or None


def phone_matches_row_text(row_text, digits):
    row_digits = digits_only(row_text)
    if not row_digits or not digits:
        return False
    if row_digits == digits:
        return True
    return (
        len(row_digits) >= SEARCH_SUFFIX_DIGITS
        and len(digits) >= SEARCH_SUFFIX_DIGITS
        and row_digits[-SEARCH_SUFFIX_DIGITS:] == digits[-SEARCH_SUFFIX_DIGITS:]
    )


def new_chat_fab_selectors(whatsapp_package):
    return (
        {"resourceId": f"{whatsapp_package}:id/fab"},
        {"resourceId": f"{whatsapp_package}:id/fabText"},
        *({"description": text} for text in NEW_CHAT_FAB_TEXTS),
        *({"text": text} for text in NEW_CHAT_FAB_TEXTS),
    )


def contact_picker_marker_selectors(whatsapp_package):
    return (
        {"resourceId": f"{whatsapp_package}:id/contact_picker_layout"},
        {"resourceId": f"{whatsapp_package}:id/contactpicker_row_name"},
    )


def new_contact_row_selectors(whatsapp_package):
    return (
        *(
            {
                "resourceId": f"{whatsapp_package}:id/contactpicker_row_name",
                "text": text,
            }
            for text in NEW_CONTACT_ROW_TEXTS
        ),
        *({"text": text} for text in NEW_CONTACT_ROW_TEXTS),
    )


def contact_form_marker_selectors(whatsapp_package):
    return (
        {"resourceId": f"{whatsapp_package}:id/contact_form_fields"},
        {"resourceId": f"{whatsapp_package}:id/phone_input_layout"},
        {"resourceId": f"{whatsapp_package}:id/first_name_input_layout"},
    )


def contact_phone_field_selectors():
    return tuple(
        {"className": "android.widget.EditText", "text": text}
        for text in CONTACT_PHONE_FIELD_TEXTS
    )


def contact_save_button_selectors(whatsapp_package):
    return (
        {"resourceId": f"{whatsapp_package}:id/keyboard_aware_save_button"},
        *({"text": text} for text in CONTACT_SAVE_TEXTS),
    )


def snackbar_chat_selectors(whatsapp_package):
    return (
        *(
            {"resourceId": f"{whatsapp_package}:id/snackbar_action", "text": text}
            for text in SNACKBAR_CHAT_TEXTS
        ),
        {"resourceId": f"{whatsapp_package}:id/snackbar_action"},
    )


def home_marker_selectors(whatsapp_package):
    return (
        {"resourceId": f"{whatsapp_package}:id/fab"},
        {"resourceId": f"{whatsapp_package}:id/fabText"},
        {"resourceId": f"{whatsapp_package}:id/search_bar_inner_layout"},
        {"resourceId": f"{whatsapp_package}:id/my_search_bar"},
    )


def home_search_selectors(whatsapp_package):
    return (
        {"resourceId": f"{whatsapp_package}:id/search_bar_inner_layout"},
        {"resourceId": f"{whatsapp_package}:id/search_text"},
        *(
            {"descriptionContains": description}
            for description in HOME_SEARCH_DESCRIPTIONS
        ),
    )


def focused_edit_selectors():
    return (
        {"className": "android.widget.EditText", "focused": True},
        {"focused": True},
    )


def search_result_name_resource_ids(whatsapp_package):
    return (
        f"{whatsapp_package}:id/conversations_row_contact_name",
        f"{whatsapp_package}:id/conversation_contact_name",
        f"{whatsapp_package}:id/contactpicker_row_name",
        f"{whatsapp_package}:id/name",
        f"{whatsapp_package}:id/row_container",
    )


def search_result_row_container_ids(whatsapp_package):
    return (
        f"{whatsapp_package}:id/row_container",
        f"{whatsapp_package}:id/contact_row_container",
        f"{whatsapp_package}:id/contactpicker_row_container",
    )


def search_result_photo_ids(whatsapp_package):
    return (
        f"{whatsapp_package}:id/photo",
        f"{whatsapp_package}:id/contact_photo",
        f"{whatsapp_package}:id/contactpicker_row_photo",
    )


def chat_entry_marker_selectors(whatsapp_package):
    return (
        {"resourceId": f"{whatsapp_package}:id/entry"},
        {"resourceId": f"{whatsapp_package}:id/mentionable_entry"},
        {"resourceIdMatches": r".*:id/entry"},
        {"resourceIdMatches": r".*:id/mentionable_entry"},
    )


def dialog_dismiss_selectors(whatsapp_package):
    return (
        {"resourceId": "com.android.permissioncontroller:id/permission_allow_button"},
        *({"text": text} for text in PERMISSION_ALLOW_TEXTS),
        {"resourceId": f"{whatsapp_package}:id/dismiss_icon"},
    )


def not_on_whatsapp_selectors():
    return tuple({"textContains": text} for text in NOT_ON_WHATSAPP_TEXTS)


def number_not_on_whatsapp_form_selectors(whatsapp_package):
    return (
        *(
            {
                "resourceId": f"{whatsapp_package}:id/number_on_whatsapp_message",
                "textContains": text,
            }
            for text in NOT_ON_WHATSAPP_TEXTS
        ),
        *(
            {
                "resourceId": f"{whatsapp_package}:id/number_on_whatsapp_action",
                "textContains": text,
            }
            for text in ("Convidar", "Invite")
        ),
    )


def non_chat_search_action_selectors(whatsapp_package):
    return (
        *(
            {"resourceId": f"{whatsapp_package}:id/action_btn", "text": text}
            for text in NON_CHAT_SEARCH_ACTION_TEXTS
        ),
        *({"text": text} for text in NON_CHAT_SEARCH_ACTION_TEXTS),
    )


def country_code_field_selectors(whatsapp_package):
    return (
        {
            "className": "android.widget.EditText",
            "textMatches": COUNTRY_CODE_TEXT_PATTERN,
        },
        *(
            {"descriptionContains": description}
            for description in COUNTRY_CODE_DESCRIPTIONS
        ),
    )


def run_silent_adb(command, serial, run_adb_command=run_adb):
    try:
        return run_adb_command(command, serial=serial)
    except Exception as exc:
        print(f"[WARN] Best-effort adb command failed ({command}): {exc}")
        return None


def selector_text(selector):
    get_text = getattr(selector, "get_text", None)
    if callable(get_text):
        try:
            text = get_text() or ""
            if text:
                return text
        except Exception:
            pass

    try:
        info = getattr(selector, "info", None)
        if callable(info):
            info = info()
        if isinstance(info, dict):
            return (
                info.get("text")
                or info.get("contentDescription")
                or info.get("content-desc")
                or ""
            )
    except Exception:
        pass

    return ""


def selector_content_desc(selector):
    try:
        info = getattr(selector, "info", None)
        if callable(info):
            info = info()
        if isinstance(info, dict):
            return info.get("contentDescription") or info.get("content-desc") or ""
    except Exception:
        pass
    return ""


def selector_bounds(selector):
    try:
        info = getattr(selector, "info", None)
        if callable(info):
            info = info()
        if isinstance(info, dict):
            bounds = info.get("bounds")
            if isinstance(bounds, dict) and all(
                key in bounds for key in ("left", "top", "right", "bottom")
            ):
                return bounds
    except Exception:
        pass
    return None


def tap_element(selector, serial, run_adb_command=run_adb):
    try:
        selector.click()
        return True
    except Exception as exc:
        print(f"[WARN] Direct click failed ({exc}); trying coordinate tap.")

    bounds = selector_bounds(selector)
    if bounds is None:
        return False

    center_x = (bounds["left"] + bounds["right"]) // 2
    center_y = (bounds["top"] + bounds["bottom"]) // 2
    return (
        run_silent_adb(
            ["shell", "input", "tap", str(center_x), str(center_y)],
            serial,
            run_adb_command=run_adb_command,
        )
        is not None
    )


def has_non_chat_search_action(device, whatsapp_package):
    for selector_kwargs in non_chat_search_action_selectors(whatsapp_package):
        try:
            if selector_exists(device(**selector_kwargs)):
                return True
        except Exception:
            continue
    return False


def click_first_existing(device, selectors, timeout, interval=POLL_INTERVAL_SECONDS):
    deadline = time.monotonic() + timeout
    while True:
        for selector_kwargs in selectors:
            try:
                selector = device(**selector_kwargs)
                if selector_exists(selector):
                    selector.click()
                    return True
            except Exception:
                continue

        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def wait_for_any(
    device,
    selectors,
    timeout,
    interval=POLL_INTERVAL_SECONDS,
    whatsapp_package=None,
):
    deadline = time.monotonic() + timeout
    while True:
        if whatsapp_package:
            dismiss_interrupting_dialogs(device, whatsapp_package)

        for selector_kwargs in selectors:
            try:
                selector = device(**selector_kwargs)
                if selector_exists(selector):
                    return selector
            except Exception:
                continue

        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


def dismiss_interrupting_dialogs(device, whatsapp_package):
    dismissed = False
    for selector_kwargs in dialog_dismiss_selectors(whatsapp_package):
        try:
            selector = device(**selector_kwargs)
            if selector_exists(selector):
                selector.click()
                dismissed = True
        except Exception:
            continue
    return dismissed


def detect_not_on_whatsapp_popup(device):
    for selector_kwargs in not_on_whatsapp_selectors():
        try:
            if selector_exists(device(**selector_kwargs)):
                return True
        except Exception:
            continue
    return False


def dump_navigation_debug(device, label):
    try:
        dump_hierarchy = getattr(device, "dump_hierarchy", None)
        if not callable(dump_hierarchy):
            return None
        filename = f"debug_nav_{label}.xml"
        with open(filename, "w", encoding="utf-8") as handle:
            handle.write(dump_hierarchy())
        print(f"[DEBUG] Navigation UI dumped to {filename}")
        return filename
    except Exception as exc:
        print(f"[WARN] Could not dump navigation UI: {exc}")
        return None


def reset_whatsapp_for_fallback(serial, whatsapp_package, run_adb_command=run_adb):
    run_silent_adb(
        ["shell", "am", "force-stop", whatsapp_package],
        serial,
        run_adb_command=run_adb_command,
    )
    time.sleep(FORCE_STOP_SETTLE_SECONDS)


def abort_navigation(serial, device, whatsapp_package, label, run_adb_command=run_adb):
    print(f"[WARN] Contact navigation step failed: {label}")
    dump_navigation_debug(device, label)
    reset_whatsapp_for_fallback(serial, whatsapp_package, run_adb_command=run_adb_command)
    return False


def grant_contacts_permissions(serial, whatsapp_package, run_adb_command=run_adb):
    for permission in ("android.permission.READ_CONTACTS", "android.permission.WRITE_CONTACTS"):
        run_silent_adb(
            ["shell", "pm", "grant", whatsapp_package, permission],
            serial,
            run_adb_command=run_adb_command,
        )


def whatsapp_home_visible(device, whatsapp_package, timeout):
    return (
        wait_for_any(
            device,
            home_marker_selectors(whatsapp_package),
            timeout,
            whatsapp_package=whatsapp_package,
        )
        is not None
    )


def ensure_whatsapp_home(
    serial,
    device,
    whatsapp_package,
    run_adb_command=run_adb,
    timeout=HOME_READY_TIMEOUT_SECONDS,
):
    # Fast path: already on the chat list — no restart needed.
    if whatsapp_home_visible(device, whatsapp_package, HOME_QUICK_CHECK_SECONDS):
        return True

    # Cheap path: bring WhatsApp to the front and step back to the chat list.
    # A force-stop cold-reloads the whole app (several seconds); pressing BACK
    # out of a chat/form reaches home instantly when WhatsApp is already open.
    run_silent_adb(
        ["shell", "monkey", "-p", whatsapp_package, "-c", "android.intent.category.LAUNCHER", "1"],
        serial,
        run_adb_command=run_adb_command,
    )
    if whatsapp_home_visible(device, whatsapp_package, HOME_RETRY_TIMEOUT_SECONDS):
        return True
    for _ in range(HOME_BACK_ATTEMPTS):
        run_silent_adb(
            ["shell", "input", "keyevent", "KEYCODE_BACK"],
            serial,
            run_adb_command=run_adb_command,
        )
        if whatsapp_home_visible(device, whatsapp_package, HOME_QUICK_CHECK_SECONDS):
            return True

    # Last resort: cold restart for a guaranteed clean home.
    run_silent_adb(
        ["shell", "am", "force-stop", whatsapp_package],
        serial,
        run_adb_command=run_adb_command,
    )
    time.sleep(FORCE_STOP_SETTLE_SECONDS)

    launch_commands = (
        ["shell", "monkey", "-p", whatsapp_package, "-c", "android.intent.category.LAUNCHER", "1"],
        *(
            ["shell", "am", "start", "-n", f"{whatsapp_package}/{component}"]
            for component in HOME_ACTIVITY_COMPONENTS
        ),
    )

    for index, command in enumerate(launch_commands):
        run_silent_adb(command, serial, run_adb_command=run_adb_command)
        attempt_timeout = timeout if index == 0 else min(timeout, HOME_RETRY_TIMEOUT_SECONDS)
        marker = wait_for_any(
            device,
            home_marker_selectors(whatsapp_package),
            attempt_timeout,
            whatsapp_package=whatsapp_package,
        )
        if marker is not None:
            return True

    return False


def read_country_code_digits(device, whatsapp_package):
    for selector_kwargs in country_code_field_selectors(whatsapp_package):
        try:
            selector = device(**selector_kwargs)
            if selector_exists(selector):
                digits = digits_only(selector_text(selector))
                if digits:
                    return digits
        except Exception:
            continue

    try:
        layout = device(resourceId=f"{whatsapp_package}:id/country_code_selector")
        if selector_exists(layout):
            child = layout.child(className="android.widget.EditText")
            if selector_exists(child):
                digits = digits_only(selector_text(child))
                if digits:
                    return digits
    except Exception:
        pass

    return None


def find_contact_phone_field(device, whatsapp_package):
    for selector_kwargs in contact_phone_field_selectors():
        try:
            selector = device(**selector_kwargs)
            if selector_exists(selector):
                return selector
        except Exception:
            continue

    try:
        layout = device(resourceId=f"{whatsapp_package}:id/phone_input_layout")
        if selector_exists(layout):
            child = layout.child(className="android.widget.EditText")
            if selector_exists(child):
                return child
    except Exception:
        pass

    return None


def phone_field_reader(device, whatsapp_package):
    # The typed field can no longer be re-queried by its placeholder text, so
    # read it back by structure instead: the EditText inside phone_input_layout.
    try:
        layout = device(resourceId=f"{whatsapp_package}:id/phone_input_layout")
        if selector_exists(layout):
            child = layout.child(className="android.widget.EditText")
            if selector_exists(child):
                return child
    except Exception:
        pass

    for selector_kwargs in focused_edit_selectors():
        try:
            selector = device(**selector_kwargs)
            if selector_exists(selector):
                return selector
        except Exception:
            continue

    return None


def enter_contact_phone_number(
    serial,
    device,
    whatsapp_package,
    field,
    digits,
    run_adb_command=run_adb,
):
    try:
        field.click()
    except Exception:
        pass

    try:
        field.set_text(digits)
    except Exception:
        run_silent_adb(
            ["shell", "input", "text", digits],
            serial,
            run_adb_command=run_adb_command,
        )
    time.sleep(TYPE_SETTLE_SECONDS)

    reader = phone_field_reader(device, whatsapp_package)
    if reader is None:
        # set_text raised no error; proceed and let the form validation and
        # SALVAR/Conversar steps catch a genuine failure. Never re-type blind:
        # adb `input text` appends, which is what corrupted the field before.
        print("[WARN] Could not read the phone field back; assuming typed text is correct.")
        return True

    if digits_only(selector_text(reader)) == digits:
        return True

    try:
        reader.clear_text()
        reader.set_text(digits)
    except Exception as exc:
        print(f"[WARN] Could not retype the phone number: {exc}")
        return False
    time.sleep(TYPE_SETTLE_SECONDS)
    return digits_only(selector_text(reader)) == digits


def detect_number_not_on_whatsapp_form(device, whatsapp_package):
    for selector_kwargs in number_not_on_whatsapp_form_selectors(whatsapp_package):
        try:
            if selector_exists(device(**selector_kwargs)):
                return True
        except Exception:
            continue
    return False


def tap_conversar_after_save(
    serial, device, whatsapp_package, digits, run_adb_command=run_adb
):
    deadline = time.monotonic() + SNACKBAR_CHAT_TIMEOUT_SECONDS
    while True:
        if detect_not_on_whatsapp_popup(device):
            return False

        for selector_kwargs in snackbar_chat_selectors(whatsapp_package):
            try:
                selector = device(**selector_kwargs)
                if selector_exists(selector):
                    return tap_element(
                        selector, serial, run_adb_command=run_adb_command
                    )
            except Exception:
                continue

        if time.monotonic() >= deadline:
            break
        time.sleep(SNACKBAR_POLL_INTERVAL_SECONDS)

    # Snackbar missed: WhatsApp is back on the contact picker where the new
    # contact now has its own row.
    row = find_matching_result_row(device, whatsapp_package, digits)
    if row is not None:
        return tap_element(row, serial, run_adb_command=run_adb_command)
    return False


def first_existing_selector(device, resource_ids, instance):
    for resource_id in resource_ids:
        try:
            selector = device(resourceId=resource_id, instance=instance)
            if selector_exists(selector):
                return selector
        except Exception:
            continue
    return None


def result_row_container(device, whatsapp_package, instance):
    return first_existing_selector(
        device, search_result_row_container_ids(whatsapp_package), instance
    )


def result_row_name_selector(device, whatsapp_package, instance):
    return first_existing_selector(
        device, search_result_name_resource_ids(whatsapp_package), instance
    )


def result_row_digits(device, whatsapp_package, instance):
    name_selector = result_row_name_selector(device, whatsapp_package, instance)
    if name_selector is not None:
        digits = digits_only(selector_text(name_selector))
        if digits:
            return digits

    photo = first_existing_selector(
        device, search_result_photo_ids(whatsapp_package), instance
    )
    if photo is not None:
        digits = digits_only(selector_content_desc(photo))
        if digits:
            return digits

    return ""


def find_matching_result_row(
    device,
    whatsapp_package,
    digits,
    allow_first_visible=False,
):
    # An invite/CONVIDAR action means the searched number is not a WhatsApp
    # contact; there is no chat to open, so fall back to the link route.
    if has_non_chat_search_action(device, whatsapp_package):
        return None

    exact_match = None
    suffix_match = None
    first_visible_result = None

    for instance in range(RESULT_ROW_MAX_INSTANCES):
        container = result_row_container(device, whatsapp_package, instance)
        name_selector = result_row_name_selector(device, whatsapp_package, instance)
        if container is None and name_selector is None:
            break

        # Always click the clickable row container when present; the name node
        # is not clickable and u2 raises trying to interact with it.
        target = container if container is not None else name_selector
        row_digits = result_row_digits(device, whatsapp_package, instance)

        if not row_digits:
            if allow_first_visible and first_visible_result is None:
                first_visible_result = target
            continue
        if row_digits == digits and exact_match is None:
            exact_match = target
        elif phone_matches_row_text(row_digits, digits) and suffix_match is None:
            suffix_match = target

    if exact_match is not None:
        return exact_match
    if suffix_match is not None:
        return suffix_match
    if allow_first_visible:
        return first_visible_result
    return None


def create_contact_and_open_chat(
    serial,
    device,
    whatsapp_package,
    digits,
    run_adb_command=run_adb,
):
    if not click_first_existing(
        device, new_chat_fab_selectors(whatsapp_package), NAV_STEP_TIMEOUT_SECONDS
    ):
        return abort_navigation(
            serial, device, whatsapp_package, "new_chat_fab", run_adb_command
        )

    if wait_for_any(
        device,
        contact_picker_marker_selectors(whatsapp_package),
        NAV_STEP_TIMEOUT_SECONDS,
        whatsapp_package=whatsapp_package,
    ) is None:
        return abort_navigation(
            serial, device, whatsapp_package, "contact_picker", run_adb_command
        )

    if not click_first_existing(
        device, new_contact_row_selectors(whatsapp_package), NAV_STEP_TIMEOUT_SECONDS
    ):
        return abort_navigation(
            serial, device, whatsapp_package, "new_contact_row", run_adb_command
        )

    if wait_for_any(
        device,
        contact_form_marker_selectors(whatsapp_package),
        NAV_STEP_TIMEOUT_SECONDS,
        whatsapp_package=whatsapp_package,
    ) is None:
        return abort_navigation(
            serial, device, whatsapp_package, "contact_form", run_adb_command
        )

    country_code = read_country_code_digits(device, whatsapp_package)
    local_digits = strip_country_code(digits, country_code) if country_code else None
    if not local_digits:
        print(
            "[WARN] Contact navigation aborted: phone "
            f"+{digits} does not match the form country code ({country_code})."
        )
        reset_whatsapp_for_fallback(
            serial, whatsapp_package, run_adb_command=run_adb_command
        )
        return False

    field = find_contact_phone_field(device, whatsapp_package)
    if field is None:
        return abort_navigation(
            serial, device, whatsapp_package, "phone_field", run_adb_command
        )

    if not enter_contact_phone_number(
        serial,
        device,
        whatsapp_package,
        field,
        local_digits,
        run_adb_command=run_adb_command,
    ):
        return abort_navigation(
            serial, device, whatsapp_package, "phone_typing", run_adb_command
        )

    # The form validates the number live; "não está no WhatsApp" means the
    # target has no account (or the field content is wrong) — the link route
    # is the same terminal state legacy behavior produces for such numbers.
    time.sleep(NUMBER_VALIDATION_SETTLE_SECONDS)
    if detect_number_not_on_whatsapp_form(device, whatsapp_package):
        return abort_navigation(
            serial, device, whatsapp_package, "number_not_on_whatsapp", run_adb_command
        )

    if not click_first_existing(
        device, contact_save_button_selectors(whatsapp_package), NAV_STEP_TIMEOUT_SECONDS
    ):
        # The keyboard may cover the button; one back-press dismisses it.
        run_silent_adb(
            ["shell", "input", "keyevent", "KEYCODE_BACK"],
            serial,
            run_adb_command=run_adb_command,
        )
        if not click_first_existing(
            device,
            contact_save_button_selectors(whatsapp_package),
            NAV_STEP_TIMEOUT_SECONDS,
        ):
            return abort_navigation(
                serial, device, whatsapp_package, "save_button", run_adb_command
            )

    if not tap_conversar_after_save(
        serial, device, whatsapp_package, digits, run_adb_command=run_adb_command
    ):
        return abort_navigation(
            serial, device, whatsapp_package, "conversar", run_adb_command
        )

    return True


def open_known_chat_via_search(
    serial,
    device,
    whatsapp_package,
    digits,
    run_adb_command=run_adb,
):
    if not click_first_existing(
        device, home_search_selectors(whatsapp_package), NAV_STEP_TIMEOUT_SECONDS
    ):
        return abort_navigation(
            serial, device, whatsapp_package, "search_bar", run_adb_command
        )

    if wait_for_any(
        device, focused_edit_selectors(), NAV_STEP_TIMEOUT_SECONDS
    ) is None:
        return abort_navigation(
            serial, device, whatsapp_package, "search_field", run_adb_command
        )

    query = digits[-SEARCH_SUFFIX_DIGITS:]
    run_silent_adb(
        ["shell", "input", "text", query],
        serial,
        run_adb_command=run_adb_command,
    )
    time.sleep(SEARCH_SETTLE_SECONDS)

    deadline = time.monotonic() + SEARCH_RESULT_TIMEOUT_SECONDS
    while True:
        row = find_matching_result_row(
            device,
            whatsapp_package,
            digits,
            allow_first_visible=True,
        )
        if row is not None:
            if tap_element(row, serial, run_adb_command=run_adb_command):
                return True
            return abort_navigation(
                serial, device, whatsapp_package, "search_result", run_adb_command
            )

        if time.monotonic() >= deadline:
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    return abort_navigation(
        serial, device, whatsapp_package, "search_result", run_adb_command
    )


def wait_for_message_entry(
    device,
    whatsapp_package,
    timeout=CHAT_OPEN_VERIFY_TIMEOUT_SECONDS,
):
    return (
        wait_for_any(
            device,
            chat_entry_marker_selectors(whatsapp_package),
            timeout,
        )
        is not None
    )


def open_chat_via_ui(
    serial,
    phone,
    whatsapp_package,
    known_contact,
    device_connector=None,
    run_adb_command=run_adb,
):
    """Open the chat for `phone` by driving the WhatsApp UI.

    Returns True only when the chat is open and verified. Returns False on
    any failure so the caller can run the wa.me link route; never raises.
    """
    if known_contact is None:
        return False

    try:
        digits = normalize_phone(phone)
    except ValueError as exc:
        print(f"[WARN] Contact navigation skipped; invalid phone: {exc}")
        return False

    if device_connector is None:
        device_connector = connect_uiautomator_device
    try:
        device = device_connector(serial)
    except Exception as exc:
        print(f"[WARN] Contact navigation unavailable; using link route: {exc}")
        return False

    try:
        if not known_contact:
            grant_contacts_permissions(
                serial, whatsapp_package, run_adb_command=run_adb_command
            )

        if not ensure_whatsapp_home(
            serial, device, whatsapp_package, run_adb_command=run_adb_command
        ):
            return abort_navigation(
                serial, device, whatsapp_package, "home", run_adb_command
            )

        if known_contact:
            opened = open_known_chat_via_search(
                serial, device, whatsapp_package, digits, run_adb_command=run_adb_command
            )
        else:
            opened = create_contact_and_open_chat(
                serial, device, whatsapp_package, digits, run_adb_command=run_adb_command
            )
        if not opened:
            return False

        if not wait_for_message_entry(device, whatsapp_package):
            return abort_navigation(
                serial, device, whatsapp_package, "chat_verify", run_adb_command
            )

        route = "contact search" if known_contact else "new contact"
        print(f"[+] Chat with +{digits} opened via {route} navigation.")
        return True
    except Exception as exc:
        print(f"[WARN] Contact navigation failed; using link route: {exc}")
        dump_navigation_debug(device, "unexpected")
        reset_whatsapp_for_fallback(
            serial, whatsapp_package, run_adb_command=run_adb_command
        )
        return False
