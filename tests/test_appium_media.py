import tempfile
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from adb_automation import appium_media
from adb_automation.config import WHATSAPP_BUSINESS_PACKAGE
from adb_automation.errors import AutomationError


class FakeElement:
    def __init__(self, on_click=None):
        self.clicked = False
        self.sent_keys = []
        self.on_click = on_click

    def click(self):
        self.clicked = True
        if self.on_click is not None:
            self.on_click()

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
                mime_type="image/jpeg",
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
                mime_type="image/jpeg",
                send_timeout=0,
            )

        dump_ui.assert_called_once_with(driver, "debug_send_not_found.xml")
        self.assertEqual(
            driver.scripts,
            [("mobile: clickGesture", {"x": 900, "y": 1840})],
        )

    def test_send_latest_visible_media_clicks_gallery_when_sheet_is_open(self):
        attach = FakeElement()
        media = FakeElement()
        send = FakeElement()
        driver = FakeDriver()

        def reveal_media():
            driver.elements[
                (
                    "xpath",
                    f"(//*[@resource-id='{WHATSAPP_BUSINESS_PACKAGE}:id/media_item_view'])[1]",
                )
            ] = media

        gallery = FakeElement(on_click=reveal_media)
        driver.elements.update(
            {
                ("id", f"{WHATSAPP_BUSINESS_PACKAGE}:id/input_attach_button"): attach,
                (
                    "id",
                    f"{WHATSAPP_BUSINESS_PACKAGE}:id/pickfiletype_gallery_holder",
                ): gallery,
                ("id", f"{WHATSAPP_BUSINESS_PACKAGE}:id/send"): send,
            }
        )

        with patch("adb_automation.appium_media.time.sleep"), patch(
            "builtins.print"
        ):
            appium_media.send_latest_visible_media(
                driver,
                WHATSAPP_BUSINESS_PACKAGE,
                mime_type="image/jpeg",
                media_timeout=0,
                source_timeout=0,
            )

        self.assertTrue(attach.clicked)
        self.assertTrue(gallery.clicked)
        self.assertTrue(media.clicked)
        self.assertTrue(send.clicked)

    def test_send_latest_visible_media_clicks_audio_when_sheet_is_open(self):
        attach = FakeElement()
        media = FakeElement()
        send = FakeElement()
        driver = FakeDriver()

        def reveal_media():
            driver.elements[
                (
                    "xpath",
                    f"(//*[@resource-id='{WHATSAPP_BUSINESS_PACKAGE}:id/media_item_view'])[1]",
                )
            ] = media

        audio = FakeElement(on_click=reveal_media)
        driver.elements.update(
            {
                ("id", f"{WHATSAPP_BUSINESS_PACKAGE}:id/input_attach_button"): attach,
                (
                    "id",
                    f"{WHATSAPP_BUSINESS_PACKAGE}:id/pickfiletype_audio_holder",
                ): audio,
                ("id", f"{WHATSAPP_BUSINESS_PACKAGE}:id/send"): send,
            }
        )

        with patch("adb_automation.appium_media.time.sleep"), patch(
            "builtins.print"
        ):
            appium_media.send_latest_visible_media(
                driver,
                WHATSAPP_BUSINESS_PACKAGE,
                mime_type="audio/ogg",
                media_timeout=0,
                source_timeout=0,
            )

        self.assertTrue(attach.clicked)
        self.assertTrue(audio.clicked)
        self.assertTrue(media.clicked)
        self.assertTrue(send.clicked)

    def test_attachment_source_selectors_cover_gallery_and_audio_locales(self):
        self.assertIn(
            ("id", f"{WHATSAPP_BUSINESS_PACKAGE}:id/pickfiletype_gallery_holder"),
            appium_media.gallery_attachment_selectors(WHATSAPP_BUSINESS_PACKAGE),
        )
        self.assertIn(
            ("accessibility", "Galeria"),
            appium_media.gallery_attachment_selectors(WHATSAPP_BUSINESS_PACKAGE),
        )
        self.assertIn(
            ("accessibility", "Gallery"),
            appium_media.gallery_attachment_selectors(WHATSAPP_BUSINESS_PACKAGE),
        )
        self.assertIn(
            ("id", f"{WHATSAPP_BUSINESS_PACKAGE}:id/pickfiletype_audio_holder"),
            appium_media.audio_attachment_selectors(WHATSAPP_BUSINESS_PACKAGE),
        )
        self.assertIn(
            ("accessibility", "Áudio"),
            appium_media.audio_attachment_selectors(WHATSAPP_BUSINESS_PACKAGE),
        )
        self.assertIn(
            ("accessibility", "Audio"),
            appium_media.audio_attachment_selectors(WHATSAPP_BUSINESS_PACKAGE),
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

        fake_sleep = Mock()

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
                sleep=fake_sleep,
            )

        self.assertEqual(
            factory_calls,
            [(serial, "http://appium.local:4723")],
        )
        send_latest_visible_media.assert_called_once_with(
            driver,
            WHATSAPP_BUSINESS_PACKAGE,
            caption="caption",
            mime_type="image/jpeg",
        )
        self.assertIn(
            (
                [
                    "shell",
                    "am",
                    "force-stop",
                    "io.appium.uiautomator2.server",
                ],
                serial,
            ),
            cleanup_commands,
        )
        self.assertIn(
            (["shell", "rm", "-f", remote_path], serial),
            cleanup_commands,
        )
        self.assertIn(
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
            cleanup_commands,
        )
        self.assertTrue(driver.quit_called)

    def test_send_media_with_appium_resets_helpers_and_retries_driver(self):
        driver = FakeDriver()
        factory_calls = []
        commands = []
        serial = "192.168.10.21:5555"
        remote_path = "/sdcard/DCIM/Camera/IMG_20260616_193045.jpg"

        def driver_factory(serial, server_url):
            factory_calls.append((serial, server_url))
            if len(factory_calls) == 1:
                raise AutomationError("UiAutomation not connected")
            return driver

        def fake_run_adb(command, serial=None):
            commands.append((command, serial))
            return ""

        fake_sleep = Mock()

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
                sleep=fake_sleep,
            )

        self.assertEqual(
            factory_calls,
            [
                (serial, "http://appium.local:4723"),
                (serial, "http://appium.local:4723"),
            ],
        )
        self.assertIn(
            (
                [
                    "shell",
                    "am",
                    "force-stop",
                    "io.appium.uiautomator2.server",
                ],
                serial,
            ),
            commands,
        )
        send_latest_visible_media.assert_called_once_with(
            driver,
            WHATSAPP_BUSINESS_PACKAGE,
            caption="caption",
            mime_type="image/jpeg",
        )
        self.assertTrue(driver.quit_called)

    def test_send_media_with_appium_falls_back_to_direct_intent_after_retry_fails(self):
        factory_calls = []
        commands = []
        serial = "192.168.10.21:5555"
        remote_path = "/sdcard/DCIM/Camera/IMG_20260616_193045.jpg"

        def driver_factory(serial, server_url):
            factory_calls.append((serial, server_url))
            raise AutomationError("UiAutomation not connected")

        def fake_run_adb(command, serial=None):
            commands.append((command, serial))
            return ""

        fake_sleep = Mock()

        with patch(
            "adb_automation.appium_media.stage_latest_media",
            return_value=remote_path,
        ), patch("adb_automation.appium_media.open_whatsapp_chat"), patch(
            "adb_automation.appium_media.click_direct_media_send"
        ) as click_direct_media_send, patch("builtins.print"):
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
                sleep=fake_sleep,
            )

        self.assertEqual(len(factory_calls), 2)
        direct_intents = [
            command
            for command, _serial in commands
            if command[:5]
            == ["shell", "am", "start", "-a", "android.intent.action.SEND"]
        ]
        self.assertEqual(len(direct_intents), 1)
        self.assertIn(f"file://{remote_path}", direct_intents[0])
        self.assertIn("android.intent.extra.TEXT", direct_intents[0])
        click_direct_media_send.assert_called_once_with(
            serial,
            WHATSAPP_BUSINESS_PACKAGE,
            run_adb_command=fake_run_adb,
            sleep=fake_sleep,
        )


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
