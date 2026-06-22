import tempfile
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from adb_automation import appium_media
from adb_automation.config import WHATSAPP_BUSINESS_PACKAGE
from adb_automation.errors import AutomationError


class FakeElement:
    def __init__(self):
        self.clicked = False
        self.sent_keys = []

    def click(self):
        self.clicked = True

    def send_keys(self, text):
        self.sent_keys.append(text)


class FakeDriver:
    def __init__(self, elements=None):
        self.elements = elements or {}
        self.calls = []
        self.scripts = []
        self.quit_called = False
        self.page_source = "<hierarchy />"

    def find_element(self, by, value):
        self.calls.append((by, value))
        element = self.elements.get((by, value))
        if element is None:
            raise Exception(f"missing element: {by} {value}")
        return element

    def execute_script(self, script, payload):
        self.scripts.append((script, payload))

    def get_window_size(self):
        return {"width": 1000, "height": 2000}

    def quit(self):
        self.quit_called = True


class AppiumMediaUiTests(unittest.TestCase):
    def test_send_latest_visible_media_clicks_attach_media_caption_and_send(self):
        attach = FakeElement()
        media = FakeElement()
        caption = FakeElement()
        send = FakeElement()
        driver = FakeDriver(
            {
                ("id", f"{WHATSAPP_BUSINESS_PACKAGE}:id/input_attach_button"): attach,
                (
                    "xpath",
                    f"(//*[@resource-id='{WHATSAPP_BUSINESS_PACKAGE}:id/media_item_view'])[1]",
                ): media,
                ("id", f"{WHATSAPP_BUSINESS_PACKAGE}:id/caption"): caption,
                ("id", f"{WHATSAPP_BUSINESS_PACKAGE}:id/send"): send,
            }
        )

        with patch("adb_automation.appium_media.time.sleep"), patch(
            "builtins.print"
        ):
            appium_media.send_latest_visible_media(
                driver,
                WHATSAPP_BUSINESS_PACKAGE,
                caption="hello caption",
            )

        self.assertTrue(attach.clicked)
        self.assertTrue(media.clicked)
        self.assertTrue(caption.clicked)
        self.assertEqual(caption.sent_keys, ["hello caption"])
        self.assertTrue(send.clicked)

    def test_send_latest_visible_media_falls_back_to_bottom_right_tap(self):
        driver = FakeDriver(
            {
                (
                    "id",
                    f"{WHATSAPP_BUSINESS_PACKAGE}:id/input_attach_button",
                ): FakeElement(),
                (
                    "xpath",
                    f"(//*[@resource-id='{WHATSAPP_BUSINESS_PACKAGE}:id/media_item_view'])[1]",
                ): FakeElement(),
            }
        )

        with patch("adb_automation.appium_media.time.sleep"), patch(
            "adb_automation.appium_media.dump_ui"
        ) as dump_ui, patch("builtins.print"):
            appium_media.send_latest_visible_media(
                driver,
                WHATSAPP_BUSINESS_PACKAGE,
                send_timeout=0,
            )

        dump_ui.assert_called_once_with(driver, "debug_send_not_found.xml")
        self.assertEqual(
            driver.scripts,
            [("mobile: clickGesture", {"x": 900, "y": 1840})],
        )

    def test_send_media_with_appium_quits_driver(self):
        driver = FakeDriver()
        factory_calls = []
        cleanup_commands = []
        serial = "192.168.10.21:5555"
        remote_path = "/sdcard/DCIM/Camera/IMG_20260616_193045.jpg"

        def driver_factory(serial, server_url):
            factory_calls.append((serial, server_url))
            return driver

        def fake_run_adb(command, serial=None):
            cleanup_commands.append((command, serial))
            return ""

        with patch(
            "adb_automation.appium_media.stage_latest_media",
            return_value=remote_path,
        ), patch("adb_automation.appium_media.open_whatsapp_chat"), patch(
            "adb_automation.appium_media.send_latest_visible_media"
        ) as send_latest_visible_media, patch("builtins.print"):
            appium_media.send_media_with_appium(
                serial,
                "5511999999999",
                "/tmp/image.jpg",
                WHATSAPP_BUSINESS_PACKAGE,
                text="caption",
                mime_type="image/jpeg",
                appium_server="http://appium.local:4723",
                run_adb_command=fake_run_adb,
                driver_factory=driver_factory,
            )

        self.assertEqual(
            factory_calls,
            [(serial, "http://appium.local:4723")],
        )
        send_latest_visible_media.assert_called_once_with(
            driver,
            WHATSAPP_BUSINESS_PACKAGE,
            caption="caption",
        )
        self.assertEqual(
            cleanup_commands,
            [
                (["shell", "rm", "-f", remote_path], serial),
                (
                    [
                        "shell",
                        "am",
                        "broadcast",
                        "-a",
                        "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                        "-d",
                        f"file://{remote_path}",
                    ],
                    serial,
                ),
            ],
        )
        self.assertTrue(driver.quit_called)


