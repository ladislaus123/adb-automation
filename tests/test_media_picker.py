import unittest
from unittest.mock import patch

from adb_automation import media_picker
from adb_automation.errors import AutomationError, WhatsAppRestrictedError

WHATSAPP_PACKAGE = "com.whatsapp"
MEDIA_STRIP_DUMP = """<hierarchy>
  <node resource-id="com.whatsapp:id/media_item_view" content-desc="Photo" bounds="[0,761][177,938]" />
</hierarchy>
"""
EMPTY_DUMP = "<hierarchy></hierarchy>"
SEND_BUTTON_PRESENT_DUMP = """<hierarchy>
  <node resource-id="com.whatsapp:id/send" content-desc="Send" bounds="[615,1405][705,1495]" />
</hierarchy>
"""
SEND_BUTTON_GONE_DUMP = "<hierarchy></hierarchy>"
RESTRICTED_DUMP = """<hierarchy>
  <node resource-id="com.whatsapp:id/send" content-desc="Send" bounds="[615,1405][705,1495]" />
  <node text="Sua conta foi restringida" content-desc="" bounds="[0,0][100,100]" />
</hierarchy>
"""


def scripted_dump(sequence):
    remaining = list(sequence)

    def fake_run_adb(command, serial=None):
        if command[:2] == ["shell", "uiautomator"]:
            return ""
        if command[:2] == ["shell", "cat"]:
            if not remaining:
                return SEND_BUTTON_GONE_DUMP
            return remaining.pop(0)
        return ""

    return fake_run_adb


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
    def test_taps_attach_at_fixed_coords_then_finds_thumbnail_by_dump(self):
        commands = []

        def fake_run_adb(command, serial=None):
            commands.append(command)
            if command[:2] == ["shell", "uiautomator"]:
                return ""
            if command[:2] == ["shell", "cat"]:
                return MEDIA_STRIP_DUMP
            return "Physical size: 720x1600"

        media_picker.select_latest_media_from_attach_menu(
            "serial",
            WHATSAPP_PACKAGE,
            run_adb_command=fake_run_adb,
            sleep=lambda seconds: None,
        )

    def test_falls_back_to_gallery_source_when_media_strip_missing(self):
        run_adb = scripted_dump(
            [ATTACH_DUMP, EMPTY_DUMP, GALLERY_OPTION_DUMP, MEDIA_STRIP_DUMP]
        )

        media_picker.select_latest_media_from_attach_menu(
            "serial",
            WHATSAPP_PACKAGE,
            mime_type="image/jpeg",
            run_adb_command=run_adb,
            sleep=lambda seconds: None,
        )

    def test_raises_when_attach_button_not_found(self):
        run_adb = scripted_dump([EMPTY_DUMP])

        with patch("adb_automation.media_picker.ATTACH_TIMEOUT_SECONDS", 0.01), patch(
            "adb_automation.media_picker.capture_debug_ui_dump"
        ) as capture_debug_ui_dump:
            with self.assertRaisesRegex(AutomationError, "Attach button not found"):
                media_picker.select_latest_media_from_attach_menu(
                    "serial",
                    WHATSAPP_PACKAGE,
                    mime_type="image/jpeg",
                    run_adb_command=run_adb,
                    sleep=lambda seconds: None,
                )
        capture_debug_ui_dump.assert_called_once()

    def test_raises_when_no_media_item_found(self):
        commands = []

        def fake_run_adb(command, serial=None):
            commands.append(command)
            if command[:2] == ["shell", "uiautomator"]:
                return ""
            if command[:2] == ["shell", "cat"]:
                return EMPTY_DUMP
            return "Physical size: 720x1600"

        with patch("adb_automation.media_picker.MEDIA_ITEM_TIMEOUT_SECONDS", 0.01):
            with self.assertRaisesRegex(AutomationError, "No media_item_view found"):
                media_picker.select_latest_media_from_attach_menu(
                    "serial",
                    WHATSAPP_PACKAGE,
                    run_adb_command=fake_run_adb,
                    sleep=lambda seconds: None,
                )


