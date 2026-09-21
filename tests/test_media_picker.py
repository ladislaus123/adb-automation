import unittest
from unittest.mock import patch

from adb_automation import media_picker
from adb_automation.errors import AutomationError, WhatsAppRestrictedError

WHATSAPP_PACKAGE = "com.whatsapp"


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


class ScaledPointTests(unittest.TestCase):
    def test_scaled_point_is_unchanged_at_reference_resolution(self):
        def fake_run_adb(command, serial=None):
            return "Physical size: 720x1600"

        self.assertEqual(
            media_picker.scaled_point(
                "serial", (461, 1456), run_adb_command=fake_run_adb
            ),
            (461, 1456),
        )

    def test_scaled_point_scales_proportionally_to_actual_screen_size(self):
        def fake_run_adb(command, serial=None):
            return "Physical size: 1440x3200"

        self.assertEqual(
            media_picker.scaled_point(
                "serial", (360, 800), run_adb_command=fake_run_adb
            ),
            (720, 1600),
        )

    def test_scaled_point_falls_back_to_reference_when_size_unreadable(self):
        def fake_run_adb(command, serial=None):
            return ""

        self.assertEqual(
            media_picker.scaled_point(
                "serial", (461, 1456), run_adb_command=fake_run_adb
            ),
            (461, 1456),
        )

    def test_scaled_point_falls_back_to_reference_when_wm_size_fails(self):
        def fake_run_adb(command, serial=None):
            raise AutomationError("device offline")

        self.assertEqual(
            media_picker.scaled_point(
                "serial", (461, 1456), run_adb_command=fake_run_adb
            ),
            (461, 1456),
        )


class SelectLatestMediaFromAttachMenuTests(unittest.TestCase):
    def test_taps_attach_at_fixed_coords_then_finds_thumbnail_via_uiautomator2(self):
        commands = []

        def fake_run_adb(command, serial=None):
            commands.append(command)
            return "Physical size: 720x1600"

        device = FakeUiDevice()
        target = device.add_selector(
            {"resourceId": f"{WHATSAPP_PACKAGE}:id/media_item_view"}
        )

        media_picker.select_latest_media_from_attach_menu(
            "serial",
            WHATSAPP_PACKAGE,
            run_adb_command=fake_run_adb,
            sleep=lambda seconds: None,
            device_connector=lambda serial: device,
        )

        self.assertTrue(target.clicked)
        self.assertIn(
            [
                "shell",
                "input",
                "tap",
                str(media_picker.ATTACH_BUTTON_COORDS[0]),
                str(media_picker.ATTACH_BUTTON_COORDS[1]),
            ],
            commands,
        )

    def test_raises_when_no_media_item_found(self):
        device = FakeUiDevice()

        with patch("adb_automation.media_picker.MEDIA_ITEM_TIMEOUT_SECONDS", 0):
            with self.assertRaisesRegex(AutomationError, "No media_item_view found"):
                media_picker.select_latest_media_from_attach_menu(
                    "serial",
                    WHATSAPP_PACKAGE,
                    run_adb_command=lambda command, serial=None: "",
                    sleep=lambda seconds: None,
                    device_connector=lambda serial: device,
                )

    def test_falls_back_to_gallery_source_when_media_strip_missing(self):
        device = FakeUiDevice()
        gallery_tile = device.add_selector({"description": "Galeria"})

        # The media-item selector only starts existing after the Galeria
        # tile is tapped, mirroring WhatsApp revealing the strip on demand.
        original_click = gallery_tile.click

        def reveal_media_item_on_click():
            original_click()
            device.add_selector(
                {"resourceId": f"{WHATSAPP_PACKAGE}:id/media_item_view"}
            )

        gallery_tile.click = reveal_media_item_on_click

        with patch("adb_automation.media_picker.MEDIA_ITEM_TIMEOUT_SECONDS", 0), patch(
            "adb_automation.media_picker.SOURCE_TIMEOUT_SECONDS", 0
        ):
            media_picker.select_latest_media_from_attach_menu(
                "serial",
                WHATSAPP_PACKAGE,
                mime_type="image/jpeg",
                run_adb_command=lambda command, serial=None: "",
                sleep=lambda seconds: None,
                device_connector=lambda serial: device,
            )

        self.assertTrue(gallery_tile.clicked)

    def test_raises_when_no_media_item_found_even_after_gallery_fallback(self):
        device = FakeUiDevice()
        device.add_selector({"description": "Galeria"})

        with patch("adb_automation.media_picker.MEDIA_ITEM_TIMEOUT_SECONDS", 0), patch(
            "adb_automation.media_picker.SOURCE_TIMEOUT_SECONDS", 0
        ):
            with self.assertRaisesRegex(AutomationError, "No media_item_view found"):
                media_picker.select_latest_media_from_attach_menu(
                    "serial",
                    WHATSAPP_PACKAGE,
                    mime_type="image/jpeg",
                    run_adb_command=lambda command, serial=None: "",
                    sleep=lambda seconds: None,
                    device_connector=lambda serial: device,
                )


