import tempfile
import unittest
from unittest.mock import patch

from adb_automation import whatsapp
from adb_automation.config import (
    WHATSAPP_BUSINESS_PACKAGE,
    WHATSAPP_MESSENGER_PACKAGE,
)


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

    def test_send_whatsapp_clicks_uiautomator_send_button(self):
        with patch(
            "adb_automation.whatsapp.get_whatsapp_package",
            return_value=WHATSAPP_MESSENGER_PACKAGE,
        ), patch("adb_automation.whatsapp.run_adb") as run_adb, patch(
            "adb_automation.whatsapp.click_send_button"
        ) as click_send_button, patch(
            "adb_automation.whatsapp.time.sleep"
        ), patch(
            "builtins.print"
        ):
            whatsapp.send_whatsapp(
                "192.168.10.21:5555", "5511999999999", text="hello"
            )

        click_send_button.assert_called_once_with(
            "192.168.10.21:5555",
            WHATSAPP_MESSENGER_PACKAGE,
            fail_on_contact_picker=False,
        )
        adb_commands = [call.args[0] for call in run_adb.call_args_list]
        command_prefixes = [cmd[:3] for cmd in adb_commands]
        self.assertNotIn(["shell", "input", "tap"], command_prefixes)

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