class EnterCaptionAndSendTests(unittest.TestCase):
    def test_sends_without_caption_when_none_given(self):
        run_adb = scripted_dump([SEND_BUTTON_GONE_DUMP])

        media_picker.enter_caption_and_send(
            "serial",
            WHATSAPP_PACKAGE,
            caption=None,
            run_adb_command=run_adb,
            sleep=lambda seconds: None,
        )

    def test_taps_send_button_at_fixed_coords(self):
        commands = []

        def fake_run_adb(command, serial=None):
            commands.append(command)
            if command[:2] == ["shell", "uiautomator"]:
                return ""
            if command[:2] == ["shell", "cat"]:
                return SEND_BUTTON_GONE_DUMP
            return "Physical size: 720x1600"

        media_picker.enter_caption_and_send(
            "serial",
            WHATSAPP_PACKAGE,
            caption=None,
            run_adb_command=fake_run_adb,
            sleep=lambda seconds: None,
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
            if command[:2] == ["shell", "uiautomator"]:
                return ""
            if command[:2] == ["shell", "cat"]:
                return SEND_BUTTON_GONE_DUMP
            return "Physical size: 720x1600"

        media_picker.enter_caption_and_send(
            "serial",
            WHATSAPP_PACKAGE,
            caption="hello",
            run_adb_command=fake_run_adb,
            sleep=lambda seconds: None,
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
        run_adb = scripted_dump([SEND_BUTTON_PRESENT_DUMP])

        with patch("adb_automation.media_picker.write_debug_dump"):
            with self.assertRaisesRegex(AutomationError, "Media appears unsent"):
                media_picker.enter_caption_and_send(
                    "serial",
                    WHATSAPP_PACKAGE,
                    caption=None,
                    run_adb_command=run_adb,
                    sleep=lambda seconds: None,
                )

    def test_raises_restricted_when_final_dump_shows_restricted_text(self):
        run_adb = scripted_dump([RESTRICTED_DUMP])

        with self.assertRaisesRegex(
            WhatsAppRestrictedError,
            "^WhatsApp is restricted\\.$",
        ):
            media_picker.enter_caption_and_send(
                "serial",
                WHATSAPP_PACKAGE,
                caption=None,
                run_adb_command=run_adb,
                sleep=lambda seconds: None,
            )


class VerifyMediaWasSentTests(unittest.TestCase):
    def test_returns_when_send_button_is_gone(self):
        run_adb = scripted_dump([SEND_BUTTON_GONE_DUMP])

        media_picker.verify_media_was_sent(
            "serial", WHATSAPP_PACKAGE, run_adb_command=run_adb
        )

    def test_raises_when_dump_itself_fails(self):
        def fake_run_adb(command, serial=None):
            if command[:2] == ["shell", "uiautomator"]:
                raise AutomationError("command failed: some adb error")
            return ""

        with self.assertRaisesRegex(
            AutomationError, "Could not verify whether the media was actually sent"
        ):
            media_picker.verify_media_was_sent(
                "serial", WHATSAPP_PACKAGE, run_adb_command=fake_run_adb
            )


class SendMediaViaGalleryPickerTests(unittest.TestCase):
    def test_stages_opens_chat_selects_media_sends_and_cleans_up(self):
        with patch(
            "adb_automation.media_picker.clear_stale_uiautomation"
        ) as clear_stale_uiautomation, patch(
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

        clear_stale_uiautomation.assert_called_once_with(
            "serial", run_adb_command=media_picker.run_adb
        )
        stage_latest_media.assert_called_once()
        open_whatsapp_chat.assert_called_once()
        verify_whatsapp_chat_ready.assert_called_once()
        select_latest_media_from_attach_menu.assert_called_once()
        enter_caption_and_send.assert_called_once()
        cleanup_staged_media.assert_called_once_with(
            "serial", "/sdcard/DCIM/Camera/IMG_1.jpg", run_adb_command=media_picker.run_adb
        )

    def test_clears_stale_uiautomation_before_staging_media(self):
        commands = []

        def run_adb(command, serial=None):
            commands.append(command)
            return ""

        with patch(
            "adb_automation.media_picker.stage_latest_media",
            return_value="/sdcard/DCIM/Camera/IMG_1.jpg",
        ), patch(
            "adb_automation.media_picker.open_whatsapp_chat"
        ), patch(
            "adb_automation.media_picker.verify_whatsapp_chat_ready"
        ), patch(
            "adb_automation.media_picker.select_latest_media_from_attach_menu"
        ), patch(
            "adb_automation.media_picker.enter_caption_and_send"
        ), patch(
            "adb_automation.media_picker.cleanup_staged_media"
        ), patch(
            "builtins.print"
        ):
            media_picker.send_media_via_gallery_picker(
                "serial",
                "5511999999999",
                "/tmp/photo.jpg",
                WHATSAPP_PACKAGE,
                mime_type="image/jpeg",
                run_adb_command=run_adb,
            )

        self.assertEqual(commands[0], ["shell", "pkill", "-f", "uiautomator"])

    def test_cleans_up_staged_media_even_when_send_fails(self):
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
