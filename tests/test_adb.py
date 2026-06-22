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
            ["adb", "-s", "192.168.10.21:5555", "shell", "id"],
        )

    def test_run_adb_does_not_target_global_commands(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr=""
        )
        with patch("adb_automation.adb.subprocess.run", return_value=completed) as run:
            output = adb.run_adb(["devices"])

        self.assertEqual(output, "ok")
        self.assertEqual(run.call_args.args[0], ["adb", "devices"])

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


if __name__ == "__main__":
    unittest.main()
