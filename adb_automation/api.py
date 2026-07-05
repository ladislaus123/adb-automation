import hmac
import os
import socket

import mysql.connector
from flask import Flask, jsonify, request, send_from_directory

from .adb import connect_wifi_device, get_connected_device_states, pair_wifi_device
from .config import (
    API_KEY_ENV_VAR,
    DEFAULT_LEASE_SECONDS,
    LEASE_ENV_VAR,
    STOCHASTIC_ENABLED_ENV_VAR,
    env_int,
    env_bool,
    parse_positive_int,
)
from .db import init_database, open_database
from .devices import (
    add_device,
    device_serial,
    find_device,
    find_device_by_endpoint,
    get_device_by_id,
    list_devices,
    mark_device_seen,
)
from .downloaded_media import cleanup_downloaded_media_file, download_media_url_to_temp
from .errors import AutomationError
from .queue_worker import start_queue_workers
from .send_queue import (
    JOB_STATUSES,
    enqueue_send_job,
    enqueue_stochastic_job_if_due,
    get_send_job,
    list_send_jobs,
    parse_job_limit,
)


def create_app(start_queue_workers=True):
    app = Flask(__name__)

    register_frontend_routes(app)
    register_device_routes(app)
    register_job_routes(app)
    register_send_route(app, "/api/sendText", text_required=True)
    register_send_route(app, "/api/sendImage", media_required=True)
    register_send_route(app, "/api/sendVoice", media_required=True)
    register_send_route(app, "/api/sendVideo", media_required=True)

    if start_queue_workers:
        app.queue_worker_threads = start_queue_workers_fn()

    return app


def start_queue_workers_fn():
    return start_queue_workers()


def register_frontend_routes(app):
    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")


def register_device_routes(app):
    @app.get("/api/devices")
    def api_list_devices():
        auth_error = validate_api_key()
        if auth_error:
            return auth_error

        conn = None
        try:
            conn = open_database()
            init_database(conn)
            states = get_connected_device_states()
            devices = [
                serialize_device(device, states) for device in list_devices(conn)
            ]
            return jsonify({"success": True, "devices": devices})
        except (AutomationError, mysql.connector.Error) as exc:
            return json_error(str(exc), 500)
        finally:
            if conn is not None:
                conn.close()

    @app.post("/api/devices")
    def api_add_device():
        auth_error = validate_api_key()
        if auth_error:
            return auth_error

        try:
            payload = get_json_payload()
            device_request = parse_device_request(payload)
        except ValueError as exc:
            return json_error(str(exc), 400)

        conn = None
        try:
            conn = open_database()
            init_database(conn)
            device = add_device(
                conn,
                device_request["name"],
                device_request["ip"],
                device_request["port"],
            )
            states = get_connected_device_states()
            return jsonify(
                {"success": True, "device": serialize_device(device, states)}
            ), 201
        except ValueError as exc:
            return json_error(str(exc), 400)
        except (AutomationError, mysql.connector.Error) as exc:
            return json_error(str(exc), 500)
        finally:
            if conn is not None:
                conn.close()

    @app.post("/api/devices/<int:device_id>/connect")
    def api_connect_device(device_id):
        auth_error = validate_api_key()
        if auth_error:
            return auth_error

        conn = None
        try:
            conn = open_database()
            init_database(conn)
            device = get_device_by_id(conn, device_id)
            if not device:
                return json_error("device not found.", 404)

            serial = device_serial(device)
            adb_output = connect_wifi_device(serial)
            states = get_connected_device_states()
            if states.get(serial) == "device":
                mark_device_seen(conn, device["id"])
                device = get_device_by_id(conn, device["id"])

            return jsonify(
                {
                    "success": True,
                    "adb_output": adb_output,
                    "device": serialize_device(device, states),
                }
            )
        except (AutomationError, mysql.connector.Error) as exc:
            return json_error(str(exc), 500)
        finally:
            if conn is not None:
                conn.close()

    @app.post("/api/pair")
    def api_pair_device():
        auth_error = validate_api_key()
        if auth_error:
            return auth_error

        try:
            payload = get_json_payload()
            pair_request = parse_pair_request(payload)
        except ValueError as exc:
            return json_error(str(exc), 400)

        conn = None
        try:
            conn = open_database()
            init_database(conn)
            if find_device(conn, pair_request["name"]):
                return json_error("device name already exists.", 400)
            if find_device_by_endpoint(
                conn, pair_request["connect_ip"], pair_request["connect_port"]
            ):
                return json_error("device IP/port already exists.", 400)

            adb_output = pair_wifi_device(
                pair_request["pair_ip"],
                pair_request["pair_port"],
                pair_request["pairing_code"],
            )
            device = add_device(
                conn,
                pair_request["name"],
                pair_request["connect_ip"],
                pair_request["connect_port"],
            )
            states = get_connected_device_states()
            return jsonify(
                {
                    "success": True,
                    "adb_output": adb_output,
                    "device": serialize_device(device, states),
                }
            ), 201
        except ValueError as exc:
            return json_error(str(exc), 400)
        except (AutomationError, mysql.connector.Error) as exc:
            return json_error(str(exc), 500)
        finally:
            if conn is not None:
                conn.close()


