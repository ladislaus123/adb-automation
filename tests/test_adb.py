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


if __name__ == "__main__":
    unittest.main()