class EnterCaptionAndSendTests(unittest.TestCase):
    def test_sends_without_caption_when_none_given(self):
        device = FakeUiDevice()

        media_picker.enter_caption_and_send(
            "serial",
            WHATSAPP_PACKAGE,
            caption=None,
            run_adb_command=lambda command, serial=None: "",
            sleep=lambda seconds: None,
            device_connector=lambda serial: device,
        )

    def test_taps_send_button_at_fixed_coords(self):
        commands = []

        def fake_run_adb(command, serial=None):
            commands.append(command)
            return ""

        media_picker.enter_caption_and_send(
            "serial",
            WHATSAPP_PACKAGE,
            caption=None,
            run_adb_command=fake_run_adb,
            sleep=lambda seconds: None,
            device_connector=lambda serial: FakeUiDevice(),
        )

        self.assertIn(
            [
                "shell",
                "input",
                "tap",
                str(media_picker.SEND_BUTTON_COORDS[0]),
                str(media_picker.SEND_BUTTON_COORDS[1]),
            ],
            commands,
        )

    def test_types_caption_before_tapping_send(self):
        commands = []

        def fake_run_adb(command, serial=None):
            commands.append(command)
            return ""

        media_picker.enter_caption_and_send(
            "serial",
            WHATSAPP_PACKAGE,
            caption="hello",
            run_adb_command=fake_run_adb,
            sleep=lambda seconds: None,
            device_connector=lambda serial: FakeUiDevice(),
        )

        caption_tap = [
            "shell",
            "input",
            "tap",
            str(media_picker.CAPTION_FIELD_COORDS[0]),
            str(media_picker.CAPTION_FIELD_COORDS[1]),
        ]
        text_command = ["shell", "input", "text", "hello"]
        send_tap = [
            "shell",
            "input",
            "tap",
            str(media_picker.SEND_BUTTON_COORDS[0]),
            str(media_picker.SEND_BUTTON_COORDS[1]),
        ]
        self.assertIn(caption_tap, commands)
        self.assertIn(text_command, commands)
        self.assertIn(send_tap, commands)
        self.assertLess(commands.index(caption_tap), commands.index(text_command))
        self.assertLess(commands.index(text_command), commands.index(send_tap))

    def test_raises_when_send_button_still_showing_after_send_tap(self):
        device = FakeUiDevice()
        device.add_selector({"resourceId": f"{WHATSAPP_PACKAGE}:id/send"})

        with patch("adb_automation.media_picker.SEND_CONFIRM_TIMEOUT_SECONDS", 0):
            with self.assertRaisesRegex(AutomationError, "Media appears unsent"):
                media_picker.enter_caption_and_send(
                    "serial",
                    WHATSAPP_PACKAGE,
                    caption=None,
                    run_adb_command=lambda command, serial=None: "",
                    sleep=lambda seconds: None,
                    device_connector=lambda serial: device,
                )

    def test_raises_restricted_when_send_button_still_showing_with_restricted_banner(
        self,
    ):
        device = FakeUiDevice()
        device.add_selector({"resourceId": f"{WHATSAPP_PACKAGE}:id/send"})
        device.add_selector({"text": "Sua conta foi restringida"})

        with patch("adb_automation.media_picker.SEND_CONFIRM_TIMEOUT_SECONDS", 0):
            with self.assertRaisesRegex(
                WhatsAppRestrictedError,
                "^WhatsApp is restricted\\.$",
            ):
                media_picker.enter_caption_and_send(
                    "serial",
                    WHATSAPP_PACKAGE,
                    caption=None,
                    run_adb_command=lambda command, serial=None: "",
                    sleep=lambda seconds: None,
                    device_connector=lambda serial: device,
                )


class VerifyMediaWasSentTests(unittest.TestCase):
    def test_returns_when_send_button_is_gone(self):
        device = FakeUiDevice()

        media_picker.verify_media_was_sent(
            "serial",
            WHATSAPP_PACKAGE,
            run_adb_command=lambda command, serial=None: "",
            device_connector=lambda serial: device,
        )

    def test_raises_when_send_button_never_disappears(self):
        device = FakeUiDevice()
        device.add_selector({"resourceId": f"{WHATSAPP_PACKAGE}:id/send"})

        with patch("adb_automation.media_picker.SEND_CONFIRM_TIMEOUT_SECONDS", 0):
            with self.assertRaisesRegex(AutomationError, "Media appears unsent"):
                media_picker.verify_media_was_sent(
                    "serial",
                    WHATSAPP_PACKAGE,
                    run_adb_command=lambda command, serial=None: "",
                    device_connector=lambda serial: device,
                )


