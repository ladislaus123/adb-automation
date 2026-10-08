import unittest
from unittest.mock import patch

from adb_automation import devices, recovery_queue, recovery_worker
from adb_automation.errors import AutomationError, OtpNotReceivedError
from adb_automation.notifications import (
    RECOVERY_EVENT_FAILED,
    RECOVERY_EVENT_RECOVERED,
    RECOVERY_EVENT_STARTED,
)
from adb_automation.whatsapp_recovery import (
    RECOVERY_SCREEN_CAN_REGISTER,
    RECOVERY_SCREEN_LOGGED_IN,
    RECOVERY_SCREEN_PERMANENT_BAN,
    RECOVERY_SCREEN_RESTRICTED,
    RECOVERY_SCREEN_REVIEW_PENDING,
)
from tests.fake_mariadb import FakeMariaDBConnection


class RecoveryWorkerTests(unittest.TestCase):
    def setUp(self):
        self.conn = FakeMariaDBConnection()
        self.device = devices.add_device(
            self.conn,
            "phone-01",
            "192.168.10.21",
            5555,
            whatsapp_phone="5547999990000",
        )

    def tearDown(self):
        self.conn.close()

    def enqueue(self, business=True):
        return recovery_queue.enqueue_recovery_job(
            self.conn,
            self.device,
            business=business,
            reason="restricted",
        )

    def run_once(
        self,
        request_screen=RECOVERY_SCREEN_REVIEW_PENDING,
        state_screen=RECOVERY_SCREEN_REVIEW_PENDING,
        relogin_result=RECOVERY_SCREEN_LOGGED_IN,
        ready_error=None,
        request_error=None,
        relogin_error=None,
    ):
        request = patch(
            "adb_automation.recovery_worker.request_account_review",
            side_effect=request_error or (lambda *args, **kwargs: request_screen),
        )
        state = patch(
            "adb_automation.recovery_worker.registration_state",
            return_value=state_screen,
        )
        relogin = patch(
            "adb_automation.recovery_worker.perform_relogin",
            side_effect=relogin_error or (lambda *args, **kwargs: relogin_result),
        )
        ready = patch(
            "adb_automation.recovery_worker.ensure_device_ready",
            side_effect=ready_error,
        )
        package = patch(
            "adb_automation.recovery_worker.get_whatsapp_package",
            return_value="com.whatsapp.w4b",
        )
        notify = patch("adb_automation.recovery_worker.notify_recovery_event")
        with patch("builtins.print"), ready as ready_mock, patch(
            "adb_automation.recovery_worker.wake_and_unlock_device"
        ), package as package_mock, request as request_mock, state as state_mock, relogin as relogin_mock, notify as notify_mock:
            processed = recovery_worker.run_recovery_once(self.conn, "recovery-1")
        return {
            "processed": processed,
            "notify": notify_mock,
            "request": request_mock,
            "state": state_mock,
            "relogin": relogin_mock,
            "ready": ready_mock,
            "package": package_mock,
        }

    def events(self, notify):
        return [call.kwargs["event"] for call in notify.call_args_list]

    def test_detected_job_submits_review_and_waits(self):
        job = self.enqueue()
        held = {}

        def request_review(*args, **kwargs):
            device = devices.get_device_by_id(self.conn, self.device["id"])
            held["locked"] = devices.lock_is_active(device)
            return RECOVERY_SCREEN_REVIEW_PENDING

        result = self.run_once(request_error=request_review)

        self.assertTrue(result["processed"])
        self.assertTrue(held["locked"])
        updated = recovery_queue.get_recovery_job(self.conn, job["id"])
        self.assertEqual(updated["status"], recovery_queue.RECOVERY_STATUS_REVIEW_PENDING)
        self.assertIsNotNone(updated["review_requested_at"])
        self.assertGreater(updated["next_attempt_at"], devices.now_iso())
        self.assertEqual(self.events(result["notify"]), [RECOVERY_EVENT_STARTED])
        self.assertEqual(result["package"].call_args.kwargs["business"], True)
        released = devices.get_device_by_id(self.conn, self.device["id"])
        self.assertIsNone(released["worker_id"])

        self.assertFalse(self.run_once()["processed"])

    def test_pending_job_moves_to_relogin_then_recovers(self):
        job = self.enqueue()
        self.run_once()
        recovery_queue.retry_recovery_job(self.conn, job["id"])

        pending = self.run_once(state_screen=RECOVERY_SCREEN_CAN_REGISTER)
        self.assertEqual(
            recovery_queue.get_recovery_job(self.conn, job["id"])["status"],
            recovery_queue.RECOVERY_STATUS_RELOGIN,
        )
        pending["relogin"].assert_not_called()

        finished = self.run_once(state_screen=RECOVERY_SCREEN_CAN_REGISTER)
        finished["relogin"].assert_called_once()
        self.assertEqual(
            finished["relogin"].call_args.args[2],
            "5547999990000",
        )
        self.assertEqual(
            recovery_queue.get_recovery_job(self.conn, job["id"])["status"],
            recovery_queue.RECOVERY_STATUS_RECOVERED,
        )
        self.assertIn(RECOVERY_EVENT_RECOVERED, self.events(finished["notify"]))

    def test_logged_in_screen_recovers_without_retyping_the_number(self):
        job = self.enqueue()
        result = self.run_once(request_screen=RECOVERY_SCREEN_LOGGED_IN)

        result["relogin"].assert_not_called()
        self.assertEqual(
            recovery_queue.get_recovery_job(self.conn, job["id"])["status"],
            recovery_queue.RECOVERY_STATUS_RECOVERED,
        )
        self.assertEqual(
            self.events(result["notify"]),
            [RECOVERY_EVENT_STARTED, RECOVERY_EVENT_RECOVERED],
        )

    def test_permanent_ban_fails_the_job(self):
        job = self.enqueue()
        result = self.run_once(request_screen=RECOVERY_SCREEN_PERMANENT_BAN)

        updated = recovery_queue.get_recovery_job(self.conn, job["id"])
        self.assertEqual(updated["status"], recovery_queue.RECOVERY_STATUS_FAILED)
        self.assertIn("permanently banned", updated["error"])
        self.assertEqual(
            self.events(result["notify"]),
            [RECOVERY_EVENT_STARTED, RECOVERY_EVENT_FAILED],
        )

    def test_device_not_ready_stays_detected_and_does_not_notify(self):
        job = self.enqueue()
        result = self.run_once(ready_error=AutomationError("device offline"))

        updated = recovery_queue.get_recovery_job(self.conn, job["id"])
        self.assertEqual(updated["status"], recovery_queue.RECOVERY_STATUS_DETECTED)
        self.assertEqual(updated["attempts"], 1)
        self.assertGreater(updated["next_attempt_at"], devices.now_iso())
        result["notify"].assert_not_called()
        result["request"].assert_not_called()

    def test_ui_errors_stop_at_max_attempts(self):
        job = self.enqueue()
        with patch(
            "adb_automation.recovery_worker.configured_max_attempts", return_value=1
        ):
            result = self.run_once(request_error=AutomationError("dump failed"))

        updated = recovery_queue.get_recovery_job(self.conn, job["id"])
        self.assertEqual(updated["status"], recovery_queue.RECOVERY_STATUS_FAILED)
        self.assertIn("max attempts", updated["error"])
        self.assertIn(RECOVERY_EVENT_FAILED, self.events(result["notify"]))

    def test_unconfirmed_review_retries_soon_instead_of_waiting_out_the_review(self):
        job = self.enqueue()
        self.run_once(request_screen=RECOVERY_SCREEN_RESTRICTED)

        updated = recovery_queue.get_recovery_job(self.conn, job["id"])
        self.assertEqual(updated["status"], recovery_queue.RECOVERY_STATUS_REQUESTING_REVIEW)
        self.assertEqual(updated["attempts"], 1)
        self.assertGreater(updated["next_attempt_at"], devices.now_iso())
        self.assertIsNone(updated["review_requested_at"])

    def test_restricted_screen_while_pending_asks_for_review_again(self):
        job = self.enqueue()
        self.run_once()
        recovery_queue.retry_recovery_job(self.conn, job["id"])
        self.run_once(state_screen=RECOVERY_SCREEN_RESTRICTED)

        updated = recovery_queue.get_recovery_job(self.conn, job["id"])
        self.assertEqual(updated["status"], recovery_queue.RECOVERY_STATUS_REQUESTING_REVIEW)
        self.assertLessEqual(updated["next_attempt_at"], devices.now_iso())

    def test_relogin_uses_a_number_saved_after_the_job_was_opened(self):
        devices.update_device(self.conn, self.device["id"], whatsapp_phone="")
        job = recovery_queue.enqueue_recovery_job(
            self.conn, self.device, business=False, phone=None, reason="logout"
        )
        self.assertIsNone(job["phone"])
        devices.update_device(self.conn, self.device["id"], whatsapp_phone="5547111111111")
        recovery_queue.mark_relogin(self.conn, job["id"])

        result = self.run_once(state_screen=RECOVERY_SCREEN_CAN_REGISTER)
        self.assertEqual(result["relogin"].call_args.args[2], "5547111111111")

    def test_otp_failure_reschedules_relogin(self):
        job = self.enqueue()
        recovery_queue.mark_relogin(self.conn, job["id"])
        self.run_once(
            state_screen=RECOVERY_SCREEN_CAN_REGISTER,
            relogin_error=OtpNotReceivedError("no code"),
        )

        updated = recovery_queue.get_recovery_job(self.conn, job["id"])
        self.assertEqual(updated["status"], recovery_queue.RECOVERY_STATUS_RELOGIN)
        self.assertEqual(updated["attempts"], 1)
        self.assertIn("no code", updated["error"])
        self.assertGreater(updated["next_attempt_at"], devices.now_iso())


if __name__ == "__main__":
    unittest.main()
