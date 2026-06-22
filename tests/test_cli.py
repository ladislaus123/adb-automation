import unittest
from unittest.mock import Mock, patch

from adb_automation import cli


class CliTests(unittest.TestCase):
    def test_devices_add_routes_to_device_repo(self):
        conn = Mock()
        device = {"id": 1, "name": "phone-01", "ip": "192.168.10.21", "port": 5555}

        with patch("builtins.print"), patch(
            "adb_automation.cli.open_database", return_value=conn
        ), patch("adb_automation.cli.init_database"), patch(
            "adb_automation.cli.add_device", return_value=device
        ) as add_device:
            result = cli.main(
                [
                    "--database",
                    ":memory:",
                    "devices",
                    "add",
                    "--name",
                    "phone-01",
                    "--ip",
                    "192.168.10.21",
                    "--port",
                    "5555",
                ]
            )

        self.assertEqual(result, 0)
        add_device.assert_called_once_with(conn, "phone-01", "192.168.10.21", 5555)
        conn.close.assert_called_once()

    def test_devices_list_routes_to_device_repo(self):
        conn = Mock()

        with patch("builtins.print"), patch(
            "adb_automation.cli.open_database", return_value=conn
        ), patch("adb_automation.cli.init_database"), patch(
            "adb_automation.cli.list_devices", return_value=[]
        ) as list_devices:
            result = cli.main(["--database", ":memory:", "devices", "list"])

        self.assertEqual(result, 0)
        list_devices.assert_called_once_with(conn)
        conn.close.assert_called_once()

    def test_devices_unlock_routes_to_device_repo(self):
        conn = Mock()
        device = {"id": 1, "name": "phone-01", "ip": "192.168.10.21", "port": 5555}

        with patch("builtins.print"), patch(
            "adb_automation.cli.open_database", return_value=conn
        ), patch("adb_automation.cli.init_database"), patch(
            "adb_automation.cli.unlock_device", return_value=device
        ) as unlock_device:
            result = cli.main(
                ["--database", ":memory:", "devices", "unlock", "--device", "phone-01"]
            )

        self.assertEqual(result, 0)
        unlock_device.assert_called_once_with(conn, "phone-01")
        conn.close.assert_called_once()

    def test_send_routes_to_workflow(self):
        conn = Mock()

        with patch("adb_automation.cli.open_database", return_value=conn), patch(
            "adb_automation.cli.init_database"
        ), patch("adb_automation.cli.send_with_device_lease") as send_with_device_lease:
            result = cli.main(
                [
                    "--database",
                    ":memory:",
                    "send",
                    "--device",
                    "phone-01",
                    "--phone",
                    "5511999999999",
                    "--text",
                    "hello",
                    "--worker-id",
                    "worker-a",
                    "--lease-seconds",
                    "30",
                ]
            )

        self.assertEqual(result, 0)
        send_with_device_lease.assert_called_once_with(
            conn,
            "phone-01",
            "5511999999999",
            "hello",
            None,
            "worker-a",
            30,
            business=False,
        )
        conn.close.assert_called_once()

    def test_send_business_routes_to_workflow(self):
        conn = Mock()

        with patch("adb_automation.cli.open_database", return_value=conn), patch(
            "adb_automation.cli.init_database"
        ), patch("adb_automation.cli.send_with_device_lease") as send_with_device_lease:
            result = cli.main(
                [
                    "--database",
                    ":memory:",
                    "send",
                    "--device",
                    "phone-01",
                    "--phone",
                    "5511999999999",
                    "--text",
                    "hello",
                    "-business",
                ]
            )

        self.assertEqual(result, 0)
        send_with_device_lease.assert_called_once_with(
            conn,
            "phone-01",
            "5511999999999",
            "hello",
            None,
            None,
            600,
            business=True,
        )
        conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