class SendMediaViaGalleryPickerTests(unittest.TestCase):
    def test_stages_opens_chat_selects_media_sends_and_cleans_up(self):
        with patch(
            "adb_automation.media_picker.stage_latest_media",
            return_value="/sdcard/DCIM/Camera/IMG_1.jpg",
        ) as stage_latest_media, patch(
            "adb_automation.media_picker.open_whatsapp_chat"
        ) as open_whatsapp_chat, patch(
            "adb_automation.media_picker.verify_whatsapp_chat_ready"
        ) as verify_whatsapp_chat_ready, patch(
            "adb_automation.media_picker.select_latest_media_from_attach_menu"
        ) as select_latest_media_from_attach_menu, patch(
            "adb_automation.media_picker.enter_caption_and_send"
        ) as enter_caption_and_send, patch(
            "adb_automation.media_picker.stop_u2_uiautomator"
        ) as stop_u2_uiautomator, patch(
            "adb_automation.media_picker.cleanup_staged_media"
        ) as cleanup_staged_media, patch(
            "builtins.print"
        ):
            media_picker.send_media_via_gallery_picker(
                "serial",
                "5511999999999",
                "/tmp/photo.jpg",
                WHATSAPP_PACKAGE,
                text="caption",
                mime_type="image/jpeg",
            )

        stage_latest_media.assert_called_once()
        open_whatsapp_chat.assert_called_once()
        verify_whatsapp_chat_ready.assert_called_once()
        select_latest_media_from_attach_menu.assert_called_once()
        enter_caption_and_send.assert_called_once()
        stop_u2_uiautomator.assert_called_once_with("serial")
        cleanup_staged_media.assert_called_once_with(
            "serial", "/sdcard/DCIM/Camera/IMG_1.jpg", run_adb_command=media_picker.run_adb
        )

    def test_stops_u2_uiautomator_and_cleans_up_even_when_send_fails(self):
        with patch(
            "adb_automation.media_picker.stage_latest_media",
            return_value="/sdcard/DCIM/Camera/IMG_1.jpg",
        ), patch(
            "adb_automation.media_picker.open_whatsapp_chat"
        ), patch(
            "adb_automation.media_picker.verify_whatsapp_chat_ready"
        ), patch(
            "adb_automation.media_picker.select_latest_media_from_attach_menu",
            side_effect=AutomationError("tap failed"),
        ), patch(
            "adb_automation.media_picker.stop_u2_uiautomator"
        ) as stop_u2_uiautomator, patch(
            "adb_automation.media_picker.cleanup_staged_media"
        ) as cleanup_staged_media, patch(
            "builtins.print"
        ):
            with self.assertRaises(AutomationError):
                media_picker.send_media_via_gallery_picker(
                    "serial",
                    "5511999999999",
                    "/tmp/photo.jpg",
                    WHATSAPP_PACKAGE,
                    mime_type="image/jpeg",
                )

        stop_u2_uiautomator.assert_called_once_with("serial")
        cleanup_staged_media.assert_called_once()

    def test_reports_when_send_fails_before_attach_flow(self):
        with patch(
            "adb_automation.media_picker.stage_latest_media",
            return_value="/sdcard/DCIM/Camera/IMG_1.jpg",
        ), patch(
            "adb_automation.media_picker.open_whatsapp_chat"
        ), patch(
            "adb_automation.media_picker.verify_whatsapp_chat_ready",
            side_effect=AutomationError("WhatsApp chat did not open"),
        ), patch(
            "adb_automation.media_picker.select_latest_media_from_attach_menu"
        ) as select_latest_media_from_attach_menu, patch(
            "adb_automation.media_picker.stop_u2_uiautomator"
        ), patch(
            "adb_automation.media_picker.cleanup_staged_media"
        ) as cleanup_staged_media, patch(
            "builtins.print"
        ):
            with self.assertRaisesRegex(AutomationError, "WhatsApp chat did not open"):
                media_picker.send_media_via_gallery_picker(
                    "serial",
                    "5511999999999",
                    "/tmp/photo.jpg",
                    WHATSAPP_PACKAGE,
                    mime_type="image/jpeg",
                )

        select_latest_media_from_attach_menu.assert_not_called()
        cleanup_staged_media.assert_called_once()


if __name__ == "__main__":
    unittest.main()
