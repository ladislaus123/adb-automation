import subprocess
import unittest
from unittest.mock import patch

from adb_automation import adb


class AdbCommandTests(unittest.TestCase):
    def test_run_adb_targets_serial_when_provided(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr=""
        )
        with patch("adb_automation.adb.subprocess.run", return_value=completed) as run:
            output = adb.run_adb(["shell", "id"], serial="192.168.10.21:5555")

        self.assertEqual(output, "ok")
        self.assertEqual(
            run.call_args.args[0],
            [adb._ADB, "-s", "192.168.10.21:5555", "shell", "id"],
        )

    def test_run_adb_does_not_target_global_commands(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr=""
        )
        with patch("adb_automation.adb.subprocess.run", return_value=completed) as run:
            output = adb.run_adb(["devices"])

        self.assertEqual(output, "ok")
        self.assertEqual(run.call_args.args[0], [adb._ADB, "devices"])

    def test_connect_wifi_device_runs_adb_connect(self):
        with patch(
            "adb_automation.adb.run_adb",
            return_value="connected to 192.168.10.21:5555\n",
        ) as run_adb, patch("builtins.print"):
            output = adb.connect_wifi_device("192.168.10.21:5555")

        self.assertEqual(output, "connected to 192.168.10.21:5555")
        run_adb.assert_called_once_with(["connect", "192.168.10.21:5555"])

    def test_pair_wifi_device_runs_adb_pair(self):
        with patch(
            "adb_automation.adb.run_adb", return_value="Successfully paired\n"
        ) as run_adb, patch("builtins.print"):
            output = adb.pair_wifi_device("192.168.10.21", 37123, "123456")

        self.assertEqual(output, "Successfully paired")
        run_adb.assert_called_once_with(
            ["pair", "192.168.10.21:37123", "123456"]
        )

    def test_ensure_wifi_device_ready_connects_then_checks_visibility(self):
        with patch("adb_automation.adb.connect_wifi_device") as connect_wifi_device, patch(
            "adb_automation.adb.get_connected_device_states",
            return_value={"192.168.10.21:5555": "device"},
        ):
            adb.ensure_device_ready("192.168.10.21:5555")

        connect_wifi_device.assert_called_once_with("192.168.10.21:5555")

    def test_ensure_usb_device_ready_only_checks_visibility(self):
        with patch("adb_automation.adb.connect_wifi_device") as connect_wifi_device, patch(
            "adb_automation.adb.get_connected_device_states",
            return_value={"R5CW123ABC": "device"},
        ):
            adb.ensure_device_ready("R5CW123ABC", adb_transport="usb")

        connect_wifi_device.assert_not_called()

    def test_ensure_usb_device_ready_reports_bad_states(self):
        scenarios = (
            ("unauthorized", "Check authorization"),
            ("offline", "is offline"),
            (None, "not visible"),
        )

        for state, expected in scenarios:
            with self.subTest(state=state), patch(
                "adb_automation.adb.connect_wifi_device"
            ) as connect_wifi_device, patch(
                "adb_automation.adb.get_connected_device_states",
                return_value={}
                if state is None
                else {"R5CW123ABC": state},
            ):
                with self.assertRaisesRegex(adb.AdbError, expected):
                    adb.ensure_device_ready("R5CW123ABC", adb_transport="usb")
                connect_wifi_device.assert_not_called()

    def test_wake_and_unlock_wakes_off_screen_and_swipes(self):
        commands = []

        def fake_run_adb(command, serial=None):
            commands.append((command, serial))
            if command == ["shell", "dumpsys", "power"]:
                return "mWakefulness=Asleep\nmInteractive=false\n"
            if command == ["shell", "dumpsys", "window"]:
                return "mShowingLockscreen=true\n"
            if command == ["shell", "wm", "size"]:
                return "Physical size: 1080x2400\n"
            return ""

        sleeps = []
        with patch("builtins.print"):
            adb.wake_and_unlock_device(
                "192.168.10.21:5555",
                run_adb_command=fake_run_adb,
                sleep=sleeps.append,
            )

        self.assertEqual(
            commands,
            [
                (["shell", "dumpsys", "power"], "192.168.10.21:5555"),
                (
                    ["shell", "input", "keyevent", "KEYCODE_WAKEUP"],
                    "192.168.10.21:5555",
                ),
                (["shell", "dumpsys", "window"], "192.168.10.21:5555"),
                (["shell", "wm", "size"], "192.168.10.21:5555"),
                (
                    [
                        "shell",
                        "input",
                        "swipe",
                        "540",
                        "2040",
                        "540",
                        "600",
                        "300",
                    ],
                    "192.168.10.21:5555",
                ),
            ],
        )
        self.assertEqual(sleeps, [adb.WAKE_SETTLE_SECONDS, adb.UNLOCK_SETTLE_SECONDS])

    def test_wake_and_unlock_does_not_touch_awake_unlocked_screen(self):
        commands = []

        def fake_run_adb(command, serial=None):
            commands.append((command, serial))
            if command == ["shell", "dumpsys", "power"]:
                return "mWakefulness=Awake\nmInteractive=true\n"
            if command == ["shell", "dumpsys", "window"]:
                return "mShowingLockscreen=false\n"
            return ""

        with patch("builtins.print"):
            adb.wake_and_unlock_device(
                "192.168.10.21:5555",
                run_adb_command=fake_run_adb,
                sleep=lambda seconds: None,
            )

        self.assertEqual(
            commands,
            [
                (["shell", "dumpsys", "power"], "192.168.10.21:5555"),
                (["shell", "dumpsys", "window"], "192.168.10.21:5555"),
            ],
        )

    def test_portrait_orientation_guard_forces_and_restores_rotation(self):
        commands = []
        serial = "192.168.10.21:5555"

        def fake_run_adb(command, serial=None):
            commands.append((command, serial))
            if command == [
                "shell",
                "settings",
                "get",
                "system",
                "accelerometer_rotation",
            ]:
                return "1\n"
            if command == ["shell", "settings", "get", "system", "user_rotation"]:
                return "3\n"
            return ""

        with adb.portrait_orientation_guard(serial, run_adb_command=fake_run_adb):
            commands.append((["inside"], serial))

        self.assertEqual(
            commands,
            [
                (
                    [
                        "shell",
                        "settings",
                        "get",
                        "system",
                        "accelerometer_rotation",
                    ],
                    serial,
                ),
                (
                    ["shell", "settings", "get", "system", "user_rotation"],
                    serial,
                ),
                (
                    [
                        "shell",
                        "settings",
                        "put",
                        "system",
                        "accelerometer_rotation",
                        "0",
                    ],
                    serial,
                ),
                (
                    ["shell", "settings", "put", "system", "user_rotation", "0"],
                    serial,
                ),
                (["inside"], serial),
                (
                    [
                        "shell",
                        "settings",
                        "put",
                        "system",
                        "accelerometer_rotation",
                        "1",
                    ],
                    serial,
                ),
                (
                    ["shell", "settings", "put", "system", "user_rotation", "3"],
                    serial,
                ),
            ],
        )

    def test_portrait_orientation_guard_continues_when_force_fails(self):
        commands = []
        serial = "192.168.10.21:5555"

        def fake_run_adb(command, serial=None):
            commands.append((command, serial))
            if command == [
                "shell",
                "settings",
                "get",
                "system",
                "accelerometer_rotation",
            ]:
                return "1\n"
            if command == ["shell", "settings", "get", "system", "user_rotation"]:
                return "2\n"
            if command == [
                "shell",
                "settings",
                "put",
                "system",
                "accelerometer_rotation",
                "0",
            ]:
                raise adb.AdbError("permission denied")
            return ""

        with patch("builtins.print") as print_mock:
            with adb.portrait_orientation_guard(serial, run_adb_command=fake_run_adb):
                commands.append((["inside"], serial))

        self.assertIn((["inside"], serial), commands)
        self.assertIn(
            (
                [
                    "shell",
                    "settings",
                    "put",
                    "system",
                    "accelerometer_rotation",
                    "1",
                ],
                serial,
            ),
            commands,
        )
        self.assertIn(
            (
                ["shell", "settings", "put", "system", "user_rotation", "2"],
                serial,
            ),
            commands,
        )
        print_mock.assert_any_call(
            "[WARN] Could not force portrait orientation: permission denied"
        )

    def test_portrait_orientation_guard_restores_after_body_failure(self):
        commands = []
        serial = "192.168.10.21:5555"

        def fake_run_adb(command, serial=None):
            commands.append((command, serial))
            if command == [
                "shell",
                "settings",
                "get",
                "system",
                "accelerometer_rotation",
            ]:
                return "0\n"
            if command == ["shell", "settings", "get", "system", "user_rotation"]:
                return "1\n"
            return ""

        with self.assertRaisesRegex(RuntimeError, "send failed"):
            with adb.portrait_orientation_guard(serial, run_adb_command=fake_run_adb):
                raise RuntimeError("send failed")

        self.assertEqual(
            commands[-2:],
            [
                (
                    [
                        "shell",
                        "settings",
                        "put",
                        "system",
                        "accelerometer_rotation",
                        "0",
                    ],
                    serial,
                ),
                (
                    ["shell", "settings", "put", "system", "user_rotation", "1"],
                    serial,
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
