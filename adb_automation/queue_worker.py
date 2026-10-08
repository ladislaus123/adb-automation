import os
import socket
import threading
import time

import mysql.connector

from .adb import ensure_device_ready, wake_and_unlock_device
from .config import (
    CONTACT_NAV_ENABLED_ENV_VAR,
    DEFAULT_QUEUE_POLL_SECONDS,
    QUEUE_POLL_SECONDS_ENV_VAR,
    QUEUE_WORKERS_ENV_VAR,
    env_bool,
    parse_positive_int,
)
from .db import init_database, open_database
from .devices import (
    device_adb_transport,
    device_serial,
    mark_device_seen,
    normalize_worker_id,
    release_device_lease,
)
from .downloaded_media import cleanup_downloaded_media_file
from .errors import (
    AdbError,
    AutomationError,
    WhatsAppLoggedOutError,
    WhatsAppRestrictedError,
)
from .notifications import (
    notify_session_disconnected,
    notify_session_restricted,
)
from .recovery_queue import enqueue_recovery_job
from .send_queue import (
    claim_next_send_job,
    complete_send_job,
    fail_send_job,
    is_phone_known_for_device,
    is_stochastic_job,
)
from .stochastic import run_stochastic_actions
from .whatsapp import send_whatsapp

_queue_workers_started = False
_queue_workers_lock = threading.Lock()


def configured_worker_count():
    cpu_count = os.cpu_count() or 1
    value = os.environ.get(QUEUE_WORKERS_ENV_VAR)
    if value is None or not str(value).strip():
        return cpu_count

    count = parse_positive_int(value, QUEUE_WORKERS_ENV_VAR)
    return min(count, cpu_count)


def configured_poll_seconds():
    value = os.environ.get(QUEUE_POLL_SECONDS_ENV_VAR)
    if value is None or not str(value).strip():
        return DEFAULT_QUEUE_POLL_SECONDS

    try:
        poll_seconds = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{QUEUE_POLL_SECONDS_ENV_VAR} must be a number.")
    if poll_seconds <= 0:
        raise ValueError(f"{QUEUE_POLL_SECONDS_ENV_VAR} must be greater than zero.")
    return poll_seconds


def queue_worker_id(index):
    return f"queue-{socket.gethostname()}-{os.getpid()}-{index}"


def start_queue_workers(count=None, poll_seconds=None):
    global _queue_workers_started
    with _queue_workers_lock:
        if _queue_workers_started:
            return []

        if count is None:
            count = configured_worker_count()
        if poll_seconds is None:
            poll_seconds = configured_poll_seconds()

        threads = []
        for index in range(count):
            worker_id = queue_worker_id(index + 1)
            thread = threading.Thread(
                target=queue_worker_loop,
                name=worker_id,
                args=(worker_id, poll_seconds),
                daemon=True,
            )
            thread.start()
            threads.append(thread)

        _queue_workers_started = True
        return threads


def queue_worker_loop(worker_id, poll_seconds, stop_event=None):
    while stop_event is None or not stop_event.is_set():
        try:
            conn = open_database()
            try:
                init_database(conn)
                processed = run_queue_once(conn, worker_id)
            finally:
                conn.close()
        except (AutomationError, mysql.connector.Error, ValueError) as exc:
            print(f"[WARN] Queue worker {worker_id} failed: {exc}")
            processed = False

        if not processed:
            time.sleep(poll_seconds)


def run_queue_once(conn, queue_worker_id_value=None):
    worker_id = normalize_worker_id(queue_worker_id_value)
    job = claim_next_send_job(conn, worker_id)
    if not job:
        return False

    process_claimed_job(conn, job)
    return True


def start_recovery_for_job(conn, job, reason):
    """Enqueue a WhatsApp ban-recovery job for the device of a failed send.

    Idempotent (enqueue_recovery_job skips if one is already in flight) and
    defensive: a recovery-enqueue failure must never mask the original send
    failure or break the worker loop."""
    try:
        device = job.get("device") or {}
        if not device:
            return
        enqueue_recovery_job(
            conn,
            device,
            business=bool(job.get("business")),
            # The device's OWN WhatsApp number (not the send recipient in
            # job["phone"]); enqueue_recovery_job falls back to the device row.
            phone=device.get("whatsapp_phone"),
            reason=str(reason),
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[WARN] Could not enqueue recovery job: {exc}")


def determine_known_contact(conn, job):
    if is_stochastic_job(job):
        return None
    if not env_bool(CONTACT_NAV_ENABLED_ENV_VAR, True):
        return None

    try:
        return is_phone_known_for_device(conn, job["device_id"], job["phone"])
    except Exception as exc:
        print(f"[WARN] Known-contact check failed; using link route: {exc}")
        return None


def process_claimed_job(conn, job):
    device = job["device"]
    serial = device_serial(device)
    adb_transport = device_adb_transport(device)
    file_path = job["file_path"]
    known_contact = determine_known_contact(conn, job)

    try:
        ensure_device_ready(serial, adb_transport=adb_transport)
        wake_and_unlock_device(serial)
        mark_device_seen(conn, device["id"])
        if is_stochastic_job(job):
            run_stochastic_actions(serial)
        else:
            send_whatsapp(
                serial,
                job["phone"],
                text=job["text"],
                file_path=file_path,
                business=bool(job["business"]),
                known_contact=known_contact,
                adb_transport=adb_transport,
            )
        complete_send_job(conn, job["id"])
        print(f"[+] Queue job {job['id']} completed.")
    except Exception as exc:
        fail_send_job(conn, job["id"], exc)
        print(f"[-] Queue job {job['id']} failed: {exc}")
        if isinstance(exc, WhatsAppRestrictedError):
            # Tell the downstream service the device's WhatsApp is restricted so
            # it can mark the session unavailable and pause its campaigns.
            notify_session_restricted(job, exc)
            # Kick off (idempotently) the automated ban-recovery flow: request a
            # review ("pedir analise"), wait for approval, then re-login.
            start_recovery_for_job(conn, job, exc)
        elif isinstance(exc, WhatsAppLoggedOutError):
            # Account logged out on the device -> the session is gone. Tell the
            # downstream service so it can mark the session CAIU and pause it.
            notify_session_disconnected(job, exc, event="session_disconnected")
            start_recovery_for_job(conn, job, exc)
        elif isinstance(exc, AdbError) and "not visible in adb" in str(exc):
            # Device dropped out of adb (offline/unplugged/rebooting). Often
            # transient, so the downstream service debounces this before acting.
            notify_session_disconnected(job, exc, event="device_offline")
    finally:
        try:
            release_device_lease(
                conn,
                device["id"],
                job["queue_worker_id"],
                job["device_locked_until"],
            )
        finally:
            cleanup_downloaded_media_file(file_path)
