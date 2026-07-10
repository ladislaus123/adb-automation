import unittest

from adb_automation import devices
from adb_automation.errors import DeviceLockError
from tests.fake_mariadb import FakeMariaDBConnection


class DeviceDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.conn = FakeMariaDBConnection()

    def tearDown(self):
        self.conn.close()

    def test_device_crud(self):
        device = devices.add_device(self.conn, "phone-01", "192.168.10.21", 5555)

        self.assertEqual(device["name"], "phone-01")
        self.assertEqual(device["ip"], "192.168.10.21")
        self.assertEqual(device["port"], 5555)
        self.assertEqual(
            devices.find_device(self.conn, "phone-01")["id"], device["id"]
        )
        self.assertEqual(
            devices.find_device(self.conn, str(device["id"]))["name"], "phone-01"
        )

    def test_active_lock_blocks_other_workers(self):
        devices.add_device(self.conn, "phone-01", "192.168.10.21", 5555)
        devices.acquire_device_lease(self.conn, "phone-01", "worker-a", 600)

        with self.assertRaises(DeviceLockError):
            devices.acquire_device_lease(self.conn, "phone-01", "worker-b", 600)

    def test_active_lock_blocks_same_worker(self):
        devices.add_device(self.conn, "phone-01", "192.168.10.21", 5555)
        devices.acquire_device_lease(self.conn, "phone-01", "worker-a", 600)

        with self.assertRaises(DeviceLockError):
            devices.acquire_device_lease(self.conn, "phone-01", "worker-a", 600)

    def test_expired_lock_can_be_reacquired(self):
        device = devices.add_device(self.conn, "phone-01", "192.168.10.21", 5555)
        devices.acquire_device_lease(self.conn, "phone-01", "worker-a", 600)
        self.conn.devices[0]["locked_until"] = "2000-01-01T00:00:00+00:00"

        leased = devices.acquire_device_lease(self.conn, "phone-01", "worker-b", 600)

        self.assertEqual(leased["worker_id"], "worker-b")

    def test_release_only_clears_same_worker(self):
        device = devices.add_device(self.conn, "phone-01", "192.168.10.21", 5555)
        lease = devices.acquire_device_lease(self.conn, "phone-01", "worker-a", 600)

        devices.release_device_lease(
            self.conn,
            device["id"],
            "worker-b",
            lease["locked_until"],
        )
        still_locked = devices.find_device(self.conn, "phone-01")
        self.assertEqual(still_locked["worker_id"], "worker-a")

        devices.release_device_lease(
            self.conn,
            device["id"],
            "worker-a",
            lease["locked_until"],
        )
        released = devices.find_device(self.conn, "phone-01")
        self.assertIsNone(released["worker_id"])
        self.assertIsNone(released["locked_until"])

    def test_stale_release_does_not_clear_newer_lease(self):
        device = devices.add_device(self.conn, "phone-01", "192.168.10.21", 5555)
        stale_lease = devices.acquire_device_lease(
            self.conn,
            "phone-01",
            "worker-a",
            600,
        )
        self.conn.devices[0]["locked_until"] = "2000-01-01T00:00:00+00:00"
        current_lease = devices.acquire_device_lease(
            self.conn,
            "phone-01",
            "worker-a",
            1200,
        )

        devices.release_device_lease(
            self.conn,
            device["id"],
            "worker-a",
            stale_lease["locked_until"],
        )
        still_locked = devices.find_device(self.conn, "phone-01")
        self.assertEqual(still_locked["worker_id"], "worker-a")
        self.assertEqual(still_locked["locked_until"], current_lease["locked_until"])

    def test_duplicate_device_is_rejected(self):
        devices.add_device(self.conn, "phone-01", "192.168.10.21", 5555)

        with self.assertRaises(ValueError):
            devices.add_device(self.conn, "phone-01", "192.168.10.22", 5555)

    def test_update_device_changes_name_ip_and_port(self):
        device = devices.add_device(self.conn, "phone-01", "192.168.10.21", 5555)

        updated = devices.update_device(
            self.conn,
            device["id"],
            name="phone-main",
            ip="192.168.10.22",
            port=45678,
        )

        self.assertEqual(updated["name"], "phone-main")
        self.assertEqual(updated["ip"], "192.168.10.22")
        self.assertEqual(updated["port"], 45678)
        self.assertEqual(devices.device_serial(updated), "192.168.10.22:45678")

    def test_update_device_allows_same_name_and_endpoint(self):
        device = devices.add_device(self.conn, "phone-01", "192.168.10.21", 5555)

        updated = devices.update_device(
            self.conn,
            device["id"],
            name="phone-01",
            ip="192.168.10.21",
            port=5555,
        )

        self.assertEqual(updated["id"], device["id"])
        self.assertEqual(updated["name"], "phone-01")

    def test_update_device_rejects_duplicate_name(self):
        first = devices.add_device(self.conn, "phone-01", "192.168.10.21", 5555)
        devices.add_device(self.conn, "phone-02", "192.168.10.22", 5555)

        with self.assertRaisesRegex(ValueError, "name already exists"):
            devices.update_device(self.conn, first["id"], name="phone-02")

    def test_update_device_rejects_duplicate_endpoint(self):
        first = devices.add_device(self.conn, "phone-01", "192.168.10.21", 5555)
        devices.add_device(self.conn, "phone-02", "192.168.10.22", 45678)

        with self.assertRaisesRegex(ValueError, "IP/port already exists"):
            devices.update_device(
                self.conn,
                first["id"],
                ip="192.168.10.22",
                port=45678,
            )

    def test_update_device_rejects_invalid_fields(self):
        device = devices.add_device(self.conn, "phone-01", "192.168.10.21", 5555)

        with self.assertRaisesRegex(ValueError, "device name is required"):
            devices.update_device(self.conn, device["id"], name="")

        with self.assertRaisesRegex(ValueError, "between 1 and 65535"):
            devices.update_device(self.conn, device["id"], port=70000)

    def test_update_device_rejects_active_lock(self):
        device = devices.add_device(self.conn, "phone-01", "192.168.10.21", 5555)
        devices.acquire_device_lease(self.conn, "phone-01", "worker-a", 600)

        with self.assertRaises(DeviceLockError):
            devices.update_device(self.conn, device["id"], ip="192.168.10.22")


if __name__ == "__main__":
    unittest.main()
