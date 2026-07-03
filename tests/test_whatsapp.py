import tempfile
import unittest
from unittest.mock import patch

from adb_automation import whatsapp
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
    def __init__(self, exists=False):
        self.exists = exists
        self.clicked = False

    def click(self):
        self.clicked = True


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

    def test_send_whatsapp_types_message_before_clicking_send(self):
        with patch(
            "adb_automation.whatsapp.get_whatsapp_package",
            return_value=WHATSAPP_MESSENGER_PACKAGE,
        ), patch("adb_automation.whatsapp.run_adb") as run_adb, patch(
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

    def test_send_whatsapp_falls_back_to_prefilled_url_when_entry_is_missing(self):
        with patch(
            "adb_automation.whatsapp.get_whatsapp_package",
            return_value=WHATSAPP_MESSENGER_PACKAGE,
        ), patch("adb_automation.whatsapp.run_adb") as run_adb, patch(
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

    def test_send_whatsapp_audio_uses_appium_media_sender(self):
        with tempfile.NamedTemporaryFile(suffix=".mp3") as media_file:
            with patch(
                "adb_automation.whatsapp.get_whatsapp_package",
                return_value=WHATSAPP_MESSENGER_PACKAGE,
            ), patch("adb_automation.whatsapp.run_adb") as run_adb, patch(
                "adb_automation.whatsapp.click_send_button"
            ) as click_send_button, patch(
                "adb_automation.whatsapp.send_media_with_appium"
            ) as send_media_with_appium, patch(
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

        send_media_with_appium.assert_called_once_with(
            "192.168.10.21:5555",
            "5511999999999",
            media_file.name,
            WHATSAPP_MESSENGER_PACKAGE,
            text="caption",
            mime_type="audio/mpeg",
        )
        click_send_button.assert_not_called()
        self.assertEqual(
            [call.args[0] for call in run_adb.call_args_list],
            [["shell", "input", "keyevent", "KEYCODE_WAKEUP"]],
        )

    def test_send_whatsapp_image_uses_appium_media_sender(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg") as media_file:
            with patch(
                "adb_automation.whatsapp.get_whatsapp_package",
                return_value=WHATSAPP_MESSENGER_PACKAGE,
            ), patch("adb_automation.whatsapp.run_adb") as run_adb, patch(
                "adb_automation.whatsapp.click_send_button"
            ) as click_send_button, patch(
                "adb_automation.whatsapp.send_media_with_appium"
            ) as send_media_with_appium, patch(
                "builtins.print"
            ):
                whatsapp.send_whatsapp(
                    "192.168.10.21:5555",
                    "5511999999999",
                    text="caption",
                    file_path=media_file.name,
                )

        send_media_with_appium.assert_called_once_with(
            "192.168.10.21:5555",
            "5511999999999",
            media_file.name,
            WHATSAPP_MESSENGER_PACKAGE,
            text="caption",
            mime_type="image/jpeg",
        )
        click_send_button.assert_not_called()
        self.assertEqual(
            [call.args[0] for call in run_adb.call_args_list],
            [["shell", "input", "keyevent", "KEYCODE_WAKEUP"]],
        )

    def test_send_whatsapp_video_uses_selected_business_package_with_appium(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as media_file:
            with patch(
                "adb_automation.whatsapp.get_whatsapp_package",
                return_value=WHATSAPP_BUSINESS_PACKAGE,
            ) as get_whatsapp_package, patch(
                "adb_automation.whatsapp.run_adb"
            ), patch(
                "adb_automation.whatsapp.click_send_button"
            ) as click_send_button, patch(
                "adb_automation.whatsapp.send_media_with_appium"
            ) as send_media_with_appium, patch(
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
        send_media_with_appium.assert_called_once_with(
            "192.168.10.21:5555",
            "5511999999999",
            media_file.name,
            WHATSAPP_BUSINESS_PACKAGE,
            text=None,
            mime_type="video/mp4",
        )
        click_send_button.assert_not_called()


if __name__ == "__main__":
    unittest.main()
