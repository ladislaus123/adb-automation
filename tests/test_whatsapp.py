import tempfile
import unittest
from unittest.mock import call, patch

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

        whatsapp.click_send_button(
            "192.168.10.21:5555",
            WHATSAPP_MESSENGER_PACKAGE,
            timeout=0,
            device_connector=lambda serial: device,
        )

        self.assertTrue(target.clicked)

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
            "adb_automation.whatsapp.focus_message_entry"
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
                ),
                call(
                    serial,
                    WHATSAPP_MESSENGER_PACKAGE,
                    fail_on_contact_picker=False,
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


if __name__ == "__main__":
    unittest.main()
