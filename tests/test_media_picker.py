import unittest
from unittest.mock import patch

from adb_automation import media_picker
from adb_automation.errors import AutomationError, WhatsAppRestrictedError

WHATSAPP_PACKAGE = "com.whatsapp"
ATTACH_DUMP = """<hierarchy>
  <node resource-id="com.whatsapp:id/input_attach_button" content-desc="" bounds="[10,20][50,60]" />
</hierarchy>
"""
MEDIA_STRIP_DUMP = """<hierarchy>
  <node resource-id="com.whatsapp:id/media_item_view" content-desc="" bounds="[100,200][300,400]" />
</hierarchy>
"""
GALLERY_OPTION_DUMP = """<hierarchy>
  <node resource-id="com.whatsapp:id/pickfiletype_gallery_holder" content-desc="Gallery" bounds="[0,0][100,100]" />
</hierarchy>
"""
SEND_DUMP = """<hierarchy>
  <node resource-id="com.whatsapp:id/send" content-desc="Send" bounds="[500,900][560,960]" />
</hierarchy>
"""
CAPTION_DUMP = """<hierarchy>
  <node resource-id="com.whatsapp:id/caption" content-desc="" bounds="[20,800][580,850]" />
</hierarchy>
"""
EMPTY_DUMP = "<hierarchy></hierarchy>"
RESTRICTED_DUMP = """<hierarchy>
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
                return EMPTY_DUMP
            return remaining.pop(0)
        return ""

    return fake_run_adb


class SelectLatestMediaFromAttachMenuTests(unittest.TestCase):
    def test_selects_first_media_item_after_attach(self):
        run_adb = scripted_dump([ATTACH_DUMP, MEDIA_STRIP_DUMP])

        media_picker.select_latest_media_from_attach_menu(
            "serial",
            WHATSAPP_PACKAGE,
            mime_type="image/jpeg",
            run_adb_command=run_adb,
            sleep=lambda seconds: None,
        )

    def test_clears_stale_uiautomation_before_interacting(self):
        commands = []

        def run_adb(command, serial=None):
            commands.append(command)
            if command[:2] == ["shell", "uiautomator"]:
                return ""
            if command[:2] == ["shell", "cat"]:
                return ATTACH_DUMP if len(
                    [c for c in commands if c[:2] == ["shell", "cat"]]
                ) == 1 else MEDIA_STRIP_DUMP
            return ""

        media_picker.select_latest_media_from_attach_menu(
            "serial",
            WHATSAPP_PACKAGE,
            mime_type="image/jpeg",
            run_adb_command=run_adb,
            sleep=lambda seconds: None,
        )

        self.assertEqual(commands[0], ["shell", "pkill", "-f", "uiautomator"])

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

    def test_raises_restricted_when_attach_button_is_hidden_by_restricted_screen(self):
        run_adb = scripted_dump([RESTRICTED_DUMP, RESTRICTED_DUMP])

        with patch("adb_automation.media_picker.ATTACH_TIMEOUT_SECONDS", 0):
            with self.assertRaisesRegex(
                WhatsAppRestrictedError,
                "^WhatsApp is restricted\\.$",
            ):
                media_picker.select_latest_media_from_attach_menu(
                    "serial",
                    WHATSAPP_PACKAGE,
                    mime_type="image/jpeg",
                    run_adb_command=run_adb,
                    sleep=lambda seconds: None,
                )

    def test_raises_when_no_media_item_found_anywhere(self):
        run_adb = scripted_dump([ATTACH_DUMP, EMPTY_DUMP, EMPTY_DUMP])

        with patch(
            "adb_automation.media_picker.MEDIA_ITEM_TIMEOUT_SECONDS", 0.01
        ), patch("adb_automation.media_picker.SOURCE_TIMEOUT_SECONDS", 0.01):
            with self.assertRaisesRegex(AutomationError, "No media_item_view found"):
                media_picker.select_latest_media_from_attach_menu(
                    "serial",
                    WHATSAPP_PACKAGE,
                    mime_type="audio/mpeg",
                    run_adb_command=run_adb,
                    sleep=lambda seconds: None,
                )

    def test_raises_restricted_when_media_strip_is_hidden_by_restricted_screen(self):
        run_adb = scripted_dump(
            [ATTACH_DUMP, RESTRICTED_DUMP, RESTRICTED_DUMP, RESTRICTED_DUMP]
        )

        with patch(
            "adb_automation.media_picker.MEDIA_ITEM_TIMEOUT_SECONDS", 0
        ), patch("adb_automation.media_picker.SOURCE_TIMEOUT_SECONDS", 0):
            with self.assertRaisesRegex(
                WhatsAppRestrictedError,
                "^WhatsApp is restricted\\.$",
            ):
                media_picker.select_latest_media_from_attach_menu(
                    "serial",
                    WHATSAPP_PACKAGE,
                    mime_type="audio/mpeg",
                    run_adb_command=run_adb,
                    sleep=lambda seconds: None,
                )


class EnterCaptionAndSendTests(unittest.TestCase):
    def test_sends_without_caption_when_none_given(self):
        commands = []

        def fake_run_adb(command, serial=None):
            if command[:2] == ["shell", "uiautomator"]:
                return ""
            if command[:2] == ["shell", "cat"]:
                return SEND_DUMP
            commands.append(command)
            return ""

        media_picker.enter_caption_and_send(
            "serial",
            WHATSAPP_PACKAGE,
            caption=None,
            run_adb_command=fake_run_adb,
            sleep=lambda seconds: None,
        )
        self.assertEqual(commands, [["shell", "input", "tap", "530", "930"]])

    def test_types_caption_before_sending(self):
        dumps = [CAPTION_DUMP, SEND_DUMP]
        commands = []

        def fake_run_adb(command, serial=None):
            if command[:2] == ["shell", "uiautomator"]:
                return ""
            if command[:2] == ["shell", "cat"]:
                return dumps.pop(0)
            commands.append(command)
            return ""

        media_picker.enter_caption_and_send(
            "serial",
            WHATSAPP_PACKAGE,
            caption="hello",
            run_adb_command=fake_run_adb,
            sleep=lambda seconds: None,
        )
        self.assertIn(["shell", "input", "tap", "300", "825"], commands)
        self.assertIn(["shell", "input", "text", "hello"], commands)

    def test_warns_and_sends_without_caption_when_field_missing(self):
        # SEND_DUMP has no caption element, so the same dump content serves both
        # the (failing) caption search and the (succeeding) send-button search
        # regardless of how many times the caption search polls before timing out.
        def run_adb(command, serial=None):
            if command[:2] == ["shell", "uiautomator"]:
                return ""
            return SEND_DUMP

        with patch(
            "adb_automation.media_picker.CAPTION_TIMEOUT_SECONDS", 0.01
        ), patch("builtins.print") as mock_print:
            media_picker.enter_caption_and_send(
                "serial",
                WHATSAPP_PACKAGE,
                caption="hello",
                run_adb_command=run_adb,
                sleep=lambda seconds: None,
            )
        self.assertTrue(
            any("Caption field not found" in call.args[0] for call in mock_print.call_args_list)
        )

    def test_raises_when_send_button_not_found(self):
        run_adb = scripted_dump([EMPTY_DUMP])

        with patch("adb_automation.media_picker.SEND_TIMEOUT_SECONDS", 0.01), \
            self.assertRaisesRegex(AutomationError, "Send button not found"):
            media_picker.enter_caption_and_send(
                "serial",
                WHATSAPP_PACKAGE,
                caption=None,
                run_adb_command=run_adb,
                sleep=lambda seconds: None,
            )

    def test_raises_restricted_when_send_button_is_hidden_by_restricted_screen(self):
        run_adb = scripted_dump([RESTRICTED_DUMP, RESTRICTED_DUMP])

        with patch("adb_automation.media_picker.SEND_TIMEOUT_SECONDS", 0):
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


class SendMediaViaGalleryPickerTests(unittest.TestCase):
    def test_stages_opens_chat_selects_media_sends_and_cleans_up(self):
        calls = []

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
        cleanup_staged_media.assert_called_once_with(
            "serial", "/sdcard/DCIM/Camera/IMG_1.jpg", run_adb_command=media_picker.run_adb
        )

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
            side_effect=AutomationError("Attach button not found."),
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

    def test_reports_when_chat_does_not_open_before_attach_flow(self):
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