def register_send_route(app, endpoint, text_required=False, media_required=False):
    def handler():
        auth_error = validate_api_key()
        if auth_error:
            return auth_error

        try:
            payload = get_json_payload()
            send_request = parse_send_request(
                payload,
                endpoint=endpoint,
                text_required=text_required,
                media_required=media_required,
            )
        except ValueError as exc:
            return json_error(str(exc), 400)

        conn = None
        downloaded_file_path = None
        try:
            conn = open_database()
            init_database(conn)
            device = find_device(conn, send_request["device"])
            if not device:
                raise ValueError(f"device not found: {send_request['device']}")

            if send_request["file_url"]:
                downloaded_file_path = download_media_url_to_temp(
                    send_request["file_url"],
                    filename=send_request["file_filename"],
                )
                send_request["file_path"] = downloaded_file_path

            job = enqueue_send_job(
                conn,
                endpoint,
                device,
                send_request["device"],
                send_request["phone"],
                send_request["text"],
                send_request["file_path"],
                send_request["business"],
                send_request["worker_id"],
                send_request["lease_seconds"],
            )
            if env_bool(STOCHASTIC_ENABLED_ENV_VAR):
                stochastic_job = enqueue_stochastic_job_if_due(
                    conn,
                    device,
                    send_request["device"],
                    send_request["worker_id"],
                    send_request["lease_seconds"],
                )
                if stochastic_job:
                    print(
                        "[*] Queued stochastic phone activity job "
                        f"{stochastic_job['id']} after send job {job['id']}."
                    )
            return jsonify(
                {
                    "success": True,
                    "queued": True,
                    "job_id": job["id"],
                    "status": job["status"],
                    "endpoint": endpoint,
                    "device": send_request["device"],
                    "device_id": device["id"],
                    "phone": send_request["phone"],
                }
            ), 202
        except ValueError as exc:
            cleanup_downloaded_media_file(downloaded_file_path)
            return json_error(str(exc), 400)
        except (AutomationError, mysql.connector.Error) as exc:
            cleanup_downloaded_media_file(downloaded_file_path)
            return json_error(str(exc), 500)
        finally:
            if conn is not None:
                conn.close()

    app.add_url_rule(endpoint, endpoint, handler, methods=["POST"])


def register_job_routes(app):
    @app.get("/api/jobs/<int:job_id>")
    def api_get_job(job_id):
        auth_error = validate_api_key()
        if auth_error:
            return auth_error

        conn = None
        try:
            conn = open_database()
            init_database(conn)
            job = get_send_job(conn, job_id)
            if not job:
                return json_error("job not found.", 404)
            return jsonify({"success": True, "job": serialize_job(job)})
        except (AutomationError, mysql.connector.Error) as exc:
            return json_error(str(exc), 500)
        finally:
            if conn is not None:
                conn.close()

    @app.get("/api/jobs")
    def api_list_jobs():
        auth_error = validate_api_key()
        if auth_error:
            return auth_error

        try:
            status = optional_query_string("status")
            if status and status not in JOB_STATUSES:
                raise ValueError("status must be one of: " + ", ".join(JOB_STATUSES))
            limit = parse_job_limit(request.args.get("limit", "50"))
        except ValueError as exc:
            return json_error(str(exc), 400)

        conn = None
        try:
            conn = open_database()
            init_database(conn)
            jobs = list_send_jobs(conn, status=status, limit=limit)
            return jsonify(
                {
                    "success": True,
                    "jobs": [serialize_job(job) for job in jobs],
                }
            )
        except (AutomationError, mysql.connector.Error) as exc:
            return json_error(str(exc), 500)
        finally:
            if conn is not None:
                conn.close()


def validate_api_key():
    expected = os.environ.get(API_KEY_ENV_VAR)
    if not expected:
        return json_error("API key is not configured.", 500)

    provided = request.headers.get("X-API-Key", "")
    if not provided or not hmac.compare_digest(provided, expected):
        return json_error("invalid or missing API key.", 401)

    return None


