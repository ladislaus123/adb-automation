import tempfile
import unittest
from unittest.mock import ANY, call, patch

from adb_automation import adb, whatsapp
from adb_automation.config import (
    WHATSAPP_BUSINESS_PACKAGE,
    WHATSAPP_MESSENGER_PACKAGE,
)


def launched_view_urls(adb_commands):
    urls = []
    for command in adb_commands:
        if command[:4] == ["shell", "am", "start", "-a"] and "-d" in command:
            urls.append(command[command.index("-d") + 1])
    return urls


def decode_adb_input_text(value):
    decoded = []
    index = 0
    while index < len(value):
        if value.startswith("%s", index):
            decoded.append(" ")
            index += 2
            continue

        if value[index] == "\\" and index + 1 < len(value):
            decoded.append(value[index + 1])
            index += 2
            continue

        decoded.append(value[index])
        index += 1

    return "".join(decoded)


def replay_adb_text_buffer(adb_commands):
    text = []
    for command in adb_commands:
        if command[:3] == ["shell", "input", "text"]:
            text.extend(decode_adb_input_text(command[3]))
        elif command == ["shell", "input", "keyevent", "KEYCODE_DEL"] and text:
            text.pop()
    return "".join(text)


class FakeUiSelector:
    def __init__(self, exists=False, set_text_error=None, send_keys_error=None):
        self.exists = exists
        self.clicked = False
        self.text_values = []
        self.clear_calls = 0
        self.sent_keys = []
        self.set_text_error = set_text_error
        self.send_keys_error = send_keys_error

    def click(self):
        self.clicked = True

    def set_text(self, text):
        if self.set_text_error is not None:
            raise self.set_text_error
        self.text_values.append(text)

    def clear_text(self):
        self.clear_calls += 1
        self.text_values.append("")

    def send_keys(self, text):
        if self.send_keys_error is not None:
            raise self.send_keys_error
        self.sent_keys.append(text)

    def get_text(self):
        return self.text_values[-1] if self.text_values else ""


class FakeUiDevice:
    def __init__(self):
        self.selectors = {}
        self.calls = []
        self.wait_activity_calls = []

    def add_selector(self, selector_kwargs, exists=True):
        selector = FakeUiSelector(exists=exists)
        self.selectors[self._key(selector_kwargs)] = selector
        return selector

    def wait_activity(self, activity, timeout=None):
        self.wait_activity_calls.append((activity, timeout))
        return True

    def __call__(self, **selector_kwargs):
        self.calls.append(selector_kwargs)
        return self.selectors.get(
            self._key(selector_kwargs), FakeUiSelector(exists=False)
        )

    def _key(self, selector_kwargs):
        return tuple(sorted(selector_kwargs.items()))


class WhatsappPackageTests(unittest.TestCase):
    def test_regular_mode_prefers_messenger_when_both_are_installed(self):
        with patch(
            "adb_automation.whatsapp.run_adb",
            return_value=(
                f"package:{WHATSAPP_MESSENGER_PACKAGE}\n"
                f"package:{WHATSAPP_BUSINESS_PACKAGE}\n"
            ),
        ):
            package = whatsapp.get_whatsapp_package("192.168.10.21:5555")

        self.assertEqual(package, WHATSAPP_MESSENGER_PACKAGE)

    def test_business_mode_selects_business_package(self):
        with patch(
            "adb_automation.whatsapp.run_adb",
            return_value=(
                f"package:{WHATSAPP_MESSENGER_PACKAGE}\n"
                f"package:{WHATSAPP_BUSINESS_PACKAGE}\n"
            ),
        ):
            package = whatsapp.get_whatsapp_package(
                "192.168.10.21:5555", business=True
            )

        self.assertEqual(package, WHATSAPP_BUSINESS_PACKAGE)

    def test_business_mode_requires_business_package(self):
        with patch(
            "adb_automation.whatsapp.run_adb",
            return_value=f"package:{WHATSAPP_MESSENGER_PACKAGE}\n",
        ):
            package = whatsapp.get_whatsapp_package(
                "192.168.10.21:5555", business=True
            )

        self.assertIsNone(package)

    def test_send_whatsapp_raises_specific_error_when_regular_is_not_installed(self):
        with patch("adb_automation.whatsapp.get_whatsapp_package", return_value=None):
            with self.assertRaisesRegex(
                whatsapp.WhatsAppNotInstalledError,
                "WhatsApp is not installed",
            ):
                whatsapp.send_whatsapp(
                    "192.168.10.21:5555",
                    "5511999999999",
                    text="hello",
                )

    def test_send_whatsapp_raises_specific_error_when_business_is_not_installed(self):
        with patch("adb_automation.whatsapp.get_whatsapp_package", return_value=None):
            with self.assertRaisesRegex(
                whatsapp.WhatsAppNotInstalledError,
                "WhatsApp Business is not installed",
            ):
                whatsapp.send_whatsapp(
                    "192.168.10.21:5555",
                    "5511999999999",
                    text="hello",
                    business=True,
                )


