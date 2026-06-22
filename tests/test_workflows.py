import unittest
from unittest.mock import patch

from adb_automation import devices, workflows
from adb_automation.errors import AutomationError
from tests.fake_mariadb import FakeMariaDBConnection


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.conn = FakeMariaDBConnection()

    def tearDown(self):
        self.conn.close()

    def test_send_with_device_lease_releases_after_failure(self):
        devices.add_device(self.conn, "phone-01", "192.168.10.21", 5555)

        with patch("builtins.print"), patch(
            "adb_automation.workflows.ensure_device_ready"
        ), patch("adb_automation.workflows.mark_device_seen"), patch(
            "adb_automation.workflows.send_whatsapp",
            side_effect=AutomationError("boom"),
        ):
            with self.assertRaises(AutomationError):
                workflows.send_with_device_lease(
                    self.conn,
                    "phone-01",
                    "5511999999999",
                    "hello",
                    None,
                    "worker-a",
                    600,
                )

        released = devices.find_device(self.conn, "phone-01")
        self.assertIsNone(released["worker_id"])
        self.assertIsNone(released["locked_until"])

    def test_send_validation_happens_before_lease(self):
        devices.add_device(self.conn, "phone-01", "192.168.10.21", 5555)

        with self.assertRaises(ValueError):
            workflows.send_with_device_lease(
                self.conn, "phone-01", "", None, None, "worker-a", 600
            )

        released = devices.find_device(self.conn, "phone-01")
        self.assertIsNone(released["worker_id"])
        self.assertIsNone(released["locked_until"])

    def test_send_with_device_lease_passes_business_flag_to_whatsapp(self):
        devices.add_device(self.conn, "phone-01", "192.168.10.21", 5555)

        with patch("builtins.print"), patch(
            "adb_automation.workflows.ensure_device_ready"
        ), patch("adb_automation.workflows.mark_device_seen"), patch(
            "adb_automation.workflows.send_whatsapp"
        ) as send_whatsapp:
            workflows.send_with_device_lease(
                self.conn,
                "phone-01",
                "5511999999999",
                "hello",
                None,
                "worker-a",
                600,
                business=True,
            )

        send_whatsapp.assert_called_once_with(
            "192.168.10.21:5555",
            "5511999999999",
            text="hello",
            file_path=None,
            business=True,
        )

    def test_send_with_device_lease_releases_exact_acquired_lease(self):
        leased_device = {
            "id": 7,
            "name": "phone-01",
            "ip": "192.168.10.21",
            "port": 5555,
            "locked_until": "2026-06-16T19:45:00+00:00",
        }

        with patch("builtins.print"), patch(
            "adb_automation.workflows.acquire_device_lease",
            return_value=leased_device,
        ), patch("adb_automation.workflows.ensure_device_ready"), patch(
            "adb_automation.workflows.mark_device_seen"
        ), patch("adb_automation.workflows.send_whatsapp"), patch(
            "adb_automation.workflows.release_device_lease"
        ) as release_device_lease:
            workflows.send_with_device_lease(
                self.conn,
                "phone-01",
                "5511999999999",
                "hello",
                None,
                "worker-a",
                600,
            )

        release_device_lease.assert_called_once_with(
            self.conn,
            7,
            "worker-a",
            "2026-06-16T19:45:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()
