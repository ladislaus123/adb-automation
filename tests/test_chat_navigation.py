import unittest
from unittest.mock import patch

from adb_automation import chat_navigation
from adb_automation.config import WHATSAPP_MESSENGER_PACKAGE


class FakeSelector:
    def __init__(self, exists=False, text="", info=None, click_error=None):
        self.exists = exists
        self.text = text
        self.info = info or {}
        self.clicked = False
        self.click_error = click_error
        self.set_text_values = []
        self.clear_calls = 0

    def get_text(self):
        return self.text

    def click(self):
        if self.click_error is not None:
            raise self.click_error
        self.clicked = True

    def set_text(self, value):
        self.set_text_values.append(value)
        self.text = value

    def clear_text(self):
        self.clear_calls += 1
        self.text = ""


class FakeDevice:
    def __init__(self):
        self.selectors = {}
        self.calls = []

    def add_selector(self, selector_kwargs, text="", info=None, click_error=None):
        selector = FakeSelector(
            exists=True, text=text, info=info, click_error=click_error
        )
        self.selectors[self._key(selector_kwargs)] = selector
        return selector

    def __call__(self, **selector_kwargs):
        self.calls.append(selector_kwargs)
        return self.selectors.get(self._key(selector_kwargs), FakeSelector())

    def _key(self, selector_kwargs):
        return tuple(sorted(selector_kwargs.items()))


class ChatNavigationSelectorTests(unittest.TestCase):
    def test_regular_whatsapp_extended_fab_is_clicked(self):
        device = FakeDevice()
        target = device.add_selector(
            {"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/fabText"}
        )

        clicked = chat_navigation.click_first_existing(
            device,
            chat_navigation.new_chat_fab_selectors(WHATSAPP_MESSENGER_PACKAGE),
            timeout=0,
        )

        self.assertTrue(clicked)
        self.assertTrue(target.clicked)

    def test_modern_search_result_name_id_matches_phone_digits(self):
        device = FakeDevice()
        target = device.add_selector(
            {
                "resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/name",
                "instance": 0,
            },
            text="+55 55 4093-2270",
        )

        row = chat_navigation.find_matching_result_row(
            device,
            WHATSAPP_MESSENGER_PACKAGE,
            "555540932270",
        )

        self.assertIs(row, target)

    def test_invite_only_search_result_is_not_treated_as_chat(self):
        device = FakeDevice()
        device.add_selector(
            {
                "resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/name",
                "instance": 0,
            },
            text="+55 55 4093-2270",
        )
        device.add_selector(
            {
                "resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/action_btn",
                "text": "CONVIDAR",
            }
        )

        row = chat_navigation.find_matching_result_row(
            device,
            WHATSAPP_MESSENGER_PACKAGE,
            "555540932270",
            allow_first_visible=True,
        )

        self.assertIsNone(row)

    def test_search_can_click_first_real_result_when_contact_name_has_no_digits(self):
        device = FakeDevice()
        target = device.add_selector(
            {
                "resourceId": (
                    f"{WHATSAPP_MESSENGER_PACKAGE}:id/conversations_row_contact_name"
                ),
                "instance": 0,
            },
            text="Chris",
        )

        row = chat_navigation.find_matching_result_row(
            device,
            WHATSAPP_MESSENGER_PACKAGE,
            "555540932270",
            allow_first_visible=True,
        )

        self.assertIs(row, target)

    def test_push_name_row_returns_clickable_container_not_name(self):
        # The saved contact shows its push-name (no digits); the clickable
        # ancestor row_container must be returned, not the non-clickable name.
        device = FakeDevice()
        container = device.add_selector(
            {"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/row_container", "instance": 0}
        )
        name = device.add_selector(
            {"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/name", "instance": 0},
            text="Chris",
        )

        row = chat_navigation.find_matching_result_row(
            device,
            WHATSAPP_MESSENGER_PACKAGE,
            "555540932270",
            allow_first_visible=True,
        )

        self.assertIs(row, container)
        self.assertIsNot(row, name)

    def test_digit_match_returns_container_when_present(self):
        device = FakeDevice()
        container = device.add_selector(
            {"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/row_container", "instance": 0}
        )
        device.add_selector(
            {"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/name", "instance": 0},
            text="+55 55 4093-2270",
        )

        row = chat_navigation.find_matching_result_row(
            device,
            WHATSAPP_MESSENGER_PACKAGE,
            "555540932270",
        )

        self.assertIs(row, container)

    def test_photo_content_desc_supplies_number_for_matching(self):
        device = FakeDevice()
        container = device.add_selector(
            {"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/row_container", "instance": 0}
        )
        device.add_selector(
            {"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/photo", "instance": 0},
            info={"contentDescription": "Foto de +55 55 4093-2270"},
        )

        row = chat_navigation.find_matching_result_row(
            device,
            WHATSAPP_MESSENGER_PACKAGE,
            "555540932270",
        )

        self.assertIs(row, container)


class EnsureHomeTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("adb_automation.chat_navigation.time.sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_skips_force_stop_when_already_on_home(self):
        device = FakeDevice()
        device.add_selector(
            {"resourceId": f"{WHATSAPP_MESSENGER_PACKAGE}:id/fab"}
        )
        commands = []

        with patch("builtins.print"):
            result = chat_navigation.ensure_whatsapp_home(
                "192.168.10.21:5555",
                device,
                WHATSAPP_MESSENGER_PACKAGE,
                run_adb_command=lambda command, serial=None: commands.append(command)
                or "",
            )

        self.assertTrue(result)
        self.assertEqual(commands, [])

    def test_force_stops_as_last_resort_when_home_never_appears(self):
        device = FakeDevice()
        commands = []

        with patch("builtins.print"), patch(
            "adb_automation.chat_navigation.HOME_QUICK_CHECK_SECONDS", 0
        ), patch(
            "adb_automation.chat_navigation.HOME_RETRY_TIMEOUT_SECONDS", 0
        ):
            result = chat_navigation.ensure_whatsapp_home(
                "192.168.10.21:5555",
                device,
                WHATSAPP_MESSENGER_PACKAGE,
                run_adb_command=lambda command, serial=None: commands.append(command)
                or "",
                timeout=0,
            )

        self.assertFalse(result)
        self.assertIn(
            ["shell", "am", "force-stop", WHATSAPP_MESSENGER_PACKAGE], commands
        )
        self.assertIn(
            ["shell", "input", "keyevent", "KEYCODE_BACK"], commands
        )


class TapElementTests(unittest.TestCase):
    def test_direct_click_is_used_when_it_succeeds(self):
        selector = FakeSelector(exists=True)
        commands = []

        result = chat_navigation.tap_element(
            selector,
            "192.168.10.21:5555",
            run_adb_command=lambda command, serial=None: commands.append(command),
        )

        self.assertTrue(result)
        self.assertTrue(selector.clicked)
        self.assertEqual(commands, [])

    def test_falls_back_to_coordinate_tap_when_click_raises(self):
        selector = FakeSelector(
            exists=True,
            click_error=RuntimeError("not clickable"),
            info={"bounds": {"left": 0, "top": 100, "right": 200, "bottom": 300}},
        )
        commands = []

        with patch("builtins.print"):
            result = chat_navigation.tap_element(
                selector,
                "192.168.10.21:5555",
                run_adb_command=lambda command, serial=None: commands.append(command)
                or "",
            )

        self.assertTrue(result)
        self.assertEqual(commands, [["shell", "input", "tap", "100", "200"]])

    def test_returns_false_when_click_raises_and_no_bounds(self):
        selector = FakeSelector(exists=True, click_error=RuntimeError("nope"))

        with patch("builtins.print"):
            result = chat_navigation.tap_element(
                selector,
                "192.168.10.21:5555",
                run_adb_command=lambda command, serial=None: "",
            )

        self.assertFalse(result)

    def test_contact_picker_lookup_does_not_click_arbitrary_named_row(self):
        device = FakeDevice()
        device.add_selector(
            {
                "resourceId": (
                    f"{WHATSAPP_MESSENGER_PACKAGE}:id/conversations_row_contact_name"
                ),
                "instance": 0,
            },
            text="Chris",
        )

        row = chat_navigation.find_matching_result_row(
            device,
            WHATSAPP_MESSENGER_PACKAGE,
            "555540932270",
        )

        self.assertIsNone(row)


class ContactPhoneEntryTests(unittest.TestCase):
    PACKAGE = WHATSAPP_MESSENGER_PACKAGE
    DIGITS = "47997571861"

    def setUp(self):
        self.device = FakeDevice()
        self.adb_commands = []
        patcher = patch("adb_automation.chat_navigation.time.sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_run_adb(self, command, serial=None):
        self.adb_commands.append(command)
        return ""

    def add_reader(self, text=""):
        reader = FakeSelector(exists=True, text=text)
        layout = self.device.add_selector(
            {"resourceId": f"{self.PACKAGE}:id/phone_input_layout"}
        )
        layout.child = lambda **kwargs: reader
        return reader

    def input_text_commands(self):
        return [
            command
            for command in self.adb_commands
            if command[:3] == ["shell", "input", "text"]
        ]

    def test_typed_number_is_verified_via_stable_reader(self):
        # Regression: the placeholder selector no longer matches a filled
        # field, so the read-back must use the phone_input_layout child.
        reader = self.add_reader()
        field = FakeSelector(exists=True, text="Telefone")
        field.set_text = lambda value: reader.set_text(value)

        with patch("builtins.print"):
            result = chat_navigation.enter_contact_phone_number(
                "192.168.10.21:5555",
                self.device,
                self.PACKAGE,
                field,
                self.DIGITS,
                run_adb_command=self.fake_run_adb,
            )

        self.assertTrue(result)
        self.assertEqual(reader.text, self.DIGITS)
        self.assertEqual(self.input_text_commands(), [])

    def test_mismatch_is_retyped_through_reader_not_adb_input(self):
        reader = self.add_reader()
        field = FakeSelector(exists=True, text="Telefone")
        # Simulate the first typing corrupting the field (doubled digits).
        field.set_text = lambda value: reader.set_text(value + value[:6])

        with patch("builtins.print"):
            result = chat_navigation.enter_contact_phone_number(
                "192.168.10.21:5555",
                self.device,
                self.PACKAGE,
                field,
                self.DIGITS,
                run_adb_command=self.fake_run_adb,
            )

        self.assertTrue(result)
        self.assertEqual(reader.clear_calls, 1)
        self.assertEqual(reader.text, self.DIGITS)
        # adb `input text` appends instead of replacing; it must never be
        # used to retype into a possibly dirty field.
        self.assertEqual(self.input_text_commands(), [])

    def test_missing_reader_assumes_typed_text_is_correct(self):
        field = FakeSelector(exists=True, text="Telefone")

        with patch("builtins.print"):
            result = chat_navigation.enter_contact_phone_number(
                "192.168.10.21:5555",
                self.device,
                self.PACKAGE,
                field,
                self.DIGITS,
                run_adb_command=self.fake_run_adb,
            )

        self.assertTrue(result)
        self.assertEqual(field.set_text_values, [self.DIGITS])
        self.assertEqual(self.input_text_commands(), [])

    def test_reader_falls_back_to_focused_edit_text(self):
        focused = self.device.add_selector(
            {"className": "android.widget.EditText", "focused": True}
        )
        focused.text = self.DIGITS

        reader = chat_navigation.phone_field_reader(self.device, self.PACKAGE)

        self.assertIs(reader, focused)


class NumberNotOnWhatsappGuardTests(unittest.TestCase):
    PACKAGE = WHATSAPP_MESSENGER_PACKAGE

    def test_detects_form_validation_message(self):
        device = FakeDevice()
        device.add_selector(
            {
                "resourceId": f"{self.PACKAGE}:id/number_on_whatsapp_message",
                "textContains": "não está no WhatsApp",
            }
        )

        self.assertTrue(
            chat_navigation.detect_number_not_on_whatsapp_form(
                device, self.PACKAGE
            )
        )

    def test_clean_form_passes(self):
        device = FakeDevice()

        self.assertFalse(
            chat_navigation.detect_number_not_on_whatsapp_form(
                device, self.PACKAGE
            )
        )


if __name__ == "__main__":
    unittest.main()