def get_json_payload():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object.")
    return payload


def parse_send_request(payload, endpoint, text_required=False, media_required=False):
    device = require_string(payload, "device")
    phone = require_string(payload, "phone")
    text = optional_string(payload, "text") or optional_string(payload, "caption")
    file_request = parse_media_file_request(payload)
    business = parse_bool(payload.get("business", False), "business")
    worker_id = optional_string(payload, "worker_id") or default_api_worker_id()
    lease_seconds = parse_lease_seconds(payload.get("lease_seconds"))

    if text_required and not text:
        raise ValueError("text is required.")

    if media_required:
        if not file_request["file_path"] and not file_request["file_url"]:
            raise ValueError("file or file_path is required, or provide file.url.")
        if file_request["file_path"] and not os.path.exists(file_request["file_path"]):
            raise ValueError(f"media file not found: {file_request['file_path']}")

    return {
        "endpoint": endpoint,
        "device": device,
        "phone": phone,
        "text": text,
        "file_path": file_request["file_path"],
        "file_url": file_request["file_url"],
        "file_filename": file_request["file_filename"],
        "business": business,
        "worker_id": worker_id,
        "lease_seconds": lease_seconds,
    }


def parse_media_file_request(payload):
    file_path = optional_string(payload, "file_path")
    file_url = optional_string(payload, "file_url")
    file_filename = None
    file_value = payload.get("file")

    if file_path:
        return {
            "file_path": file_path,
            "file_url": None,
            "file_filename": None,
        }

    if isinstance(file_value, str):
        file_path = file_value.strip() or None
        return {
            "file_path": file_path,
            "file_url": None if file_path else file_url,
            "file_filename": None,
        }

    if isinstance(file_value, dict):
        file_url = optional_string(file_value, "url") or file_url
        file_filename = optional_string(file_value, "filename")
        if not file_url:
            raise ValueError("file.url is required when file is an object.")

    elif file_value is not None:
        raise ValueError("file must be a string path or an object with url.")

    return {
        "file_path": None,
        "file_url": file_url,
        "file_filename": file_filename,
    }


def parse_device_request(payload):
    return {
        "name": require_string(payload, "name"),
        "ip": require_string(payload, "ip"),
        "port": parse_network_port(payload.get("port"), "port"),
    }


def parse_pair_request(payload):
    return {
        "name": require_string(payload, "name"),
        "pair_ip": require_string(payload, "pair_ip"),
        "pair_port": parse_network_port(payload.get("pair_port"), "pair_port"),
        "pairing_code": require_string(payload, "pairing_code"),
        "connect_ip": require_string(payload, "connect_ip"),
        "connect_port": parse_network_port(
            payload.get("connect_port"), "connect_port"
        ),
    }


def parse_network_port(value, field):
    port = parse_positive_int(value, field)
    if port > 65535:
        raise ValueError(f"{field} must be between 1 and 65535.")
    return port


def serialize_device(device, states):
    serial = device_serial(device)
    adb_state = states.get(serial)
    return {
        "id": device["id"],
        "name": device["name"],
        "ip": device["ip"],
        "port": device["port"],
        "serial": serial,
        "adb_state": adb_state or "disconnected",
        "connected": adb_state == "device",
        "worker_id": device["worker_id"],
        "locked_until": device["locked_until"],
        "last_seen_at": device["last_seen_at"],
    }


def serialize_job(job):
    return {
        "id": job["id"],
        "status": job["status"],
        "endpoint": job["endpoint"],
        "device_id": job["device_id"],
        "device": job["device_selector"],
        "phone": job["phone"],
        "text": job["text"],
        "file_path": job["file_path"],
        "business": bool(job["business"]),
        "worker_id": job["worker_id"],
        "lease_seconds": job["lease_seconds"],
        "queue_worker_id": job["queue_worker_id"],
        "device_locked_until": job["device_locked_until"],
        "error": job["error"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
    }


def require_string(payload, field):
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required.")
    return value.strip()


def optional_string(payload, field):
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string.")
    value = value.strip()
    return value or None


def optional_query_string(field):
    value = request.args.get(field)
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_bool(value, field):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    raise ValueError(f"{field} must be a boolean.")


def parse_lease_seconds(value):
    if value is None:
        return env_int(LEASE_ENV_VAR, DEFAULT_LEASE_SECONDS)
    return parse_positive_int(value, "lease_seconds")


def default_api_worker_id():
    return f"api-{socket.gethostname()}-{os.getpid()}"


def json_error(message, status):
    response = jsonify({"success": False, "error": message})
    return response, status
