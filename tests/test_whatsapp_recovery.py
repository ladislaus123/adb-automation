import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adb_automation.adb_ui import parse_ui_dump
from adb_automation.errors import ReviewUnavailableError, WhatsAppRecoveryError
from adb_automation.whatsapp_recovery import (
    RECOVERY_SCREEN_CAN_REGISTER,
    RECOVERY_SCREEN_LOGGED_IN,
    RECOVERY_SCREEN_PERMANENT_BAN,
    RECOVERY_SCREEN_RESTRICTED,
    RECOVERY_SCREEN_REVIEW_PENDING,
    capture_debug_dump,
    classify_elements,
    extract_otp_from_sms_dump,
    perform_relogin,
    read_sms_otp,
    request_account_review,
    split_country_and_national,
)

ROOT = Path(__file__).resolve().parents[1]


def element(text="", resource_id="", class_name="android.widget.TextView", bounds="[0,0][100,40]"):
    return {
        "text": text,
        "content_desc": "",
        "resource_id": resource_id,
        "class_name": class_name,
        "bounds": bounds,
        "clickable": True,
    }


class SelectorClassificationTests(unittest.TestCase):
    def test_restricted_chat_dump_is_classified_as_restricted(self):
        xml_text = (ROOT / "debug_nav_chat_verify.xml").read_text(encoding="utf-8")
        self.assertEqual(
            classify_elements(parse_ui_dump(xml_text)),
            RECOVERY_SCREEN_RESTRICTED,
        )

    def test_home_dump_is_classified_as_logged_in(self):
        xml_text = (ROOT / "dumps" / "whatsapp_home.xml").read_text(encoding="utf-8")
        self.assertEqual(
            classify_elements(parse_ui_dump(xml_text)),
            RECOVERY_SCREEN_LOGGED_IN,
        )

    def test_review_registration_and_ban_screens(self):
        self.assertEqual(
            classify_elements([element("Pedir análise")]),
            RECOVERY_SCREEN_RESTRICTED,
        )
        self.assertEqual(
            classify_elements([element("Estamos analisando sua conta")]),
            RECOVERY_SCREEN_REVIEW_PENDING,
        )
        self.assertEqual(
            classify_elements([element("You're not allowed to use WhatsApp")]),
            RECOVERY_SCREEN_PERMANENT_BAN,
        )
        self.assertEqual(
            classify_elements([element("Agree and continue")]),
            RECOVERY_SCREEN_CAN_REGISTER,
        )
        self.assertEqual(
            classify_elements([element("Verify your phone number")]),
            RECOVERY_SCREEN_CAN_REGISTER,
        )

    def test_permanent_ban_wins_over_a_review_button(self):
        elements = [
            element("You're not allowed to use WhatsApp"),
            element("Request a review"),
        ]
        self.assertEqual(classify_elements(elements), RECOVERY_SCREEN_PERMANENT_BAN)


class OtpAndPhoneSplitTests(unittest.TestCase):
    def test_extract_otp_prefers_a_whatsapp_sms(self):
        dump = "\n".join(
            [
                "Row: 0 address=VIVO, body=123456 is your bank code, date=1",
                "Row: 1 address=WhatsApp, body=Seu código do WhatsApp: 654-321, date=2",
            ]
        )
        self.assertEqual(extract_otp_from_sms_dump(dump), "654321")

    def test_extract_otp_falls_back_and_ignores_longer_numbers(self):
        self.assertEqual(extract_otp_from_sms_dump("body=code 111222"), "111222")
        self.assertIsNone(extract_otp_from_sms_dump("body=1234567"))
        self.assertIsNone(extract_otp_from_sms_dump(""))
        self.assertEqual(extract_otp_from_sms_dump("codigo 123 456"), "123456")

    def test_read_sms_otp_returns_none_when_adb_cannot_read_sms(self):
        def explode(*args, **kwargs):
            raise RuntimeError("permission denial")

        self.assertIsNone(read_sms_otp("serial", run_adb_command=explode))

    def test_split_country_and_national(self):
        self.assertEqual(
            split_country_and_national("5547999990000", "55"),
            ("55", "47999990000"),
        )
        self.assertEqual(
            split_country_and_national("5547999990000", ""),
            ("55", "47999990000"),
        )
        self.assertEqual(
            split_country_and_national("551133334444", ""),
            ("55", "1133334444"),
        )
        self.assertEqual(
            split_country_and_national("11999998888", ""),
            ("", "11999998888"),
        )
        self.assertEqual(
            split_country_and_national("5547999990000", "1"),
            ("1", "5547999990000"),
        )


