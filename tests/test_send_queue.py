import unittest

from adb_automation import devices, send_queue
from tests.fake_mariadb import FakeMariaDBConnection


class SendQueueTests(unittest.TestCase):
    def setUp(self):
        self.conn = FakeMariaDBConnection()
        self.device = devices.add_device(
            self.conn,
            "phone-01",
            "192.168.10.21",
            5555,
        )

    def tearDown(self):
        self.conn.close()

    def enqueue(self, device=None, endpoint="/api/sendText", text="hello"):
        return send_queue.enqueue_send_job(
            self.conn,
            endpoint,
            device or self.device,
            "phone-01",
            "5511999999999",
            text,
            None,
            False,
            "api-worker",
            600,
        )

    def test_enqueue_get_and_list_jobs(self):
        job = self.enqueue()

        self.assertEqual(job["status"], send_queue.JOB_STATUS_PENDING)
        self.assertEqual(job["endpoint"], "/api/sendText")
        self.assertEqual(job["device_id"], self.device["id"])
        self.assertEqual(job["phone"], "5511999999999")

        self.assertEqual(send_queue.get_send_job(self.conn, job["id"])["id"], job["id"])
        self.assertEqual(send_queue.list_send_jobs(self.conn)[0]["id"], job["id"])
        self.assertEqual(
            send_queue.list_send_jobs(
                self.conn,
                status=send_queue.JOB_STATUS_PENDING,
            )[0]["id"],
            job["id"],
        )

    def test_claim_next_job_marks_running_and_leases_device(self):
        job = self.enqueue()

        claimed = send_queue.claim_next_send_job(self.conn, "queue-worker-1")

        self.assertEqual(claimed["id"], job["id"])
        self.assertEqual(claimed["status"], send_queue.JOB_STATUS_RUNNING)
        self.assertEqual(claimed["queue_worker_id"], "queue-worker-1")
        self.assertIsNotNone(claimed["device_locked_until"])
        self.assertEqual(claimed["device"]["id"], self.device["id"])

        leased = devices.find_device(self.conn, "phone-01")
        self.assertEqual(leased["worker_id"], "queue-worker-1")
        self.assertEqual(leased["locked_until"], claimed["device_locked_until"])

    def test_claim_skips_locked_device_and_claims_next_available_job(self):
        devices.acquire_device_lease(self.conn, "phone-01", "manual-worker", 600)
        locked_job = self.enqueue()
        second_device = devices.add_device(
            self.conn,
            "phone-02",
            "192.168.10.22",
            5555,
        )
        available_job = self.enqueue(device=second_device)

        claimed = send_queue.claim_next_send_job(self.conn, "queue-worker-1")

        self.assertEqual(claimed["id"], available_job["id"])
        self.assertEqual(
            send_queue.get_send_job(self.conn, locked_job["id"])["status"],
            send_queue.JOB_STATUS_PENDING,
        )

    def test_running_job_is_not_claimed_twice(self):
        self.enqueue()
        first = send_queue.claim_next_send_job(self.conn, "queue-worker-1")
        second = send_queue.claim_next_send_job(self.conn, "queue-worker-2")

        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_complete_and_fail_update_running_jobs(self):
        first = self.enqueue()
        second_device = devices.add_device(
            self.conn,
            "phone-02",
            "192.168.10.22",
            5555,
        )
        second = self.enqueue(device=second_device)

        claimed_first = send_queue.claim_next_send_job(self.conn, "queue-worker-1")
        devices.release_device_lease(
            self.conn,
            self.device["id"],
            claimed_first["queue_worker_id"],
            claimed_first["device_locked_until"],
        )
        claimed_second = send_queue.claim_next_send_job(self.conn, "queue-worker-2")

        completed = send_queue.complete_send_job(self.conn, first["id"])
        failed = send_queue.fail_send_job(self.conn, second["id"], "boom")

        self.assertEqual(completed["status"], send_queue.JOB_STATUS_SUCCEEDED)
        self.assertIsNotNone(completed["finished_at"])
        self.assertEqual(failed["status"], send_queue.JOB_STATUS_FAILED)
        self.assertEqual(failed["error"], "boom")
        self.assertIsNotNone(claimed_second)


if __name__ == "__main__":
    unittest.main()