class AppiumMediaStagingTests(unittest.TestCase):
    def test_cleanup_staged_media_is_best_effort(self):
        commands = []

        def fake_run_adb(command, serial=None):
            commands.append((command, serial))
            if command[:3] == ["shell", "rm", "-f"]:
                raise AutomationError("rm failed")
            return ""

        with patch("builtins.print"):
            appium_media.cleanup_staged_media(
                "192.168.10.21:5555",
                "/sdcard/DCIM/Camera/IMG_20260616_193045.jpg",
                run_adb_command=fake_run_adb,
            )

        self.assertEqual(len(commands), 2)

    def test_stage_latest_image_uses_fresh_file_and_cleans_it_up(self):
        fixed_now = datetime(2026, 6, 16, 19, 30, 45)
        commands = []
        removed = []

        def fake_run_adb(command, serial=None):
            commands.append((command, serial))
            if command[:3] == ["shell", "toybox", "touch"]:
                raise AutomationError("touch failed")
            return ""

        with tempfile.NamedTemporaryFile(suffix=".jpg") as media_file, patch(
            "builtins.print"
        ):
            remote_path = appium_media.stage_latest_media(
                "192.168.10.21:5555",
                media_file.name,
                "image/jpeg",
                run_adb_command=fake_run_adb,
                now_provider=lambda: fixed_now,
                fresh_image_factory=lambda path: "/tmp/fresh-media.jpg",
                remove_local_file=removed.append,
                wait_after_push=0,
            )

        self.assertEqual(
            remote_path,
            "/sdcard/DCIM/Camera/IMG_20260616_193045.jpg",
        )
        self.assertEqual(
            commands[0],
            (
                [
                    "push",
                    "/tmp/fresh-media.jpg",
                    "/sdcard/DCIM/Camera/IMG_20260616_193045.jpg",
                ],
                "192.168.10.21:5555",
            ),
        )
        self.assertEqual(
            commands[1][0],
            [
                "shell",
                "toybox",
                "touch",
                "-t",
                "202606161930.45",
                "/sdcard/DCIM/Camera/IMG_20260616_193045.jpg",
            ],
        )
        self.assertEqual(commands[2][0][0:4], ["shell", "am", "broadcast", "-a"])
        self.assertEqual(removed, ["/tmp/fresh-media.jpg"])

    def test_stage_latest_video_pushes_original_file_to_camera_roll(self):
        fixed_now = datetime(2026, 6, 16, 19, 30, 45)
        commands = []
        remove_local_file = Mock()
        fresh_image_factory = Mock()

        def fake_run_adb(command, serial=None):
            commands.append((command, serial))
            return ""

        with tempfile.NamedTemporaryFile(suffix=".mp4") as media_file, patch(
            "builtins.print"
        ):
            remote_path = appium_media.stage_latest_media(
                "192.168.10.21:5555",
                media_file.name,
                "video/mp4",
                run_adb_command=fake_run_adb,
                now_provider=lambda: fixed_now,
                fresh_image_factory=fresh_image_factory,
                remove_local_file=remove_local_file,
                wait_after_push=0,
            )

            self.assertEqual(
                commands[0],
                (
                    [
                        "push",
                        media_file.name,
                        "/sdcard/DCIM/Camera/VID_20260616_193045.mp4",
                    ],
                    "192.168.10.21:5555",
                ),
            )

        self.assertEqual(
            remote_path,
            "/sdcard/DCIM/Camera/VID_20260616_193045.mp4",
        )
        fresh_image_factory.assert_not_called()
        remove_local_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
