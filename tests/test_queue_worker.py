import os
import tempfile
import unittest
from unittest.mock import patch

from adb_automation import devices, downloaded_media, queue_worker, send_queue
from adb_automation.errors import (
    AdbError,
    AutomationError,
    WhatsAppLoggedOutError,
    WhatsAppRestrictedError,
)
from tests.fake_mariadb import FakeMariaDBConnection


class QueueWorkerTests(unittest.TestCase):
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

    def enqueue(self, endpoint="/api/sendText", file_path=None, text="hello"):
        return send_queue.enqueue_send_job(
            self.conn,
            endpoint,
            self.device,
            "phone-01",
            "5511999999999",
            text,
            file_path,
            True,
            "api-worker",
            600,
        )

    def test_run_queue_once_sends_job_and_releases_device(self):
        job = self.enqueue()

        with patch("builtins.print"), patch(
            "adb_automation.queue_worker.ensure_device_ready"
        ) as ensure_device_ready, patch(
            "adb_automation.queue_worker.wake_and_unlock_device"
        ) as wake_and_unlock_device, patch(
            "adb_automation.queue_worker.mark_device_seen"
        ) as mark_device_seen, patch(
            "adb_automation.queue_worker.send_whatsapp"
        ) as send_whatsapp:
            processed = queue_worker.run_queue_once(self.conn, "queue-worker-1")

        self.assertTrue(processed)
        ensure_device_ready.assert_called_once_with(
            "192.168.10.21:5555",
            adb_transport=devices.ADB_TRANSPORT_WIFI,
        )
        wake_and_unlock_device.assert_called_once_with("192.168.10.21:5555")
        mark_device_seen.assert_called_once_with(self.conn, self.device["id"])
        send_whatsapp.assert_called_once_with(
            "192.168.10.21:5555",
            "5511999999999",
            text="hello",
            file_path=None,
            business=True,
            known_contact=False,
            adb_transport=devices.ADB_TRANSPORT_WIFI,
        )
        self.assertEqual(
            send_queue.get_send_job(self.conn, job["id"])["status"],
            send_queue.JOB_STATUS_SUCCEEDED,
        )
        released = devices.find_device(self.conn, "phone-01")
        self.assertIsNone(released["worker_id"])
        self.assertIsNone(released["locked_until"])

    def test_restricted_error_notifies_session_restricted(self):
        devices.update_device(
            self.conn, self.device["id"], whatsapp_phone="+55 47 99999-0000"
        )
        job = self.enqueue()
        restricted = WhatsAppRestrictedError("WhatsApp is restricted.")

        with patch("builtins.print"), patch(
            "adb_automation.queue_worker.ensure_device_ready"
        ), patch("adb_automation.queue_worker.wake_and_unlock_device"), patch(
            "adb_automation.queue_worker.mark_device_seen"
        ), patch(
            "adb_automation.queue_worker.send_whatsapp", side_effect=restricted
        ), patch(
            "adb_automation.queue_worker.notify_session_restricted"
        ) as notify:
            queue_worker.run_queue_once(self.conn, "queue-worker-1")

        self.assertEqual(
            send_queue.get_send_job(self.conn, job["id"])["status"],
            send_queue.JOB_STATUS_FAILED,
        )
        notify.assert_called_once()
        called_job, called_exc = notify.call_args.args
        self.assertEqual(called_job["id"], job["id"])
        self.assertIs(called_exc, restricted)
        self.assertEqual(len(self.conn.recovery_jobs), 1)
        self.assertEqual(self.conn.recovery_jobs[0]["device_id"], self.device["id"])
        self.assertEqual(self.conn.recovery_jobs[0]["status"], "detected")
        self.assertEqual(self.conn.recovery_jobs[0]["phone"], "5547999990000")
        self.assertEqual(self.conn.recovery_jobs[0]["business"], 1)

        self.enqueue()
        with patch("builtins.print"), patch(
            "adb_automation.queue_worker.ensure_device_ready"
        ), patch("adb_automation.queue_worker.wake_and_unlock_device"), patch(
            "adb_automation.queue_worker.mark_device_seen"
        ), patch(
            "adb_automation.queue_worker.send_whatsapp", side_effect=restricted
        ), patch("adb_automation.queue_worker.notify_session_restricted"):
            queue_worker.run_queue_once(self.conn, "queue-worker-1")

        self.assertEqual(len(self.conn.recovery_jobs), 1)

    def test_non_restricted_error_does_not_notify_session_restricted(self):
        self.enqueue()

        with patch("builtins.print"), patch(
            "adb_automation.queue_worker.ensure_device_ready"
        ), patch("adb_automation.queue_worker.wake_and_unlock_device"), patch(
            "adb_automation.queue_worker.mark_device_seen"
        ), patch(
            "adb_automation.queue_worker.send_whatsapp",
            side_effect=AutomationError("some other failure"),
        ), patch(
            "adb_automation.queue_worker.notify_session_restricted"
        ) as notify, patch(
            "adb_automation.queue_worker.notify_session_disconnected"
        ) as notify_disc:
            queue_worker.run_queue_once(self.conn, "queue-worker-1")

        notify.assert_not_called()
        notify_disc.assert_not_called()
        self.assertEqual(self.conn.recovery_jobs, [])

    def test_logged_out_error_notifies_session_disconnected(self):
        job = self.enqueue()
        logged_out = WhatsAppLoggedOutError("WhatsApp session is logged out.")

        with patch("builtins.print"), patch(
            "adb_automation.queue_worker.ensure_device_ready"
        ), patch("adb_automation.queue_worker.wake_and_unlock_device"), patch(
            "adb_automation.queue_worker.mark_device_seen"
        ), patch(
            "adb_automation.queue_worker.send_whatsapp", side_effect=logged_out
        ), patch(
            "adb_automation.queue_worker.notify_session_restricted"
        ) as notify_restricted, patch(
            "adb_automation.queue_worker.notify_session_disconnected"
        ) as notify_disc:
            queue_worker.run_queue_once(self.conn, "queue-worker-1")

        self.assertEqual(
            send_queue.get_send_job(self.conn, job["id"])["status"],
            send_queue.JOB_STATUS_FAILED,
        )
        notify_restricted.assert_not_called()
        notify_disc.assert_called_once()
        called_job, called_exc = notify_disc.call_args.args
        self.assertEqual(called_job["id"], job["id"])
        self.assertIs(called_exc, logged_out)
        self.assertEqual(
            notify_disc.call_args.kwargs.get("event"), "session_disconnected"
        )
        self.assertEqual(len(self.conn.recovery_jobs), 1)
        self.assertEqual(self.conn.recovery_jobs[0]["status"], "detected")
        self.assertIn("logged out", self.conn.recovery_jobs[0]["reason"])

    def test_device_offline_error_notifies_device_offline(self):
        self.enqueue()
        offline = AdbError("device R9 is not visible in adb devices.")

        with patch("builtins.print"), patch(
            "adb_automation.queue_worker.ensure_device_ready"
        ), patch("adb_automation.queue_worker.wake_and_unlock_device"), patch(
            "adb_automation.queue_worker.mark_device_seen"
        ), patch(
            "adb_automation.queue_worker.send_whatsapp", side_effect=offline
        ), patch(
            "adb_automation.queue_worker.notify_session_disconnected"
        ) as notify_disc:
            queue_worker.run_queue_once(self.conn, "queue-worker-1")

        notify_disc.assert_called_once()
        self.assertEqual(
            notify_disc.call_args.kwargs.get("event"), "device_offline"
        )
        self.assertEqual(self.conn.recovery_jobs, [])

    def test_unrelated_adb_error_does_not_notify(self):
        self.enqueue()
        other = AdbError("adb shell command failed with exit code 1")

        with patch("builtins.print"), patch(
            "adb_automation.queue_worker.ensure_device_ready"
        ), patch("adb_automation.queue_worker.wake_and_unlock_device"), patch(
            "adb_automation.queue_worker.mark_device_seen"
        ), patch(
            "adb_automation.queue_worker.send_whatsapp", side_effect=other
        ), patch(
            "adb_automation.queue_worker.notify_session_disconnected"
        ) as notify_disc:
            queue_worker.run_queue_once(self.conn, "queue-worker-1")

        notify_disc.assert_not_called()

    def test_run_queue_once_uses_usb_transport_for_usb_device(self):
        usb_device = devices.add_device(
            self.conn,
            "phone-usb",
            adb_transport=devices.ADB_TRANSPORT_USB,
            usb_serial="R5CW123ABC",
        )
        job = send_queue.enqueue_send_job(
            self.conn,
            "/api/sendText",
            usb_device,
            "phone-usb",
            "5511999999999",
            "hello",
            None,
            False,
            "api-worker",
            600,
        )

        with patch("builtins.print"), patch(
            "adb_automation.queue_worker.ensure_device_ready"
        ) as ensure_device_ready, patch(
            "adb_automation.queue_worker.wake_and_unlock_device"
        ), patch("adb_automation.queue_worker.mark_device_seen"), patch(
            "adb_automation.queue_worker.send_whatsapp"
        ) as send_whatsapp:
            processed = queue_worker.run_queue_once(self.conn, "queue-worker-1")

        self.assertTrue(processed)
        ensure_device_ready.assert_called_once_with(
            "R5CW123ABC",
            adb_transport=devices.ADB_TRANSPORT_USB,
        )
        send_whatsapp.assert_called_once_with(
            "R5CW123ABC",
            "5511999999999",
            text="hello",
            file_path=None,
            business=False,
            known_contact=False,
            adb_transport=devices.ADB_TRANSPORT_USB,
        )
        self.assertEqual(
            send_queue.get_send_job(self.conn, job["id"])["status"],
            send_queue.JOB_STATUS_SUCCEEDED,
        )

    def test_voice_job_passes_original_audio_through_media_route(self):
        with tempfile.NamedTemporaryFile(suffix=".mp3") as media_file:
            self.enqueue(
                endpoint="/api/sendVoice",
                file_path=media_file.name,
                text="caption",
            )

            with patch("builtins.print"), patch(
                "adb_automation.queue_worker.ensure_device_ready"
            ), patch(
                "adb_automation.queue_worker.wake_and_unlock_device"
            ), patch("adb_automation.queue_worker.mark_device_seen"), patch(
                "adb_automation.queue_worker.send_whatsapp"
            ) as send_whatsapp:
                queue_worker.run_queue_once(self.conn, "queue-worker-1")

        send_whatsapp.assert_called_once_with(
            "192.168.10.21:5555",
            "5511999999999",
            text="caption",
            file_path=media_file.name,
            business=True,
            known_contact=False,
            adb_transport=devices.ADB_TRANSPORT_WIFI,
        )

    def test_worker_cleans_downloaded_media_file_after_success(self):
        downloaded = tempfile.NamedTemporaryFile(
            delete=False,
            prefix=downloaded_media.URL_MEDIA_TEMP_PREFIX,
            suffix=".jpg",
        )
        downloaded_path = downloaded.name
        downloaded.close()
        self.enqueue(endpoint="/api/sendImage", file_path=downloaded_path)

        with patch("builtins.print"), patch(
            "adb_automation.queue_worker.ensure_device_ready"
        ), patch(
            "adb_automation.queue_worker.wake_and_unlock_device"
        ), patch("adb_automation.queue_worker.mark_device_seen"), patch(
            "adb_automation.queue_worker.send_whatsapp"
        ):
            queue_worker.run_queue_once(self.conn, "queue-worker-1")

        self.assertFalse(os.path.exists(downloaded_path))

    def test_worker_keeps_regular_media_file_after_success(self):
        media_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        media_path = media_file.name
        media_file.close()
        self.enqueue(endpoint="/api/sendImage", file_path=media_path)

        try:
            with patch("builtins.print"), patch(
                "adb_automation.queue_worker.ensure_device_ready"
            ), patch(
                "adb_automation.queue_worker.wake_and_unlock_device"
            ), patch("adb_automation.queue_worker.mark_device_seen"), patch(
                "adb_automation.queue_worker.send_whatsapp"
            ):
                queue_worker.run_queue_once(self.conn, "queue-worker-1")

            self.assertTrue(os.path.exists(media_path))
        finally:
            if os.path.exists(media_path):
                os.remove(media_path)

    def test_worker_records_failure_and_releases_device(self):
        job = self.enqueue()

        with patch("builtins.print"), patch(
            "adb_automation.queue_worker.ensure_device_ready"
        ), patch(
            "adb_automation.queue_worker.wake_and_unlock_device"
        ), patch("adb_automation.queue_worker.mark_device_seen"), patch(
            "adb_automation.queue_worker.send_whatsapp",
            side_effect=AutomationError("adb failed"),
        ):
            processed = queue_worker.run_queue_once(self.conn, "queue-worker-1")

        self.assertTrue(processed)
        failed = send_queue.get_send_job(self.conn, job["id"])
        self.assertEqual(failed["status"], send_queue.JOB_STATUS_FAILED)
        self.assertIn("adb failed", failed["error"])
        released = devices.find_device(self.conn, "phone-01")
        self.assertIsNone(released["worker_id"])
        self.assertIsNone(released["locked_until"])

    def test_run_queue_once_returns_false_when_no_job_available(self):
        processed = queue_worker.run_queue_once(self.conn, "queue-worker-1")

        self.assertFalse(processed)

    def test_worker_runs_stochastic_job_and_releases_device(self):
        job = send_queue.enqueue_stochastic_job(
            self.conn,
            self.device,
            "phone-01",
            "api-worker",
            600,
        )

        with patch("builtins.print"), patch(
            "adb_automation.queue_worker.ensure_device_ready"
        ) as ensure_device_ready, patch(
            "adb_automation.queue_worker.wake_and_unlock_device"
        ) as wake_and_unlock_device, patch(
            "adb_automation.queue_worker.mark_device_seen"
        ) as mark_device_seen, patch(
            "adb_automation.queue_worker.run_stochastic_actions"
        ) as run_stochastic_actions, patch(
            "adb_automation.queue_worker.send_whatsapp"
        ) as send_whatsapp:
            processed = queue_worker.run_queue_once(self.conn, "queue-worker-1")

        self.assertTrue(processed)
        ensure_device_ready.assert_called_once_with(
            "192.168.10.21:5555",
            adb_transport=devices.ADB_TRANSPORT_WIFI,
        )
        wake_and_unlock_device.assert_called_once_with("192.168.10.21:5555")
        mark_device_seen.assert_called_once_with(self.conn, self.device["id"])
        run_stochastic_actions.assert_called_once_with("192.168.10.21:5555")
        send_whatsapp.assert_not_called()
        self.assertEqual(
            send_queue.get_send_job(self.conn, job["id"])["status"],
            send_queue.JOB_STATUS_SUCCEEDED,
        )
        released = devices.find_device(self.conn, "phone-01")
        self.assertIsNone(released["worker_id"])
        self.assertIsNone(released["locked_until"])

    def test_configured_worker_count_caps_to_cpu_count(self):
        with patch("adb_automation.queue_worker.os.cpu_count", return_value=4), patch.dict(
            "os.environ",
            {"ADB_AUTOMATION_QUEUE_WORKERS": "99"},
        ):
            self.assertEqual(queue_worker.configured_worker_count(), 4)


if __name__ == "__main__":
    unittest.main()
