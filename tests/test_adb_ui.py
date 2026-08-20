import unittest

from adb_automation import adb_ui
from adb_automation.errors import AdbError, AutomationError

SAMPLE_DUMP = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="com.whatsapp:id/input_attach_button" class="android.widget.ImageButton" content-desc="Attach" clickable="true" bounds="[10,20][50,60]" />
  <node index="1" text="" resource-id="com.whatsapp:id/media_item_view" class="android.widget.ImageView" content-desc="Photo" clickable="true" bounds="[100,200][300,400]" />
  <node index="2" text="" resource-id="com.whatsapp:id/media_item_view" class="android.widget.ImageView" content-desc="Photo 2" clickable="true" bounds="[400,200][600,400]" />
  <node index="3" text="Send" resource-id="com.whatsapp:id/send" class="android.widget.ImageButton" content-desc="" clickable="true" bounds="[500,900][560,960]" />
</hierarchy>
"""


class ParseUiDumpTests(unittest.TestCase):
    def test_parse_ui_dump_flattens_all_nodes(self):
        elements = adb_ui.parse_ui_dump(SAMPLE_DUMP)
        self.assertEqual(len(elements), 4)
        self.assertEqual(elements[0]["resource_id"], "com.whatsapp:id/input_attach_button")
        self.assertEqual(elements[0]["content_desc"], "Attach")

    def test_parse_ui_dump_raises_on_invalid_xml(self):
        with self.assertRaises(AutomationError):
            adb_ui.parse_ui_dump("<not-valid-xml")


class BoundsTests(unittest.TestCase):
    def test_parse_bounds(self):
        self.assertEqual(adb_ui.parse_bounds("[10,20][50,60]"), (10, 20, 50, 60))

    def test_parse_bounds_returns_none_when_missing(self):
        self.assertIsNone(adb_ui.parse_bounds(""))
        self.assertIsNone(adb_ui.parse_bounds(None))

    def test_bounds_center(self):
        self.assertEqual(adb_ui.bounds_center("[10,20][50,60]"), (30, 40))


class FindFirstTests(unittest.TestCase):
    def setUp(self):
        self.elements = adb_ui.parse_ui_dump(SAMPLE_DUMP)

    def test_find_first_by_resource_id_returns_first_match_in_document_order(self):
        found = adb_ui.find_first(
            self.elements, [("id", "com.whatsapp:id/media_item_view")]
        )
        self.assertEqual(found["content_desc"], "Photo")

    def test_find_first_by_accessibility(self):
        found = adb_ui.find_first(self.elements, [("accessibility", "Attach")])
        self.assertEqual(found["resource_id"], "com.whatsapp:id/input_attach_button")

    def test_find_first_falls_through_selector_list(self):
        found = adb_ui.find_first(
            self.elements,
            [("id", "does.not:exist"), ("text", "Send")],
        )
        self.assertEqual(found["resource_id"], "com.whatsapp:id/send")

    def test_find_first_returns_none_when_no_selector_matches(self):
        self.assertIsNone(adb_ui.find_first(self.elements, [("id", "missing")]))


class TapTests(unittest.TestCase):
    def test_tap_point_runs_input_tap(self):
        commands = []
        adb_ui.tap_point(
            "serial", 12, 34, run_adb_command=lambda c, serial=None: commands.append(c)
        )
        self.assertEqual(commands, [["shell", "input", "tap", "12", "34"]])

    def test_tap_element_taps_bounds_center(self):
        commands = []
        element = {"bounds": "[10,20][50,60]"}
        center = adb_ui.tap_element(
            "serial", element, run_adb_command=lambda c, serial=None: commands.append(c)
        )
        self.assertEqual(center, (30, 40))
        self.assertEqual(commands, [["shell", "input", "tap", "30", "40"]])

    def test_tap_element_raises_without_usable_bounds(self):
        with self.assertRaises(AutomationError):
            adb_ui.tap_element("serial", {"bounds": ""}, run_adb_command=lambda c, serial=None: None)


class DumpUiXmlSelfHealTests(unittest.TestCase):
    def test_dump_ui_xml_retries_after_clearing_stale_uiautomation(self):
        calls = []
        dump_command = ["shell", "uiautomator", "dump", adb_ui.DUMP_REMOTE_PATH]
        cat_command = ["shell", "cat", adb_ui.DUMP_REMOTE_PATH]
        pkill_command = ["shell", "pkill", "-f", "uiautomator"]

        def fake_run_adb(command, serial=None):
            calls.append(command)
            if command == dump_command:
                if calls.count(command) == 1:
                    raise AdbError(
                        "command failed: adb -s serial shell uiautomator dump "
                        "/sdcard/window_dump.xml"
                    )
                return ""
            if command == cat_command:
                return SAMPLE_DUMP
            if command[:2] == ["shell", "pkill"]:
                return ""
            raise AssertionError(f"unexpected command: {command}")

        xml_text = adb_ui.dump_ui_xml(
            "serial", run_adb_command=fake_run_adb, sleep=lambda seconds: None
        )

        self.assertEqual(xml_text, SAMPLE_DUMP)
        self.assertIn(pkill_command, calls)
        for name in adb_ui.STALE_APP_PROCESS_NAMES:
            self.assertIn(["shell", "pkill", "-9", "-x", name], calls)
        self.assertEqual(calls.count(dump_command), 2)

    def test_dump_ui_xml_does_not_retry_on_other_errors(self):
        def fake_run_adb(command, serial=None):
            if command == ["shell", "uiautomator", "dump", adb_ui.DUMP_REMOTE_PATH]:
                raise AdbError("device offline")
            raise AssertionError(f"unexpected command: {command}")

        with self.assertRaises(AdbError):
            adb_ui.dump_ui_xml("serial", run_adb_command=fake_run_adb)


class WaitAndClickTests(unittest.TestCase):
    def test_wait_for_first_retries_until_element_appears(self):
        dumps = ["<hierarchy></hierarchy>", SAMPLE_DUMP]
        sleeps = []

        def fake_run_adb(command, serial=None):
            if command[:2] == ["shell", "uiautomator"]:
                return ""
            return dumps.pop(0)

        found = adb_ui.wait_for_first(
            "serial",
            [("id", "com.whatsapp:id/send")],
            timeout=5,
            interval=0.01,
            run_adb_command=fake_run_adb,
            sleep=sleeps.append,
        )
        self.assertIsNotNone(found)
        self.assertEqual(found["resource_id"], "com.whatsapp:id/send")
        self.assertEqual(sleeps, [0.01])

    def test_wait_for_first_times_out_and_returns_none(self):
        ticks = {"count": 0}

        def fake_run_adb(command, serial=None):
            if command[:2] == ["shell", "uiautomator"]:
                return ""
            return "<hierarchy></hierarchy>"

        def fake_sleep(_seconds):
            ticks["count"] += 1

        found = adb_ui.wait_for_first(
            "serial",
            [("id", "missing")],
            timeout=0.05,
            interval=0.01,
            run_adb_command=fake_run_adb,
            sleep=fake_sleep,
        )

        self.assertIsNone(found)
        self.assertGreater(ticks["count"], 0)

    def test_click_first_taps_found_element_and_returns_true(self):
        commands = []

        def fake_run_adb(command, serial=None):
            if command[:2] == ["shell", "uiautomator"]:
                return ""
            if command[:2] == ["shell", "cat"]:
                return SAMPLE_DUMP
            commands.append(command)
            return ""

        result = adb_ui.click_first(
            "serial",
            [("id", "com.whatsapp:id/media_item_view")],
            timeout=1,
            interval=0.01,
            run_adb_command=fake_run_adb,
            sleep=lambda seconds: None,
        )
        self.assertTrue(result)
        self.assertEqual(commands, [["shell", "input", "tap", "200", "300"]])

    def test_click_first_returns_false_when_not_found(self):
        def fake_run_adb(command, serial=None):
            if command[:2] == ["shell", "uiautomator"]:
                return ""
            return "<hierarchy></hierarchy>"

        result = adb_ui.click_first(
            "serial",
            [("id", "missing")],
            timeout=0.02,
            interval=0.01,
            run_adb_command=fake_run_adb,
            sleep=lambda seconds: None,
        )
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