class WhatsappSendButtonTests(unittest.TestCase):
    def test_click_send_button_prefers_resource_id(self):
        device = FakeUiDevice()
        target = device.add_selector(
            {"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/send"}
        )
        device.add_selector({"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/entry"})

        whatsapp.click_send_button(
            "192.168.10.21:5555",
            WHATSAPP_MESSENGER_PACKAGE,
            timeout=0,
            device_connector=lambda serial: device,
        )

        self.assertTrue(target.clicked)
        self.assertIn({"resourceId": "com.whatsapp:id/send"}, device.calls)
        self.assertEqual(
            device.wait_activity_calls,
            [("com.whatsapp", whatsapp.WHATSAPP_ACTIVITY_WAIT_SECONDS)],
        )

    def test_click_send_button_falls_back_to_localized_description(self):
        device = FakeUiDevice()
        target = device.add_selector({"description": "Enviar"})
        device.add_selector({"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/entry"})

        whatsapp.click_send_button(
            "192.168.10.21:5555",
            WHATSAPP_MESSENGER_PACKAGE,
            timeout=0,
            device_connector=lambda serial: device,
        )

        self.assertTrue(target.clicked)

    def test_click_send_button_accepts_alternate_send_button_resource_id(self):
        device = FakeUiDevice()
        target = device.add_selector(
            {"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/send_button"}
        )
        device.add_selector({"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/entry"})

        whatsapp.click_send_button(
            "192.168.10.21:5555",
            WHATSAPP_MESSENGER_PACKAGE,
            timeout=0,
            device_connector=lambda serial: device,
        )

        self.assertTrue(target.clicked)

    def test_click_send_button_accepts_alternate_media_send_resource_id(self):
        device = FakeUiDevice()
        target = device.add_selector(
            {"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/send_media_btn"}
        )
        device.add_selector({"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/entry"})

        whatsapp.click_send_button(
            "192.168.10.21:5555",
            WHATSAPP_MESSENGER_PACKAGE,
            timeout=0,
            device_connector=lambda serial: device,
        )

        self.assertTrue(target.clicked)

    def test_click_send_button_uses_typed_field_to_catch_unsent_draft(self):
        # Regression test: on some chat screens the real `:id/entry` compose
        # field isn't matched, and the send-verification selector search
        # falls back to a generic EditText that belongs to a *different*,
        # already-empty widget. Without reusing the exact field we typed
        # into, that false "empty" reading would make click_send_button
        # report success while the real message is still a draft.
        device = FakeUiDevice()
        device.add_selector({"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/send"})
        device.add_selector({"className": "android.widget.EditText"})

        message_entry = FakeUiSelector(exists=True)
        message_entry.text_values = ["still a draft"]

        fake_time = [0.0]

        def fake_monotonic():
            fake_time[0] += 1
            return fake_time[0]

        with patch(
            "adb_automation.whatsapp.time.monotonic", side_effect=fake_monotonic
        ), patch("adb_automation.whatsapp.time.sleep"), self.assertRaisesRegex(
            whatsapp.AutomationError, "may still be a draft"
        ):
            whatsapp.click_send_button(
                "192.168.10.21:5555",
                WHATSAPP_MESSENGER_PACKAGE,
                timeout=0,
                device_connector=lambda serial: device,
                message_entry=message_entry,
            )

    def test_click_send_button_raises_when_element_is_missing(self):
        device = FakeUiDevice()

        with self.assertRaisesRegex(
            whatsapp.AutomationError,
            "Could not find the WhatsApp send button",
        ):
            whatsapp.click_send_button(
                "192.168.10.21:5555",
                WHATSAPP_MESSENGER_PACKAGE,
                timeout=0,
                device_connector=lambda serial: device,
            )

    def test_click_send_button_raises_when_contact_picker_is_visible(self):
        device = FakeUiDevice()
        device.add_selector({"text": "Enviar para"})

        with self.assertRaisesRegex(
            whatsapp.AutomationError,
            "contact picker",
        ):
            whatsapp.click_send_button(
                "192.168.10.21:5555",
                WHATSAPP_MESSENGER_PACKAGE,
                timeout=0,
                fail_on_contact_picker=True,
                device_connector=lambda serial: device,
            )

    def test_click_send_button_raises_restricted_for_portuguese_banner(self):
        device = FakeUiDevice()
        device.add_selector({"text": "Sua conta foi restringida"})

        with self.assertRaisesRegex(
            whatsapp.WhatsAppRestrictedError,
            "^WhatsApp is restricted\\.$",
        ):
            whatsapp.click_send_button(
                "192.168.10.21:5555",
                WHATSAPP_MESSENGER_PACKAGE,
                timeout=0,
                device_connector=lambda serial: device,
            )

    def test_click_send_button_raises_restricted_for_english_popup(self):
        device = FakeUiDevice()
        device.add_selector({"descriptionContains": "Unable to use WhatsApp"})

        with self.assertRaisesRegex(
            whatsapp.WhatsAppRestrictedError,
            "^WhatsApp is restricted\\.$",
        ):
            whatsapp.click_send_button(
                "192.168.10.21:5555",
                WHATSAPP_MESSENGER_PACKAGE,
                timeout=0,
                device_connector=lambda serial: device,
            )

    def test_click_send_button_keyboard_fallback_does_not_retry_when_restricted(self):
        with patch(
            "adb_automation.whatsapp.click_send_button",
            side_effect=whatsapp.WhatsAppRestrictedError(
                "WhatsApp is restricted."
            ),
        ) as click_send_button, patch(
            "adb_automation.whatsapp.run_adb"
        ) as run_adb:
            with self.assertRaisesRegex(
                whatsapp.WhatsAppRestrictedError,
                "^WhatsApp is restricted\\.$",
            ):
                whatsapp.click_send_button_with_keyboard_fallback(
                    "192.168.10.21:5555",
                    WHATSAPP_MESSENGER_PACKAGE,
                )

        click_send_button.assert_called_once_with(
            "192.168.10.21:5555",
            WHATSAPP_MESSENGER_PACKAGE,
            fail_on_contact_picker=False,
            message_entry=None,
            confirm_text=None,
        )
        run_adb.assert_not_called()

    def test_focus_message_entry_prefers_resource_id(self):
        device = FakeUiDevice()
        target = device.add_selector(
            {"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/entry"}
        )

        with patch("adb_automation.whatsapp.time.sleep"):
            whatsapp.focus_message_entry(
                "192.168.10.21:5555",
                WHATSAPP_MESSENGER_PACKAGE,
                timeout=0,
                device_connector=lambda serial: device,
            )

        self.assertTrue(target.clicked)
        self.assertIn({"resourceId": "com.whatsapp:id/entry"}, device.calls)
        self.assertEqual(
            device.wait_activity_calls,
            [("com.whatsapp", whatsapp.WHATSAPP_ACTIVITY_WAIT_SECONDS)],
        )

    def test_focus_message_entry_falls_back_to_edit_text(self):
        device = FakeUiDevice()
        target = device.add_selector({"className": "android.widget.EditText"})

        with patch("adb_automation.whatsapp.time.sleep"):
            whatsapp.focus_message_entry(
                "192.168.10.21:5555",
                WHATSAPP_MESSENGER_PACKAGE,
                timeout=0,
                device_connector=lambda serial: device,
            )

        self.assertTrue(target.clicked)
        self.assertIn({"resourceId": "com.whatsapp:id/entry"}, device.calls)
        self.assertIn({"className": "android.widget.EditText"}, device.calls)

    def test_focus_message_entry_raises_when_missing(self):
        device = FakeUiDevice()

        with patch("adb_automation.whatsapp.time.sleep"), self.assertRaisesRegex(
            whatsapp.AutomationError,
            "message compose field",
        ):
            whatsapp.focus_message_entry(
                "192.168.10.21:5555",
                WHATSAPP_MESSENGER_PACKAGE,
                timeout=0,
                device_connector=lambda serial: device,
            )

    def test_split_adb_safe_text_separates_unicode_spans(self):
        self.assertEqual(
            whatsapp.split_adb_safe_text("Ola você 🙂!"),
            (
                (whatsapp.TEXT_CHUNK_ADB, "Ola voc"),
                (whatsapp.TEXT_CHUNK_UNICODE, "ê"),
                (whatsapp.TEXT_CHUNK_ADB, " "),
                (whatsapp.TEXT_CHUNK_UNICODE, "🙂"),
                (whatsapp.TEXT_CHUNK_ADB, "!"),
            ),
        )

    def test_human_type_text_uses_input_text_backspace_and_preserves_final_text(self):
        adb_commands = []

        def fake_run_adb(command, serial=None):
            adb_commands.append(command)
            return ""

        with patch(
            "adb_automation.whatsapp.run_adb", side_effect=fake_run_adb
        ), patch("adb_automation.whatsapp.time.sleep"):
            whatsapp.human_type_text("192.168.10.21:5555", "hello there")

        self.assertEqual(replay_adb_text_buffer(adb_commands), "hello there")
        self.assertTrue(
            any(command[:3] == ["shell", "input", "text"] for command in adb_commands)
        )
        self.assertTrue(
            any(
                command == ["shell", "input", "keyevent", "KEYCODE_DEL"]
                for command in adb_commands
            )
        )

    def test_human_type_text_inserts_unicode_without_adb_typing_unicode(self):
        adb_commands = []
        message_entry = FakeUiSelector(exists=True)
        text = "Ola, você 🙂 ok"

        def fake_run_adb(command, serial=None):
            adb_commands.append(command)
            return ""

        with patch(
            "adb_automation.whatsapp.run_adb", side_effect=fake_run_adb
        ), patch("adb_automation.whatsapp.time.sleep"):
            whatsapp.human_type_text(
                "192.168.10.21:5555",
                text,
                message_entry=message_entry,
            )

        self.assertEqual(message_entry.text_values[-1], text)
        self.assertIn("Ola, você", message_entry.text_values)
        self.assertIn("Ola, você 🙂", message_entry.text_values)
        text_commands = [
            command
            for command in adb_commands
            if command[:3] == ["shell", "input", "text"]
        ]
        self.assertTrue(text_commands)
        self.assertTrue(all(command[3].isascii() for command in text_commands))
        self.assertFalse(
            any("ê" in command[3] or "🙂" in command[3] for command in text_commands)
        )
        self.assertTrue(
            any(
                command == ["shell", "input", "keyevent", "KEYCODE_DEL"]
                for command in adb_commands
            )
        )

    def test_human_type_text_requires_compose_field_for_unicode(self):
        with self.assertRaisesRegex(
            whatsapp.AutomationError,
            "Unicode text requires",
        ):
            whatsapp.human_type_text("192.168.10.21:5555", "Olá")

    def test_send_whatsapp_types_message_before_clicking_send(self):
        with patch(
            "adb_automation.whatsapp.get_whatsapp_package",
            return_value=WHATSAPP_MESSENGER_PACKAGE,
        ), patch(
            "adb_automation.whatsapp.run_adb", return_value=""
        ) as run_adb, patch(
            "adb_automation.whatsapp.focus_message_entry",
            return_value=FakeUiSelector(exists=True),
        ) as focus_message_entry, patch(
            "adb_automation.whatsapp.click_send_button"
        ) as click_send_button, patch(
            "adb_automation.whatsapp.time.sleep"
        ), patch(
            "builtins.print"
        ):
            whatsapp.send_whatsapp(
                "192.168.10.21:5555", "5511999999999", text="hello there"
            )

        focus_message_entry.assert_called_once_with(
            "192.168.10.21:5555",
            WHATSAPP_MESSENGER_PACKAGE,
        )
        click_send_button.assert_called_once_with(
            "192.168.10.21:5555",
            WHATSAPP_MESSENGER_PACKAGE,
            fail_on_contact_picker=False,
            message_entry=focus_message_entry.return_value,
            confirm_text=ANY,
        )
        adb_commands = [call.args[0] for call in run_adb.call_args_list]
        self.assertEqual(
            launched_view_urls(adb_commands),
            ["https://wa.me/5511999999999"],
        )
        self.assertEqual(replay_adb_text_buffer(adb_commands), "hello there")
        self.assertTrue(
            any(
                command == ["shell", "input", "keyevent", "KEYCODE_DEL"]
                for command in adb_commands
            )
        )

    def test_send_whatsapp_reasserts_portrait_orientation_before_focusing_entry(self):
        events = []
        serial = "192.168.10.21:5555"

        def fake_run_adb(command, serial=None):
            events.append(tuple(command))
            return ""

        def fake_focus_message_entry(serial, whatsapp_package):
            events.append("focus_message_entry")
            return FakeUiSelector(exists=True)

        with patch(
            "adb_automation.whatsapp.get_whatsapp_package",
            return_value=WHATSAPP_MESSENGER_PACKAGE,
        ), patch(
            "adb_automation.whatsapp.run_adb", side_effect=fake_run_adb
        ), patch(
            "adb_automation.whatsapp.focus_message_entry",
            side_effect=fake_focus_message_entry,
        ), patch(
            "adb_automation.whatsapp.click_send_button"
        ), patch(
            "adb_automation.whatsapp.time.sleep"
        ), patch(
            "builtins.print"
        ):
            whatsapp.send_whatsapp(serial, "5511999999999", text="hi")

        fix_rotation_indexes = [
            index
            for index, event in enumerate(events)
            if event
            == ("shell", "cmd", "window", "fixed-to-user-rotation", "enabled")
        ]
        focus_index = events.index("focus_message_entry")

        # Once from the guard entering, once more as a re-assertion right
        # before focusing the compose field (the point the bug was observed).
        self.assertEqual(len(fix_rotation_indexes), 2)
        self.assertLess(fix_rotation_indexes[-1], focus_index)

    def test_send_whatsapp_continues_when_portrait_force_fails(self):
        adb_commands = []
        serial = "192.168.10.21:5555"

        def fake_run_adb(command, serial=None):
            adb_commands.append(command)
            if command == [
                "shell",
                "settings",
                "get",
                "system",
                "accelerometer_rotation",
            ]:
                return "1\n"
            if command == ["shell", "settings", "get", "system", "user_rotation"]:
                return "3\n"
            if command == [
                "shell",
                "settings",
                "put",
                "system",
                "accelerometer_rotation",
                "0",
            ]:
                raise adb.AdbError("rotation denied")
            return ""

        with patch(
            "adb_automation.whatsapp.get_whatsapp_package",
            return_value=WHATSAPP_MESSENGER_PACKAGE,
        ), patch(
            "adb_automation.whatsapp.run_adb", side_effect=fake_run_adb
        ), patch(
            "adb_automation.chat_navigation.open_chat_via_ui",
            return_value=False,
        ), patch(
            "adb_automation.whatsapp.focus_message_entry",
            return_value=FakeUiSelector(exists=True),
        ), patch(
            "adb_automation.whatsapp.click_send_button"
        ) as click_send_button, patch(
            "adb_automation.whatsapp.time.sleep"
        ), patch(
            "builtins.print"
        ):
            whatsapp.send_whatsapp(
                serial,
                "5511999999999",
                text="hello there",
            )

        click_send_button.assert_called_once_with(
            serial,
            WHATSAPP_MESSENGER_PACKAGE,
            fail_on_contact_picker=False,
            message_entry=ANY,
            confirm_text=ANY,
        )
        self.assertEqual(replay_adb_text_buffer(adb_commands), "hello there")
        self.assertIn(
            ["shell", "settings", "put", "system", "accelerometer_rotation", "1"],
            adb_commands,
        )
        self.assertIn(
            ["shell", "settings", "put", "system", "user_rotation", "3"],
            adb_commands,
        )

    def test_send_whatsapp_dismisses_keyboard_and_retries_send_button_for_text(self):
        adb_commands = []
        serial = "192.168.10.21:5555"

        def fake_run_adb(command, serial=None):
            adb_commands.append(command)
            if command == [
                "shell",
                "settings",
                "get",
                "system",
                "accelerometer_rotation",
            ]:
                return "1\n"
            if command == ["shell", "settings", "get", "system", "user_rotation"]:
                return "2\n"
            return ""

        with patch(
            "adb_automation.whatsapp.get_whatsapp_package",
            return_value=WHATSAPP_MESSENGER_PACKAGE,
        ), patch(
            "adb_automation.whatsapp.run_adb", side_effect=fake_run_adb
        ), patch(
            "adb_automation.chat_navigation.open_chat_via_ui",
            return_value=False,
        ), patch(
            "adb_automation.whatsapp.focus_message_entry",
            return_value=FakeUiSelector(exists=True),
        ), patch(
            "adb_automation.whatsapp.click_send_button",
            side_effect=[whatsapp.AutomationError("button hidden"), None],
        ) as click_send_button, patch(
            "adb_automation.whatsapp.time.sleep"
        ), patch(
            "builtins.print"
        ):
            whatsapp.send_whatsapp(
                serial,
                "5511999999999",
                text="hello there",
            )

        self.assertEqual(
            click_send_button.call_args_list,
            [
                call(
                    serial,
                    WHATSAPP_MESSENGER_PACKAGE,
                    fail_on_contact_picker=False,
                    message_entry=ANY,
                    confirm_text=ANY,
                ),
                call(
                    serial,
                    WHATSAPP_MESSENGER_PACKAGE,
                    fail_on_contact_picker=False,
                    message_entry=ANY,
                    confirm_text=ANY,
                ),
            ],
        )
        self.assertIn(
            ["shell", "input", "keyevent", "KEYCODE_BACK"],
            adb_commands,
        )

    def test_send_whatsapp_restores_rotation_after_send_button_retry_fails(self):
        adb_commands = []
        serial = "192.168.10.21:5555"

        def fake_run_adb(command, serial=None):
            adb_commands.append(command)
            if command == [
                "shell",
                "settings",
                "get",
                "system",
                "accelerometer_rotation",
            ]:
                return "0\n"
            if command == ["shell", "settings", "get", "system", "user_rotation"]:
                return "1\n"
            return ""

        with self.assertRaisesRegex(whatsapp.AutomationError, "still hidden"):
            with patch(
                "adb_automation.whatsapp.get_whatsapp_package",
                return_value=WHATSAPP_MESSENGER_PACKAGE,
            ), patch(
                "adb_automation.whatsapp.run_adb", side_effect=fake_run_adb
            ), patch(
                "adb_automation.chat_navigation.open_chat_via_ui",
                return_value=False,
            ), patch(
                "adb_automation.whatsapp.focus_message_entry",
                return_value=FakeUiSelector(exists=True),
            ), patch(
                "adb_automation.whatsapp.click_send_button",
                side_effect=[
                    whatsapp.AutomationError("button hidden"),
                    whatsapp.AutomationError("still hidden"),
                ],
            ), patch(
                "adb_automation.whatsapp.time.sleep"
            ), patch(
                "builtins.print"
            ):
                whatsapp.send_whatsapp(
                    serial,
                    "5511999999999",
                    text="hello there",
                )

        self.assertEqual(
            adb_commands[-4:],
            [
                [
                    "shell",
                    "settings",
                    "put",
                    "system",
                    "accelerometer_rotation",
                    "0",
                ],
                ["shell", "settings", "put", "system", "user_rotation", "1"],
                ["shell", "cmd", "window", "set-ignore-orientation-request", "false"],
                ["shell", "cmd", "window", "fixed-to-user-rotation", "disabled"],
            ],
        )

    def test_send_whatsapp_falls_back_to_prefilled_url_when_entry_is_missing(self):
        with patch(
            "adb_automation.whatsapp.get_whatsapp_package",
            return_value=WHATSAPP_MESSENGER_PACKAGE,
        ), patch(
            "adb_automation.whatsapp.run_adb", return_value=""
        ) as run_adb, patch(
            "adb_automation.whatsapp.focus_message_entry",
            side_effect=whatsapp.AutomationError("compose field missing"),
        ), patch(
            "adb_automation.whatsapp.click_send_button"
        ) as click_send_button, patch(
            "adb_automation.whatsapp.time.sleep"
        ), patch(
            "builtins.print"
        ):
            whatsapp.send_whatsapp(
                "192.168.10.21:5555", "5511999999999", text="hello there"
            )

        click_send_button.assert_called_once_with(
            "192.168.10.21:5555",
            WHATSAPP_MESSENGER_PACKAGE,
            fail_on_contact_picker=False,
            message_entry=None,
            confirm_text=ANY,
        )
        adb_commands = [call.args[0] for call in run_adb.call_args_list]
        self.assertEqual(
            launched_view_urls(adb_commands),
            [
                "https://wa.me/5511999999999",
                "https://wa.me/5511999999999?text=hello%20there",
            ],
        )
        self.assertEqual(replay_adb_text_buffer(adb_commands), "")

    def test_send_whatsapp_does_not_prefilled_fallback_when_entry_is_restricted(self):
        with patch(
            "adb_automation.whatsapp.get_whatsapp_package",
            return_value=WHATSAPP_MESSENGER_PACKAGE,
        ), patch(
            "adb_automation.whatsapp.run_adb", return_value=""
        ), patch(
            "adb_automation.whatsapp.focus_message_entry",
            side_effect=whatsapp.WhatsAppRestrictedError(
                "WhatsApp is restricted."
            ),
        ), patch(
            "adb_automation.whatsapp.launch_whatsapp_prefilled_text"
        ) as launch_whatsapp_prefilled_text, patch(
            "adb_automation.whatsapp.click_send_button"
        ) as click_send_button, patch(
            "adb_automation.whatsapp.time.sleep"
        ), patch(
            "builtins.print"
        ):
            with self.assertRaisesRegex(
                whatsapp.WhatsAppRestrictedError,
                "^WhatsApp is restricted\\.$",
            ):
                whatsapp.send_whatsapp(
                    "192.168.10.21:5555",
                    "5511999999999",
                    text="hello there",
                )

        launch_whatsapp_prefilled_text.assert_not_called()
        click_send_button.assert_not_called()

    def test_send_whatsapp_falls_back_to_prefilled_url_when_typing_fails(self):
        adb_commands = []

        def fake_run_adb(command, serial=None):
            adb_commands.append(command)
            if command[:3] == ["shell", "input", "text"] and "sno" in command[3]:
                raise whatsapp.AutomationError(
                    "java.lang.NullPointerException: "
                    "Attempt to get length of null array"
                )
            return ""

        with patch(
            "adb_automation.whatsapp.get_whatsapp_package",
            return_value=WHATSAPP_MESSENGER_PACKAGE,
        ), patch(
            "adb_automation.whatsapp.run_adb", side_effect=fake_run_adb
        ), patch(
            "adb_automation.whatsapp.focus_message_entry"
        ), patch(
            "adb_automation.whatsapp.click_send_button"
        ) as click_send_button, patch(
            "adb_automation.whatsapp.time.sleep"
        ), patch(
            "builtins.print"
        ):
            whatsapp.send_whatsapp(
                "192.168.10.21:5555", "5511999999999", text="hello snowman"
            )

        click_send_button.assert_called_once_with(
            "192.168.10.21:5555",
            WHATSAPP_MESSENGER_PACKAGE,
            fail_on_contact_picker=False,
            message_entry=None,
            confirm_text=ANY,
        )
        self.assertEqual(
            launched_view_urls(adb_commands),
            [
                "https://wa.me/5511999999999",
                "https://wa.me/5511999999999?text=hello%20snowman",
            ],
        )
        self.assertTrue(
            any(
                command[:3] == ["shell", "input", "keyevent"]
                and command.count("KEYCODE_DEL") >= len("hello snowman")
                for command in adb_commands
            )
        )

    def test_send_whatsapp_falls_back_to_prefilled_url_when_unicode_insert_fails(self):
        adb_commands = []
        message_entry = FakeUiSelector(
            exists=True,
            set_text_error=whatsapp.AutomationError("unicode insert failed"),
            send_keys_error=whatsapp.AutomationError("unicode send_keys failed"),
        )

        def fake_run_adb(command, serial=None):
            adb_commands.append(command)
            return ""

        with patch(
            "adb_automation.whatsapp.get_whatsapp_package",
            return_value=WHATSAPP_MESSENGER_PACKAGE,
        ), patch(
            "adb_automation.whatsapp.run_adb", side_effect=fake_run_adb
        ), patch(
            "adb_automation.whatsapp.focus_message_entry",
            return_value=message_entry,
        ), patch(
            "adb_automation.whatsapp.click_send_button"
        ) as click_send_button, patch(
            "adb_automation.whatsapp.time.sleep"
        ), patch(
            "builtins.print"
        ):
            whatsapp.send_whatsapp(
                "192.168.10.21:5555", "5511999999999", text="Olá 🙂"
            )

        click_send_button.assert_called_once_with(
            "192.168.10.21:5555",
            WHATSAPP_MESSENGER_PACKAGE,
            fail_on_contact_picker=False,
            message_entry=None,
            confirm_text=ANY,
        )
        self.assertEqual(
            launched_view_urls(adb_commands),
            [
                "https://wa.me/5511999999999",
                "https://wa.me/5511999999999?text=Ol%C3%A1%20%F0%9F%99%82",
            ],
        )
        self.assertTrue(
            any(
                command[:3] == ["shell", "input", "keyevent"]
                and command.count("KEYCODE_DEL") >= len("Olá 🙂")
                for command in adb_commands
            )
        )

    def test_send_whatsapp_audio_uses_gallery_picker_flow(self):
        with tempfile.NamedTemporaryFile(suffix=".mp3") as media_file:
            with patch(
                "adb_automation.whatsapp.get_whatsapp_package",
                return_value=WHATSAPP_MESSENGER_PACKAGE,
            ), patch("adb_automation.whatsapp.run_adb", return_value=""), patch(
                "adb_automation.media_picker.send_media_via_gallery_picker"
            ) as send_media_via_gallery_picker, patch(
                "adb_automation.whatsapp.click_send_button"
            ) as click_send_button, patch(
                "adb_automation.whatsapp.time.sleep"
            ), patch(
                "builtins.print"
            ):
                whatsapp.send_whatsapp(
                    "192.168.10.21:5555",
                    "5511999999999",
                    text="caption",
                    file_path=media_file.name,
                )

        send_media_via_gallery_picker.assert_called_once_with(
            "192.168.10.21:5555",
            "5511999999999",
            media_file.name,
            WHATSAPP_MESSENGER_PACKAGE,
            text="caption",
            mime_type="audio/mpeg",
            adb_transport="wifi",
        )
        click_send_button.assert_not_called()

    def test_send_whatsapp_image_uses_gallery_picker_flow(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg") as media_file:
            with patch(
                "adb_automation.whatsapp.get_whatsapp_package",
                return_value=WHATSAPP_MESSENGER_PACKAGE,
            ), patch("adb_automation.whatsapp.run_adb", return_value=""), patch(
                "adb_automation.media_picker.send_media_via_gallery_picker"
            ) as send_media_via_gallery_picker, patch(
                "adb_automation.whatsapp.click_send_button"
            ) as click_send_button, patch(
                "builtins.print"
            ):
                whatsapp.send_whatsapp(
                    "192.168.10.21:5555",
                    "5511999999999",
                    text="caption",
                    file_path=media_file.name,
                )

        send_media_via_gallery_picker.assert_called_once_with(
            "192.168.10.21:5555",
            "5511999999999",
            media_file.name,
            WHATSAPP_MESSENGER_PACKAGE,
            text="caption",
            mime_type="image/jpeg",
            adb_transport="wifi",
        )
        click_send_button.assert_not_called()

    def test_send_whatsapp_video_uses_selected_business_package_with_gallery_picker(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as media_file:
            with patch(
                "adb_automation.whatsapp.get_whatsapp_package",
                return_value=WHATSAPP_BUSINESS_PACKAGE,
            ) as get_whatsapp_package, patch(
                "adb_automation.whatsapp.run_adb", return_value=""
            ), patch(
                "adb_automation.media_picker.send_media_via_gallery_picker"
            ) as send_media_via_gallery_picker, patch(
                "adb_automation.whatsapp.click_send_button"
            ) as click_send_button, patch(
                "adb_automation.whatsapp.time.sleep"
            ), patch(
                "builtins.print"
            ):
                whatsapp.send_whatsapp(
                    "192.168.10.21:5555",
                    "5511999999999",
                    file_path=media_file.name,
                    business=True,
                )

        get_whatsapp_package.assert_called_once_with(
            "192.168.10.21:5555", business=True
        )
        send_media_via_gallery_picker.assert_called_once_with(
            "192.168.10.21:5555",
            "5511999999999",
            media_file.name,
            WHATSAPP_BUSINESS_PACKAGE,
            text=None,
            mime_type="video/mp4",
            adb_transport="wifi",
        )
        click_send_button.assert_not_called()

    def test_send_whatsapp_document_still_uses_direct_media_intent(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as media_file:
            with patch(
                "adb_automation.whatsapp.get_whatsapp_package",
                return_value=WHATSAPP_MESSENGER_PACKAGE,
            ), patch(
                "adb_automation.whatsapp.run_adb", return_value=""
            ) as run_adb, patch(
                "adb_automation.whatsapp.click_send_button"
            ) as click_send_button, patch(
                "adb_automation.whatsapp.time.sleep"
            ), patch(
                "builtins.print"
            ):
                whatsapp.send_whatsapp(
                    "192.168.10.21:5555",
                    "5511999999999",
                    text="caption",
                    file_path=media_file.name,
                )

        adb_commands = [call.args[0] for call in run_adb.call_args_list]
        push_commands = [c for c in adb_commands if c[0] == "push"]
        self.assertEqual(len(push_commands), 1)
        self.assertEqual(push_commands[0][1], media_file.name)
        remote_path = push_commands[0][2]
        self.assertTrue(remote_path.startswith(whatsapp.DEVICE_DOWNLOAD_DIR))

        intent_commands = [
            c for c in adb_commands if c[:4] == ["shell", "am", "start", "-a"]
            and "android.intent.action.SEND" in c
        ]
        self.assertEqual(len(intent_commands), 1)
        intent = intent_commands[0]
        self.assertIn("--grant-read-uri-permission", intent)
        self.assertIn("jid", intent)
        self.assertEqual(intent[intent.index("jid") + 1], "5511999999999@s.whatsapp.net")
        self.assertIn(whatsapp.STREAM_EXTRA, intent)
        self.assertEqual(
            intent[intent.index(whatsapp.STREAM_EXTRA) + 1],
            f"file://{remote_path}",
        )
        self.assertIn("android.intent.extra.TEXT", intent)
        self.assertEqual(intent[intent.index("android.intent.extra.TEXT") + 1], "caption")
        self.assertIn(WHATSAPP_MESSENGER_PACKAGE, intent)

        click_send_button.assert_called_once_with(
            "192.168.10.21:5555",
            WHATSAPP_MESSENGER_PACKAGE,
            fail_on_contact_picker=True,
        )

    def test_send_whatsapp_stops_u2_uiautomator_after_text_send(self):
        with patch(
            "adb_automation.whatsapp.get_whatsapp_package",
            return_value=WHATSAPP_MESSENGER_PACKAGE,
        ), patch(
            "adb_automation.whatsapp.run_adb", return_value=""
        ), patch(
            "adb_automation.whatsapp.focus_message_entry"
        ), patch(
            "adb_automation.whatsapp.click_send_button"
        ), patch(
            "adb_automation.whatsapp.time.sleep"
        ), patch(
            "adb_automation.whatsapp.stop_u2_uiautomator"
        ) as stop_u2_uiautomator, patch(
            "builtins.print"
        ):
            whatsapp.send_whatsapp(
                "192.168.10.21:5555", "5511999999999", text="hello there"
            )

        stop_u2_uiautomator.assert_called_once_with("192.168.10.21:5555")

    def test_send_whatsapp_stops_u2_uiautomator_after_direct_media_intent(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as media_file:
            with patch(
                "adb_automation.whatsapp.get_whatsapp_package",
                return_value=WHATSAPP_MESSENGER_PACKAGE,
            ), patch(
                "adb_automation.whatsapp.run_adb", return_value=""
            ), patch(
                "adb_automation.whatsapp.click_send_button"
            ), patch(
                "adb_automation.whatsapp.time.sleep"
            ), patch(
                "adb_automation.whatsapp.stop_u2_uiautomator"
            ) as stop_u2_uiautomator, patch(
                "builtins.print"
            ):
                whatsapp.send_whatsapp(
                    "192.168.10.21:5555",
                    "5511999999999",
                    text="caption",
                    file_path=media_file.name,
                )

        stop_u2_uiautomator.assert_called_once_with("192.168.10.21:5555")

    def test_send_whatsapp_stops_u2_uiautomator_even_when_send_fails(self):
        with patch(
            "adb_automation.whatsapp.get_whatsapp_package",
            return_value=WHATSAPP_MESSENGER_PACKAGE,
        ), patch(
            "adb_automation.whatsapp.run_adb", return_value=""
        ), patch(
            "adb_automation.whatsapp.focus_message_entry",
            side_effect=whatsapp.AutomationError("boom"),
        ), patch(
            "adb_automation.whatsapp.launch_whatsapp_prefilled_text"
        ), patch(
            "adb_automation.whatsapp.click_send_button_with_keyboard_fallback",
            side_effect=whatsapp.AutomationError("send failed"),
        ), patch(
            "adb_automation.whatsapp.time.sleep"
        ), patch(
            "adb_automation.whatsapp.stop_u2_uiautomator"
        ) as stop_u2_uiautomator, patch(
            "builtins.print"
        ):
            with self.assertRaises(whatsapp.AutomationError):
                whatsapp.send_whatsapp(
                    "192.168.10.21:5555", "5511999999999", text="hello there"
                )

        stop_u2_uiautomator.assert_called_once_with("192.168.10.21:5555")

    def test_send_whatsapp_does_not_stop_u2_uiautomator_for_gallery_picker_flow(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg") as media_file:
            with patch(
                "adb_automation.whatsapp.get_whatsapp_package",
                return_value=WHATSAPP_MESSENGER_PACKAGE,
            ), patch(
                "adb_automation.whatsapp.run_adb", return_value=""
            ), patch(
                "adb_automation.media_picker.send_media_via_gallery_picker"
            ), patch(
                "adb_automation.whatsapp.stop_u2_uiautomator"
            ) as stop_u2_uiautomator, patch(
                "builtins.print"
            ):
                whatsapp.send_whatsapp(
                    "192.168.10.21:5555",
                    "5511999999999",
                    file_path=media_file.name,
                )

        stop_u2_uiautomator.assert_not_called()


class VerifyMessageTypedTests(unittest.TestCase):
    def test_returns_without_retry_when_text_matches_immediately(self):
        message_entry = FakeUiSelector(exists=True)
        message_entry.text_values.append("hello there")

        with patch("adb_automation.whatsapp.time.sleep"):
            whatsapp.verify_message_typed(message_entry, "hello there")

        self.assertEqual(message_entry.text_values, ["hello there"])

    def test_retries_with_direct_set_when_text_is_missing(self):
        message_entry = FakeUiSelector(exists=True)

        with patch("adb_automation.whatsapp.time.sleep"):
            whatsapp.verify_message_typed(message_entry, "hello there")

        self.assertEqual(message_entry.text_values, ["hello there"])

    def test_raises_when_text_still_does_not_match_after_retry(self):
        class StuckUiSelector:
            """set_text() reports success but the on-device text never changes."""

            def __init__(self):
                self.set_text_calls = []

            def get_text(self):
                return "stuck draft"

            def set_text(self, text):
                self.set_text_calls.append(text)

        message_entry = StuckUiSelector()

        with patch("adb_automation.whatsapp.time.sleep"), self.assertRaisesRegex(
            whatsapp.AutomationError,
            "did not match the intended message",
        ):
            whatsapp.verify_message_typed(message_entry, "hello there")

        self.assertEqual(message_entry.set_text_calls, ["hello there"])

    def test_assumes_correct_when_field_cannot_be_read_back(self):
        class Unreadable:
            pass

        message_entry = Unreadable()

        with patch("adb_automation.whatsapp.time.sleep"), patch(
            "builtins.print"
        ) as fake_print:
            whatsapp.verify_message_typed(message_entry, "hello there")

        self.assertTrue(
            any(
                "Could not read the compose field back" in call.args[0]
                for call in fake_print.call_args_list
            )
        )


def _row_xml(pkg, text, with_status=True, status_desc="Entregue"):
    status_node = (
        f'<node resource-id="{pkg}:id/status" class="android.widget.ImageView" '
        f'text="" content-desc="{status_desc}" />'
        if with_status
        else ""
    )
    return (
        "<hierarchy>"
        f'<node resource-id="{pkg}:id/conversation_layout">'
        f'<node resource-id="{pkg}:id/conversation_row">'
        f'<node resource-id="{pkg}:id/message_text" '
        f'class="android.widget.TextView" text="{text}" />'
        f"{status_node}"
        "</node>"
        "</node>"
        "</hierarchy>"
    )


class FakeStatusDevice:
    """Minimal device exposing dump_hierarchy for status confirmation."""

    def __init__(self, xml):
        self._xml = xml
        self.dumps = 0

    def dump_hierarchy(self):
        self.dumps += 1
        return self._xml


class OutgoingStatusPresentTests(unittest.TestCase):
    pkg = WHATSAPP_MESSENGER_PACKAGE

    def test_true_when_matching_bubble_has_status_icon(self):
        xml = _row_xml(self.pkg, "hello there", with_status=True)
        self.assertTrue(
            whatsapp._outgoing_status_present(xml, self.pkg, "hello there")
        )

    def test_false_when_bubble_matches_but_has_no_status_icon(self):
        # A failed/draft row shows a retry icon, not id/status -> not committed.
        xml = _row_xml(self.pkg, "hello there", with_status=False)
        self.assertFalse(
            whatsapp._outgoing_status_present(xml, self.pkg, "hello there")
        )

    def test_false_when_no_bubble_text_matches(self):
        xml = _row_xml(self.pkg, "a different message", with_status=True)
        self.assertFalse(
            whatsapp._outgoing_status_present(xml, self.pkg, "hello there")
        )

    def test_matches_when_target_already_normalized(self):
        # _outgoing_status_present receives an already-normalized target; the
        # bubble side is normalized internally.
        xml = _row_xml(self.pkg, "line one   line two", with_status=True)
        self.assertTrue(
            whatsapp._outgoing_status_present(xml, self.pkg, "line one line two")
        )

    def test_long_message_substring_match_is_trusted(self):
        sent = "Tá chegando, minha gente! Domingo é dia de escolher o Brasil"
        rendered = sent + " "  # trailing whitespace the bubble may add/strip
        xml = _row_xml(self.pkg, rendered, with_status=True)
        self.assertTrue(
            whatsapp._outgoing_status_present(xml, self.pkg, sent)
        )


class ConfirmMessageSentViaStatusTests(unittest.TestCase):
    pkg = WHATSAPP_MESSENGER_PACKAGE

    def test_confirms_when_status_icon_present(self):
        device = FakeStatusDevice(_row_xml(self.pkg, "hello there", True))
        with patch("adb_automation.whatsapp.time.sleep"):
            self.assertTrue(
                whatsapp.confirm_message_sent_via_status(
                    device, self.pkg, "hello there", timeout=1
                )
            )

    def test_returns_false_without_dump_hierarchy(self):
        # A stubbed device (no live tree) must defer to the caller's fallback,
        # and must not sleep/settle.
        class NoDump:
            pass

        with patch("adb_automation.whatsapp.time.sleep") as sleep:
            self.assertFalse(
                whatsapp.confirm_message_sent_via_status(
                    NoDump(), self.pkg, "hello there"
                )
            )
        sleep.assert_not_called()

    def test_returns_false_when_status_never_appears(self):
        device = FakeStatusDevice(_row_xml(self.pkg, "hello there", False))
        with patch("adb_automation.whatsapp.time.sleep"):
            self.assertFalse(
                whatsapp.confirm_message_sent_via_status(
                    device, self.pkg, "hello there", timeout=0
                )
            )

    def test_confirms_multiline_message_after_newline_normalization(self):
        # The bubble renders the multi-paragraph message on one line; the entry
        # point normalizes the sent text before matching.
        device = FakeStatusDevice(
            _row_xml(self.pkg, "line one line two", with_status=True)
        )
        with patch("adb_automation.whatsapp.time.sleep"):
            self.assertTrue(
                whatsapp.confirm_message_sent_via_status(
                    device, self.pkg, "line one\n\nline two", timeout=1
                )
            )

    def test_settles_before_reading_tree(self):
        device = FakeStatusDevice(_row_xml(self.pkg, "hello there", True))
        with patch("adb_automation.whatsapp.time.sleep") as sleep:
            whatsapp.confirm_message_sent_via_status(
                device, self.pkg, "hello there", timeout=1, settle=1.2
            )
        # The settle delay guards against a previous job's screen being read.
        self.assertIn(1.2, [c.args[0] for c in sleep.call_args_list if c.args])


class ConfirmTextSendTests(unittest.TestCase):
    pkg = WHATSAPP_MESSENGER_PACKAGE

    def test_status_confirmation_short_circuits_compose_check(self):
        # The status tick confirms the send even when the compose-field read
        # would wrongly report "not empty" (the placeholder-hint false negative).
        device = FakeStatusDevice(_row_xml(self.pkg, "hello there", True))
        with patch("adb_automation.whatsapp.time.sleep"), patch(
            "adb_automation.whatsapp.wait_for_message_entry_cleared"
        ) as fallback:
            result = whatsapp._confirm_text_send(
                device, self.pkg, "hello there", message_entry=None
            )
        self.assertTrue(result)
        fallback.assert_not_called()

    def test_falls_back_to_compose_check_when_status_unavailable(self):
        class NoDump:
            pass

        with patch("adb_automation.whatsapp.time.sleep"), patch(
            "adb_automation.whatsapp.wait_for_message_entry_cleared",
            return_value=True,
        ) as fallback:
            result = whatsapp._confirm_text_send(
                NoDump(), self.pkg, "hello there", message_entry=None
            )
        self.assertTrue(result)
        fallback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
