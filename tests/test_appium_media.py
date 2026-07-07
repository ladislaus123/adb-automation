import tempfile
import types
import unittest
from datetime import datetime
from unittest.mock import Mock, call, patch

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
    def test_start_appium_driver_sets_deterministic_system_port(self):
        captured = {}
        serial = "192.168.10.21:5555"

        class FakeOptions:
            def __init__(self):
                self.capabilities = {}

            def set_capability(self, key, value):
                self.capabilities[key] = value

        def fake_remote(server_url, options=None):
            captured["server_url"] = server_url
            captured["options"] = options
            return "driver"

        appium_module = types.ModuleType("appium")
        webdriver_module = types.ModuleType("appium.webdriver")
        webdriver_module.Remote = fake_remote
        appium_module.webdriver = webdriver_module
        options_module = types.ModuleType("appium.options")
        android_options_module = types.ModuleType("appium.options.android")
        android_options_module.UiAutomator2Options = FakeOptions

        with patch.dict(
            "sys.modules",
            {
                "appium": appium_module,
                "appium.webdriver": webdriver_module,
                "appium.options": options_module,
                "appium.options.android": android_options_module,
            },
        ):
            driver = appium_media.start_appium_driver(
                serial,
                "http://appium.local:4723",
            )

        self.assertEqual(driver, "driver")
        self.assertEqual(captured["server_url"], "http://appium.local:4723")
        system_port = captured["options"].capabilities["systemPort"]
        self.assertEqual(
            system_port,
            appium_media.appium_system_port_for_serial(serial),
        )
        self.assertGreaterEqual(system_port, appium_media.APPIUM_SYSTEM_PORT_BASE)
        self.assertLess(
            system_port,
            appium_media.APPIUM_SYSTEM_PORT_BASE
            + appium_media.APPIUM_SYSTEM_PORT_SPAN,
        )

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
        events = []
        serial = "192.168.10.21:5555"
        remote_path = "/sdcard/DCIM/Camera/IMG_20260616_193045.jpg"

        def quit_driver():
            events.append(("quit",))
            driver.quit_called = True

        driver.quit = quit_driver

        def driver_factory(serial, server_url):
            factory_calls.append((serial, server_url))
            events.append(("factory", serial, server_url))
            return driver

        def fake_run_adb(command, serial=None):
            cleanup_commands.append((command, serial))
            events.append(("adb", command, serial))
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
        self.assertNotIn((["forward", "--remove-all"], serial), cleanup_commands)
        force_stopped = [
            command[3]
            for command, _serial in cleanup_commands
            if command[:3] == ["shell", "am", "force-stop"]
        ]
        self.assertNotIn("io.appium.uiautomator2.server", force_stopped)
        self.assertNotIn("io.appium.uiautomator2.server.test", force_stopped)
        self.assertNotIn("io.appium.settings", force_stopped)
        u2_stop_event = (
            "adb",
            ["shell", "am", "force-stop", "com.github.uiautomator"],
            serial,
        )
        self.assertLess(
            events.index(u2_stop_event),
            events.index(("factory", serial, "http://appium.local:4723")),
        )
        send_latest_visible_media.assert_called_once_with(
            driver,
            WHATSAPP_BUSINESS_PACKAGE,
            caption="caption",
            mime_type="image/jpeg",
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
        self.assertEqual(
            fake_sleep.call_args_list,
            [
                call(appium_media.APPIUM_PRE_SESSION_WAIT_SECONDS),
                call(appium_media.APPIUM_POST_QUIT_WAIT_SECONDS),
            ],
        )

    def test_send_media_with_appium_recovers_and_retries_driver(self):
        driver = FakeDriver()
        factory_calls = []
        commands = []
        events = []
        serial = "192.168.10.21:5555"
        remote_path = "/sdcard/DCIM/Camera/IMG_20260616_193045.jpg"

        def driver_factory(serial, server_url):
            factory_calls.append((serial, server_url))
            events.append(("factory", len(factory_calls), serial, server_url))
            if len(factory_calls) == 1:
                raise AutomationError("UiAutomation not connected")
            return driver

        def fake_run_adb(command, serial=None):
            commands.append((command, serial))
            events.append(("adb", command, serial))
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
        self.assertNotIn((["forward", "--remove-all"], serial), commands)
        port = appium_media.appium_system_port_for_serial(serial)
        forward_event = ("adb", ["forward", "--remove", f"tcp:{port}"], serial)
        server_stop_event = (
            "adb",
            ["shell", "am", "force-stop", "io.appium.uiautomator2.server"],
            serial,
        )
        first_attempt = events.index(("factory", 1, serial, "http://appium.local:4723"))
        second_attempt = events.index(("factory", 2, serial, "http://appium.local:4723"))
        self.assertLess(first_attempt, events.index(server_stop_event))
        self.assertLess(events.index(server_stop_event), second_attempt)
        self.assertLess(first_attempt, events.index(forward_event))
        self.assertLess(events.index(forward_event), second_attempt)
        self.assertIn(
            (["shell", "pkill", "-f", "uiautomator"], serial),
            commands,
        )
        uninstalls = [
            command for command, _serial in commands if command[:1] == ["uninstall"]
        ]
        self.assertEqual(uninstalls, [])
        send_latest_visible_media.assert_called_once_with(
            driver,
            WHATSAPP_BUSINESS_PACKAGE,
            caption="caption",
            mime_type="image/jpeg",
        )
        self.assertTrue(driver.quit_called)
        self.assertEqual(
            fake_sleep.call_args_list,
            [
                call(appium_media.APPIUM_PRE_SESSION_WAIT_SECONDS),
                call(appium_media.appium_settle_seconds()),
                call(appium_media.APPIUM_POST_QUIT_WAIT_SECONDS),
            ],
        )

    def test_send_media_with_appium_falls_back_to_direct_intent_after_ladder_fails(self):
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
        ) as click_direct_media_send, patch(
            "adb_automation.appium_media.connect_wifi_device"
        ), patch.dict(
            "os.environ",
            {
                "ADB_AUTOMATION_APPIUM_RECONNECT_ON_WEDGE": "1",
                "ADB_AUTOMATION_APPIUM_REBOOT_ON_WEDGE": "0",
            },
        ), patch("builtins.print"):
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

        # initial attempt + one retry per ladder level (1, 2, 3)
        self.assertEqual(len(factory_calls), 4)
        uninstalls = [
            command for command, _serial in commands if command[:1] == ["uninstall"]
        ]
        self.assertEqual(
            uninstalls,
            [
                ["uninstall", "io.appium.uiautomator2.server"],
                ["uninstall", "io.appium.uiautomator2.server.test"],
            ],
        )
        self.assertIn((["reconnect"], serial), commands)
        self.assertNotIn((["reboot"], serial), commands)
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
        settle = appium_media.appium_settle_seconds()
        self.assertEqual(
            fake_sleep.call_args_list,
            [
                call(appium_media.APPIUM_PRE_SESSION_WAIT_SECONDS),
                call(settle),
                call(settle),
                call(settle),
                call(settle),
            ],
        )

    def test_start_appium_driver_with_recovery_skips_ladder_on_non_recoverable_error(self):
        factory_calls = []
        commands = []
        serial = "192.168.10.21:5555"

        def driver_factory(serial, server_url):
            factory_calls.append((serial, server_url))
            raise AutomationError("Appium-Python-Client is required")

        def fake_run_adb(command, serial=None):
            commands.append((command, serial))
            return ""

        with patch("builtins.print"):
            driver = appium_media.start_appium_driver_with_recovery(
                serial,
                "http://appium.local:4723",
                run_adb_command=fake_run_adb,
                driver_factory=driver_factory,
                sleep=Mock(),
            )

        self.assertIsNone(driver)
        self.assertEqual(len(factory_calls), 1)
        force_stopped = [
            command[3]
            for command, _serial in commands
            if command[:3] == ["shell", "am", "force-stop"]
        ]
        self.assertNotIn("io.appium.uiautomator2.server", force_stopped)
        uninstalls = [
            command for command, _serial in commands if command[:1] == ["uninstall"]
        ]
        self.assertEqual(uninstalls, [])

    def test_remove_appium_forward_targets_device_system_port(self):
        commands = []
        serial = "192.168.10.21:5555"

        def fake_run_adb(command, serial=None):
            commands.append((command, serial))
            return ""

        appium_media.remove_appium_forward(serial, run_adb_command=fake_run_adb)

        port = appium_media.appium_system_port_for_serial(serial)
        self.assertEqual(commands, [(["forward", "--remove", f"tcp:{port}"], serial)])

    def test_build_recovery_ladder_respects_env_gates(self):
        with patch.dict(
            "os.environ",
            {
                "ADB_AUTOMATION_APPIUM_RECONNECT_ON_WEDGE": "1",
                "ADB_AUTOMATION_APPIUM_REBOOT_ON_WEDGE": "0",
            },
        ):
            default_ladder = appium_media.build_recovery_ladder()
        self.assertEqual(
            default_ladder,
            [
                appium_media.recover_appium_level_1,
                appium_media.recover_appium_level_2,
                appium_media.recover_appium_level_3,
            ],
        )

        with patch.dict(
            "os.environ",
            {
                "ADB_AUTOMATION_APPIUM_RECONNECT_ON_WEDGE": "0",
                "ADB_AUTOMATION_APPIUM_REBOOT_ON_WEDGE": "1",
            },
        ):
            gated_ladder = appium_media.build_recovery_ladder()
        self.assertEqual(
            gated_ladder,
            [
                appium_media.recover_appium_level_1,
                appium_media.recover_appium_level_2,
                appium_media.recover_appium_level_4,
            ],
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
