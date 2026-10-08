import unittest
from datetime import timedelta

from adb_automation import devices, recovery_queue
from tests.fake_mariadb import FakeMariaDBConnection


class RecoveryQueueTests(unittest.TestCase):
    def setUp(self):
        self.conn = FakeMariaDBConnection()
        self.device = devices.add_device(
            self.conn,
            "phone-01",
            "192.168.10.21",
            5555,
            whatsapp_phone="+55 47 99999-0000",
        )

    def tearDown(self):
        self.conn.close()

    def enqueue(self, device=None, phone=None, business=False, reason="restricted"):
        return recovery_queue.enqueue_recovery_job(
            self.conn,
            device or self.device,
            business=business,
            phone=phone,
            reason=reason,
        )

    def test_enqueue_is_idempotent_and_normalizes_the_phone(self):
        first = self.enqueue(phone="+55 (47) 98888-0000", business=True, reason="ban")
        second = self.enqueue(reason="again")

        self.assertEqual(first["status"], recovery_queue.RECOVERY_STATUS_DETECTED)
        self.assertEqual(first["phone"], "5547988880000")
        self.assertEqual(first["business"], 1)
        self.assertEqual(first["device_label"], "phone-01")
        self.assertEqual(first["reason"], "ban")
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(len(self.conn.recovery_jobs), 1)
        self.assertEqual(
            recovery_queue.list_recovery_jobs(self.conn, status="detected")[0]["id"],
            first["id"],
        )

    def test_enqueue_falls_back_to_the_device_number(self):
        job = self.enqueue()
        self.assertEqual(job["phone"], "5547999990000")

    def test_enqueue_rejects_a_phone_with_no_digits(self):
        with self.assertRaisesRegex(ValueError, "phone number is required"):
            self.enqueue(phone="not-a-number")
        self.assertEqual(self.conn.recovery_jobs, [])

    def test_claim_leases_the_device_and_skips_a_locked_one(self):
        job = self.enqueue()
        devices.acquire_device_lease(self.conn, "phone-01", "send-worker", 600)
        self.assertIsNone(recovery_queue.claim_next_recovery_job(self.conn, "recovery-1"))

        devices.release_device_lease(
            self.conn,
            self.device["id"],
            "send-worker",
            devices.get_device_by_id(self.conn, self.device["id"])["locked_until"],
        )
        second = devices.add_device(self.conn, "phone-02", "192.168.10.22", 5555)
        other = self.enqueue(device=second)
        # phone-01 is free again, and it was enqueued first, so it is claimed.
        claimed = recovery_queue.claim_next_recovery_job(self.conn, "recovery-1")

        self.assertEqual(claimed["id"], job["id"])
        self.assertEqual(claimed["worker_id"], "recovery-1")
        self.assertIsNotNone(claimed["started_at"])
        self.assertEqual(claimed["device"]["id"], self.device["id"])
        leased = devices.get_device_by_id(self.conn, self.device["id"])
        self.assertEqual(leased["worker_id"], "recovery-1")
        self.assertEqual(leased["locked_until"], claimed["device_locked_until"])
        self.assertEqual(other["status"], recovery_queue.RECOVERY_STATUS_DETECTED)

        devices.release_device_lease(
            self.conn,
            self.device["id"],
            claimed["worker_id"],
            claimed["device_locked_until"],
        )
        # Claim does not change status. A released, still-due job is claimable
        # again, so park the first one before expecting the second device.
        future = devices.to_iso(devices.utcnow() + timedelta(hours=2))
        recovery_queue.mark_review_pending(self.conn, job["id"], future)
        nxt = recovery_queue.claim_next_recovery_job(self.conn, "recovery-2")
        self.assertEqual(nxt["id"], other["id"])

    def test_claim_fails_a_job_whose_device_was_removed(self):
        job = self.enqueue()
        self.conn.devices.clear()

        self.assertIsNone(recovery_queue.claim_next_recovery_job(self.conn, "recovery-1"))

        failed = recovery_queue.get_recovery_job(self.conn, job["id"])
        self.assertEqual(failed["status"], recovery_queue.RECOVERY_STATUS_FAILED)
        self.assertIn("device not found", failed["error"])

    def test_review_backoff_hides_the_job_until_retry(self):
        job = self.enqueue()
        future = devices.to_iso(devices.utcnow() + timedelta(hours=2))
        pending = recovery_queue.mark_review_pending(self.conn, job["id"], future)

        self.assertEqual(pending["status"], recovery_queue.RECOVERY_STATUS_REVIEW_PENDING)
        self.assertEqual(pending["next_attempt_at"], future)
        self.assertIsNotNone(pending["review_requested_at"])
        self.assertIsNone(recovery_queue.claim_next_recovery_job(self.conn, "recovery-1"))

        retried = recovery_queue.retry_recovery_job(self.conn, job["id"])
        self.assertLessEqual(retried["next_attempt_at"], devices.now_iso())
        claimed = recovery_queue.claim_next_recovery_job(self.conn, "recovery-1")
        self.assertEqual(claimed["id"], job["id"])

    def test_status_transitions_and_terminal_jobs_are_not_claimed(self):
        job = self.enqueue()
        recovery_queue.mark_requesting_review(self.conn, job["id"])
        recovery_queue.mark_relogin(self.conn, job["id"])
        recovered = recovery_queue.mark_recovered(self.conn, job["id"])

        self.assertEqual(recovered["status"], recovery_queue.RECOVERY_STATUS_RECOVERED)
        self.assertIsNotNone(recovered["recovered_at"])
        self.assertIsNotNone(recovered["finished_at"])
        self.assertIsNone(recovery_queue.claim_next_recovery_job(self.conn, "recovery-1"))

        other_device = devices.add_device(self.conn, "phone-02", "192.168.10.22", 5555)
        other = self.enqueue(device=other_device)
        failed = recovery_queue.fail_recovery_job(self.conn, other["id"], "permanent ban")
        self.assertEqual(failed["status"], recovery_queue.RECOVERY_STATUS_FAILED)
        self.assertEqual(failed["error"], "permanent ban")
        with self.assertRaisesRegex(ValueError, "only active jobs"):
            recovery_queue.retry_recovery_job(self.conn, other["id"])

    def test_cancel_is_not_overwritten_by_a_later_transition(self):
        job = self.enqueue()
        cancelled = recovery_queue.cancel_recovery_job(self.conn, job["id"])
        self.assertEqual(cancelled["status"], recovery_queue.RECOVERY_STATUS_CANCELLED)

        still = recovery_queue.mark_recovered(self.conn, job["id"])
        self.assertEqual(still["status"], recovery_queue.RECOVERY_STATUS_CANCELLED)
        self.assertIsNone(still["recovered_at"])

    def test_bump_attempt_schedules_a_backoff(self):
        job = self.enqueue()
        updated = recovery_queue.bump_attempt_and_reschedule(
            self.conn,
            job["id"],
            recovery_queue.RECOVERY_STATUS_RELOGIN,
            60,
            error="otp timeout",
        )

        self.assertEqual(updated["status"], recovery_queue.RECOVERY_STATUS_RELOGIN)
        self.assertEqual(updated["attempts"], 1)
        self.assertEqual(updated["error"], "otp timeout")
        self.assertGreater(updated["next_attempt_at"], devices.now_iso())
        self.assertIsNone(recovery_queue.claim_next_recovery_job(self.conn, "recovery-1"))


if __name__ == "__main__":
    unittest.main()
