import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from adb_automation import devices, downloaded_media, send_queue
from adb_automation.api import create_app
from adb_automation.errors import AutomationError
from tests.fake_mariadb import FakeMariaDBConnection


class ApiRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(start_queue_workers=False)
        self.client = self.app.test_client()
        self.api_key = "test-api-key"

    def auth_headers(self):
        return {"X-API-Key": self.api_key}

    def post_json(self, endpoint, payload, headers=None):
        return self.client.post(endpoint, json=payload, headers=headers or {})

    def test_index_serves_frontend(self):
        response = self.client.get("/")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Device Console", response.data)
        finally:
            response.close()

    def test_auth_is_required(self):
        response = self.post_json(
            "/api/sendText",
            {"device": "mdv", "phone": "256740932270", "text": "hello"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["success"])

    def test_invalid_api_key_is_rejected(self):
        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}):
            response = self.post_json(
                "/api/sendText",
                {"device": "mdv", "phone": "256740932270", "text": "hello"},
                headers={"X-API-Key": "wrong"},
            )

        self.assertEqual(response.status_code, 401)

    def test_send_text_requires_text(self):
        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}):
            response = self.post_json(
                "/api/sendText",
                {"device": "mdv", "phone": "256740932270"},
                headers=self.auth_headers(),
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("text is required", response.get_json()["error"])

    def test_media_routes_require_file(self):
        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}):
            for endpoint in ("/api/sendImage", "/api/sendVoice", "/api/sendVideo"):
                with self.subTest(endpoint=endpoint):
                    response = self.post_json(
                        endpoint,
                        {"device": "mdv", "phone": "256740932270"},
                        headers=self.auth_headers(),
                    )

                    self.assertEqual(response.status_code, 400)
                    self.assertIn("file or file_path", response.get_json()["error"])

    def test_send_text_enqueues_job(self):
        conn = FakeMariaDBConnection()
        devices.add_device(conn, "mdv", "192.168.10.21", 5555)

        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}), patch(
            "adb_automation.api.open_database", return_value=conn
        ), patch("adb_automation.api.init_database"), patch(
            "adb_automation.api.start_queue_workers"
        ):
            response = self.post_json(
                "/api/sendText",
                {
                    "device": "mdv",
                    "phone": "256740932270",
                    "text": "hello",
                    "business": True,
                    "worker_id": "api-worker-1",
                    "lease_seconds": 30,
                },
                headers=self.auth_headers(),
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 202)
        self.assertTrue(payload["queued"])
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(conn.send_jobs[0]["endpoint"], "/api/sendText")
        self.assertEqual(conn.send_jobs[0]["phone"], "256740932270")
        self.assertEqual(conn.send_jobs[0]["text"], "hello")
        self.assertEqual(conn.send_jobs[0]["business"], 1)
        self.assertTrue(conn.closed)

    def test_image_and_video_routes_enqueue_file_path(self):
        conn = FakeMariaDBConnection()
        devices.add_device(conn, "mdv", "192.168.10.21", 5555)

        with tempfile.NamedTemporaryFile() as media_file:
            with patch.dict(
                os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}
            ), patch("adb_automation.api.open_database", return_value=conn), patch(
                "adb_automation.api.init_database"
            ):
                for endpoint in ("/api/sendImage", "/api/sendVideo"):
                    with self.subTest(endpoint=endpoint):
                        response = self.post_json(
                            endpoint,
                            {
                                "device": "mdv",
                                "phone": "256740932270",
                                "file_path": media_file.name,
                                "text": "caption",
                                "worker_id": "api-worker-1",
                                "lease_seconds": 30,
                            },
                            headers=self.auth_headers(),
                        )

                        self.assertEqual(response.status_code, 202)
                        self.assertEqual(conn.send_jobs[-1]["endpoint"], endpoint)
                        self.assertEqual(conn.send_jobs[-1]["file_path"], media_file.name)
                        self.assertEqual(conn.send_jobs[-1]["text"], "caption")

        self.assertTrue(conn.closed)

    def test_send_voice_enqueues_original_audio_without_conversion(self):
        conn = FakeMariaDBConnection()
        devices.add_device(conn, "mdv", "192.168.10.21", 5555)

        with tempfile.NamedTemporaryFile(suffix=".mp3") as media_file:
            with patch.dict(
                os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}
            ), patch("adb_automation.api.open_database", return_value=conn), patch(
                "adb_automation.api.init_database"
            ):
                response = self.post_json(
                    "/api/sendVoice",
                    {
                        "device": "mdv",
                        "phone": "256740932270",
                        "file_path": media_file.name,
                        "text": "caption",
                        "worker_id": "api-worker-1",
                        "lease_seconds": 30,
                    },
                    headers=self.auth_headers(),
                )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(conn.send_jobs[0]["endpoint"], "/api/sendVoice")
        self.assertEqual(conn.send_jobs[0]["file_path"], media_file.name)

    def test_file_alias_is_accepted_for_media_routes(self):
        conn = FakeMariaDBConnection()
        devices.add_device(conn, "mdv", "192.168.10.21", 5555)

        with tempfile.NamedTemporaryFile() as media_file:
            with patch.dict(
                os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}
            ), patch("adb_automation.api.open_database", return_value=conn), patch(
                "adb_automation.api.init_database"
            ):
                response = self.post_json(
                    "/api/sendImage",
                    {
                        "device": "mdv",
                        "phone": "256740932270",
                        "file": media_file.name,
                        "worker_id": "api-worker-1",
                    },
                    headers=self.auth_headers(),
                )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(conn.send_jobs[0]["file_path"], media_file.name)

    def test_file_url_object_is_downloaded_and_enqueued(self):
        conn = FakeMariaDBConnection()
        devices.add_device(conn, "mdv", "192.168.10.21", 5555)
        downloaded = tempfile.NamedTemporaryFile(
            delete=False,
            prefix=downloaded_media.URL_MEDIA_TEMP_PREFIX,
            suffix=".jpg",
        )
        downloaded_path = downloaded.name
        downloaded.close()

        try:
            with patch.dict(
                os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}
            ), patch("adb_automation.api.open_database", return_value=conn), patch(
                "adb_automation.api.init_database"
            ), patch(
                "adb_automation.api.download_media_url_to_temp",
                return_value=downloaded_path,
            ) as download:
                response = self.post_json(
                    "/api/sendImage",
                    {
                        "device": "mdv",
                        "phone": "256740932270",
                        "file": {
                            "url": "https://cdn.example.test/media/cat",
                            "filename": "cat.jpg",
                        },
                        "caption": "caption from waha-style payload",
                        "worker_id": "api-worker-1",
                    },
                    headers=self.auth_headers(),
                )

            self.assertEqual(response.status_code, 202)
            download.assert_called_once_with(
                "https://cdn.example.test/media/cat",
                filename="cat.jpg",
            )
            self.assertEqual(conn.send_jobs[0]["file_path"], downloaded_path)
            self.assertEqual(
                conn.send_jobs[0]["text"],
                "caption from waha-style payload",
            )
            self.assertTrue(os.path.exists(downloaded_path))
        finally:
            downloaded_media.cleanup_downloaded_media_file(downloaded_path)

    def test_file_url_download_is_cleaned_up_when_enqueue_fails(self):
        conn = FakeMariaDBConnection()
        devices.add_device(conn, "mdv", "192.168.10.21", 5555)
        downloaded = tempfile.NamedTemporaryFile(
            delete=False,
            prefix=downloaded_media.URL_MEDIA_TEMP_PREFIX,
            suffix=".jpg",
        )
        downloaded_path = downloaded.name
        downloaded.close()

        with patch.dict(
            os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}
        ), patch("adb_automation.api.open_database", return_value=conn), patch(
            "adb_automation.api.init_database"
        ), patch(
            "adb_automation.api.download_media_url_to_temp",
            return_value=downloaded_path,
        ), patch(
            "adb_automation.api.enqueue_send_job",
            side_effect=AutomationError("queue failed"),
        ):
            response = self.post_json(
                "/api/sendImage",
                {
                    "device": "mdv",
                    "phone": "256740932270",
                    "file": {"url": "https://cdn.example.test/media/cat.jpg"},
                },
                headers=self.auth_headers(),
            )

        self.assertEqual(response.status_code, 500)
        self.assertFalse(os.path.exists(downloaded_path))

    def test_file_object_requires_url(self):
        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}):
            response = self.post_json(
                "/api/sendImage",
                {
                    "device": "mdv",
                    "phone": "256740932270",
                    "file": {"filename": "cat.jpg"},
                },
                headers=self.auth_headers(),
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("file.url", response.get_json()["error"])

    def test_send_route_unknown_device_returns_bad_request(self):
        conn = FakeMariaDBConnection()
        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}), patch(
            "adb_automation.api.open_database", return_value=conn
        ), patch("adb_automation.api.init_database"), patch(
            "adb_automation.api.start_queue_workers"
        ):
            response = self.post_json(
                "/api/sendText",
                {"device": "mdv", "phone": "256740932270", "text": "hello"},
                headers=self.auth_headers(),
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("device not found", response.get_json()["error"])

    def test_send_error_returns_server_error(self):
        conn = FakeMariaDBConnection()
        devices.add_device(conn, "mdv", "192.168.10.21", 5555)

        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}), patch(
            "adb_automation.api.open_database", return_value=conn
        ), patch("adb_automation.api.init_database"), patch(
            "adb_automation.api.enqueue_send_job",
            side_effect=AutomationError("adb failed"),
        ):
            response = self.post_json(
                "/api/sendText",
                {"device": "mdv", "phone": "256740932270", "text": "hello"},
                headers=self.auth_headers(),
            )

        self.assertEqual(response.status_code, 500)

    def test_job_detail_returns_queued_job(self):
        conn = FakeMariaDBConnection()
        device = devices.add_device(conn, "mdv", "192.168.10.21", 5555)
        job = send_queue.enqueue_send_job(
            conn,
            "/api/sendText",
            device,
            "mdv",
            "256740932270",
            "hello",
            None,
            False,
            "api-worker-1",
            30,
        )

        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}), patch(
            "adb_automation.api.open_database", return_value=conn
        ), patch("adb_automation.api.init_database"):
            response = self.client.get(
                f"/api/jobs/{job['id']}",
                headers=self.auth_headers(),
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["job"]["id"], job["id"])
        self.assertEqual(payload["job"]["status"], "pending")
        self.assertEqual(payload["job"]["device"], "mdv")

    def test_job_detail_returns_not_found(self):
        conn = FakeMariaDBConnection()

        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}), patch(
            "adb_automation.api.open_database", return_value=conn
        ), patch("adb_automation.api.init_database"):
            response = self.client.get("/api/jobs/999", headers=self.auth_headers())

        self.assertEqual(response.status_code, 404)

    def test_job_list_filters_by_status_and_limit(self):
        conn = FakeMariaDBConnection()
        device = devices.add_device(conn, "mdv", "192.168.10.21", 5555)
        pending = send_queue.enqueue_send_job(
            conn,
            "/api/sendText",
            device,
            "mdv",
            "256740932270",
            "hello",
            None,
            False,
            "api-worker-1",
            30,
        )
        failed = send_queue.enqueue_send_job(
            conn,
            "/api/sendText",
            device,
            "mdv",
            "256740932271",
            "hello",
            None,
            False,
            "api-worker-1",
            30,
        )
        conn.send_jobs[1]["status"] = "failed"

        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}), patch(
            "adb_automation.api.open_database", return_value=conn
        ), patch("adb_automation.api.init_database"):
            response = self.client.get(
                "/api/jobs?status=failed&limit=1",
                headers=self.auth_headers(),
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["jobs"]), 1)
        self.assertEqual(payload["jobs"][0]["id"], failed["id"])
        self.assertNotEqual(payload["jobs"][0]["id"], pending["id"])

    def test_job_list_rejects_invalid_status_and_limit(self):
        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}):
            status_response = self.client.get(
                "/api/jobs?status=nope",
                headers=self.auth_headers(),
            )
            limit_response = self.client.get(
                "/api/jobs?limit=zero",
                headers=self.auth_headers(),
            )

        self.assertEqual(status_response.status_code, 400)
        self.assertEqual(limit_response.status_code, 400)

    def test_device_list_requires_auth(self):
        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}):
            response = self.client.get("/api/devices")

        self.assertEqual(response.status_code, 401)

    def test_device_list_merges_database_devices_with_adb_state(self):
        conn = FakeMariaDBConnection()
        device = devices.add_device(conn, "phone-01", "192.168.10.21", 5555)
        conn.devices[0]["worker_id"] = "worker-a"
        conn.devices[0]["locked_until"] = "2099-01-01T00:00:00+00:00"
        conn.devices[0]["last_seen_at"] = "2026-06-14T12:00:00+00:00"

        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}), patch(
            "adb_automation.api.open_database", return_value=conn
        ), patch("adb_automation.api.init_database"), patch(
            "adb_automation.api.get_connected_device_states",
            return_value={devices.device_serial(device): "device"},
        ):
            response = self.client.get("/api/devices", headers=self.auth_headers())

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["devices"][0]["name"], "phone-01")
        self.assertEqual(payload["devices"][0]["serial"], "192.168.10.21:5555")
        self.assertEqual(payload["devices"][0]["adb_state"], "device")
        self.assertTrue(payload["devices"][0]["connected"])
        self.assertEqual(payload["devices"][0]["worker_id"], "worker-a")
        self.assertTrue(conn.closed)

    def test_add_device_route_saves_device(self):
        conn = FakeMariaDBConnection()

        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}), patch(
            "adb_automation.api.open_database", return_value=conn
        ), patch("adb_automation.api.init_database"), patch(
            "adb_automation.api.get_connected_device_states", return_value={}
        ):
            response = self.post_json(
                "/api/devices",
                {"name": "phone-01", "ip": "192.168.10.21", "port": 5555},
                headers=self.auth_headers(),
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 201)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["device"]["name"], "phone-01")
        self.assertEqual(payload["device"]["adb_state"], "disconnected")
        self.assertEqual(conn.devices[0]["ip"], "192.168.10.21")
        self.assertTrue(conn.closed)

    def test_connect_device_route_runs_adb_and_marks_seen(self):
        conn = FakeMariaDBConnection()
        device = devices.add_device(conn, "phone-01", "192.168.10.21", 5555)
        serial = devices.device_serial(device)

        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}), patch(
            "adb_automation.api.open_database", return_value=conn
        ), patch("adb_automation.api.init_database"), patch(
            "adb_automation.api.connect_wifi_device",
            return_value=f"connected to {serial}",
        ) as connect_wifi_device, patch(
            "adb_automation.api.get_connected_device_states",
            return_value={serial: "device"},
        ):
            response = self.post_json(
                f"/api/devices/{device['id']}/connect",
                {},
                headers=self.auth_headers(),
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["device"]["connected"])
        self.assertEqual(payload["adb_output"], f"connected to {serial}")
        self.assertIsNotNone(conn.devices[0]["last_seen_at"])
        connect_wifi_device.assert_called_once_with(serial)
        self.assertTrue(conn.closed)

    def test_connect_device_route_returns_adb_error(self):
        conn = FakeMariaDBConnection()
        device = devices.add_device(conn, "phone-01", "192.168.10.21", 5555)

        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}), patch(
            "adb_automation.api.open_database", return_value=conn
        ), patch("adb_automation.api.init_database"), patch(
            "adb_automation.api.connect_wifi_device",
            side_effect=AutomationError("adb failed"),
        ):
            response = self.post_json(
                f"/api/devices/{device['id']}/connect",
                {},
                headers=self.auth_headers(),
            )

        self.assertEqual(response.status_code, 500)
        self.assertIn("adb failed", response.get_json()["error"])
        self.assertTrue(conn.closed)

    def test_pair_route_requires_pairing_code(self):
        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}):
            response = self.post_json(
                "/api/pair",
                {
                    "name": "phone-01",
                    "pair_ip": "192.168.10.21",
                    "pair_port": 37123,
                    "connect_ip": "192.168.10.21",
                    "connect_port": 5555,
                },
                headers=self.auth_headers(),
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("pairing_code is required", response.get_json()["error"])

    def test_pair_route_rejects_duplicate_endpoint_before_adb(self):
        conn = FakeMariaDBConnection()
        devices.add_device(conn, "phone-01", "192.168.10.21", 5555)

        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}), patch(
            "adb_automation.api.open_database", return_value=conn
        ), patch("adb_automation.api.init_database"), patch(
            "adb_automation.api.pair_wifi_device"
        ) as pair_wifi_device:
            response = self.post_json(
                "/api/pair",
                {
                    "name": "phone-02",
                    "pair_ip": "192.168.10.21",
                    "pair_port": 37123,
                    "pairing_code": "123456",
                    "connect_ip": "192.168.10.21",
                    "connect_port": 5555,
                },
                headers=self.auth_headers(),
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("device IP/port already exists", response.get_json()["error"])
        pair_wifi_device.assert_not_called()
        self.assertTrue(conn.closed)

    def test_pair_route_pairs_then_saves_device(self):
        conn = FakeMariaDBConnection()

        with patch.dict(os.environ, {"ADB_AUTOMATION_API_KEY": self.api_key}), patch(
            "adb_automation.api.open_database", return_value=conn
        ), patch("adb_automation.api.init_database"), patch(
            "adb_automation.api.pair_wifi_device", return_value="Successfully paired"
        ) as pair_wifi_device, patch(
            "adb_automation.api.get_connected_device_states",
            return_value={"192.168.10.21:5555": "device"},
        ):
            response = self.post_json(
                "/api/pair",
                {
                    "name": "phone-01",
                    "pair_ip": "192.168.10.21",
                    "pair_port": 37123,
                    "pairing_code": "123456",
                    "connect_ip": "192.168.10.21",
                    "connect_port": 5555,
                },
                headers=self.auth_headers(),
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 201)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["adb_output"], "Successfully paired")
        self.assertEqual(payload["device"]["name"], "phone-01")
        self.assertTrue(payload["device"]["connected"])
        self.assertEqual(conn.devices[0]["port"], 5555)
        pair_wifi_device.assert_called_once_with("192.168.10.21", 37123, "123456")
        self.assertTrue(conn.closed)


if __name__ == "__main__":
    unittest.main()