class RecoveryUiTests(unittest.TestCase):
    def test_request_account_review_with_patched_dumps(self):
        screens = [
            [element("Pedir análise", bounds="[10,10][110,50]")],
            [element("Estamos analisando sua conta")],
            [element("Estamos analisando sua conta")],
        ]
        taps = []

        def dump_elements(*args, **kwargs):
            return screens.pop(0)

        def tap(serial, tapped, run_adb_command=None):
            taps.append(tapped["text"])
            return (60, 30)

        with patch(
            "adb_automation.whatsapp_recovery.dump_elements", side_effect=dump_elements
        ), patch("adb_automation.whatsapp_recovery.open_whatsapp"), patch(
            "adb_automation.whatsapp_recovery.tap_element", side_effect=tap
        ):
            state = request_account_review(
                "serial",
                "com.whatsapp",
                sleep=lambda seconds: None,
            )

        self.assertEqual(state, RECOVERY_SCREEN_REVIEW_PENDING)
        self.assertEqual(taps, ["Pedir análise"])
        self.assertEqual(screens, [])

    def test_request_account_review_requires_a_button(self):
        with patch(
            "adb_automation.whatsapp_recovery.dump_elements",
            return_value=[element("Sua conta foi restringida")],
        ), patch("adb_automation.whatsapp_recovery.open_whatsapp"):
            with self.assertRaises(ReviewUnavailableError):
                request_account_review("serial", "com.whatsapp", sleep=lambda seconds: None)

    def test_perform_relogin_types_the_national_number_and_uses_sms_fallback(self):
        phone_field = element(
            "",
            resource_id="com.whatsapp:id/registration_phone",
            class_name="android.widget.EditText",
            bounds="[20,80][200,120]",
        )
        country_field = element(
            "55",
            resource_id="com.whatsapp:id/registration_cc",
            class_name="android.widget.EditText",
            bounds="[0,80][40,120]",
        )
        screens = [
            [element("Concordar e continuar", bounds="[0,200][200,240]")],
            [country_field, phone_field],
            [element("Avançar", bounds="[0,300][80,340]")],
            [element("Sim", bounds="[0,300][80,340]")],
            [element("waiting")],
            [element("", resource_id="com.whatsapp:id/fab", bounds="[0,400][40,440]")],
        ]
        calls = []
        clock = {"t": 0}

        def dump_elements(*args, **kwargs):
            return screens.pop(0)

        def run_adb(command, serial=None):
            calls.append(command)
            return ""

        def monotonic():
            clock["t"] += 10
            return clock["t"]

        with patch(
            "adb_automation.whatsapp_recovery.dump_elements", side_effect=dump_elements
        ), patch("adb_automation.whatsapp_recovery.open_whatsapp"), patch(
            "adb_automation.whatsapp_recovery.otp_wait_seconds", return_value=0
        ), patch(
            "adb_automation.whatsapp_recovery.read_sms_otp", return_value="123456"
        ) as read_sms:
            state = perform_relogin(
                "serial",
                "com.whatsapp",
                "5547999990000",
                run_adb_command=run_adb,
                sleep=lambda seconds: None,
                monotonic=monotonic,
            )

        self.assertEqual(state, RECOVERY_SCREEN_LOGGED_IN)
        typed = [
            command[-1]
            for command in calls
            if command[:3] == ["shell", "input", "text"]
        ]
        self.assertIn("47999990000", typed)
        self.assertIn("123456", typed)
        read_sms.assert_called_once()

    def test_perform_relogin_requires_a_phone(self):
        with self.assertRaises(WhatsAppRecoveryError):
            perform_relogin("serial", "com.whatsapp", None, sleep=lambda seconds: None)

    def test_capture_debug_dump_writes_the_screen(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "adb_automation.whatsapp_recovery.dump_ui_xml",
            return_value="<hierarchy />",
        ):
            path = capture_debug_dump(
                "serial",
                "ban screen",
                directory=tmpdir,
                sleep=lambda seconds: None,
            )
            written = Path(path)
            self.assertEqual(written.name, "debug_recovery_ban_screen.xml")
            self.assertEqual(written.read_text(encoding="utf-8"), "<hierarchy />")
            self.assertEqual(written.parent, Path(tmpdir))


if __name__ == "__main__":
    unittest.main()
