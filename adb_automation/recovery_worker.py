"""Background worker that drives the WhatsApp ban-recovery state machine.

One daemon thread polls `whatsapp_recovery_jobs` (via claim_next_recovery_job,
which also leases the device, so recovery never collides with a normal send) and
dispatches each claimed job on its status to the UI automation in
whatsapp_recovery.py. Shaped exactly like queue_worker.py: fresh connection per
tick, init_database every loop, release the device lease in `finally`.
"""

import os
import socket
import threading
import time
from datetime import timedelta

import mysql.connector

from .adb import ensure_device_ready, wake_and_unlock_device
from .config import (
    DEFAULT_RECOVERY_MAX_ATTEMPTS,
    DEFAULT_RECOVERY_POLL_SECONDS,
    DEFAULT_RECOVERY_REVIEW_BACKOFF_SECONDS,
    RECOVERY_ENABLED_ENV_VAR,
    RECOVERY_MAX_ATTEMPTS_ENV_VAR,
    RECOVERY_POLL_SECONDS_ENV_VAR,
    RECOVERY_REVIEW_BACKOFF_ENV_VAR,
    env_bool,
    env_int,
)
from .db import init_database, open_database
from .devices import (
    device_adb_transport,
    device_serial,
    mark_device_seen,
    normalize_worker_id,
    release_device_lease,
    to_iso,
    utcnow,
)
from .errors import AutomationError
from .notifications import (
    RECOVERY_EVENT_FAILED,
    RECOVERY_EVENT_RECOVERED,
    RECOVERY_EVENT_STARTED,
    notify_recovery_event,
)
from .recovery_queue import (
    RECOVERY_STATUS_DETECTED,
    RECOVERY_STATUS_FAILED,
    RECOVERY_STATUS_RECOVERED,
    RECOVERY_STATUS_RELOGIN,
    RECOVERY_STATUS_REQUESTING_REVIEW,
    RECOVERY_STATUS_REVIEW_PENDING,
    bump_attempt_and_reschedule,
    claim_next_recovery_job,
    fail_recovery_job,
    mark_recovered,
    mark_relogin,
    mark_requesting_review,
    mark_review_pending,
)
from .whatsapp import get_whatsapp_package
from .whatsapp_recovery import (
    RECOVERY_SCREEN_CAN_REGISTER,
    RECOVERY_SCREEN_LOGGED_IN,
    RECOVERY_SCREEN_PERMANENT_BAN,
    RECOVERY_SCREEN_RESTRICTED,
    RECOVERY_SCREEN_REVIEW_PENDING,
    perform_relogin,
    registration_state,
    request_account_review,
)

_recovery_worker_started = False
_recovery_worker_lock = threading.Lock()

# Short backoff for a transient hiccup (an unexpected screen, a re-login retry)
# as opposed to the long review-approval wait.
TRANSIENT_BACKOFF_SECONDS = 60


def recovery_enabled():
    return env_bool(RECOVERY_ENABLED_ENV_VAR, True)


def configured_poll_seconds():
    value = os.environ.get(RECOVERY_POLL_SECONDS_ENV_VAR)
    if value is None or not str(value).strip():
        return DEFAULT_RECOVERY_POLL_SECONDS
    try:
        poll_seconds = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{RECOVERY_POLL_SECONDS_ENV_VAR} must be a number.")
    if poll_seconds <= 0:
        raise ValueError(f"{RECOVERY_POLL_SECONDS_ENV_VAR} must be greater than zero.")
    return poll_seconds


def configured_review_backoff_seconds():
    return env_int(RECOVERY_REVIEW_BACKOFF_ENV_VAR, DEFAULT_RECOVERY_REVIEW_BACKOFF_SECONDS)


def configured_max_attempts():
    return env_int(RECOVERY_MAX_ATTEMPTS_ENV_VAR, DEFAULT_RECOVERY_MAX_ATTEMPTS)


def recovery_worker_id():
    return f"recovery-{socket.gethostname()}-{os.getpid()}"


def start_recovery_worker(poll_seconds=None):
    global _recovery_worker_started
    with _recovery_worker_lock:
        if _recovery_worker_started:
            return None
        if not recovery_enabled():
            print("[*] WhatsApp recovery worker disabled via config.")
            return None
        if poll_seconds is None:
            poll_seconds = configured_poll_seconds()
        worker_id = recovery_worker_id()
        thread = threading.Thread(
            target=recovery_worker_loop,
            name=worker_id,
            args=(worker_id, poll_seconds),
            daemon=True,
        )
        thread.start()
        _recovery_worker_started = True
        return thread


def recovery_worker_loop(worker_id, poll_seconds, stop_event=None):
    while stop_event is None or not stop_event.is_set():
        try:
            conn = open_database()
            try:
                init_database(conn)
                processed = run_recovery_once(conn, worker_id)
            finally:
                conn.close()
        except (AutomationError, mysql.connector.Error, ValueError) as exc:
            print(f"[WARN] Recovery worker {worker_id} failed: {exc}")
            processed = False

        if not processed:
            time.sleep(poll_seconds)


def run_recovery_once(conn, worker_id=None):
    worker_id = normalize_worker_id(worker_id)
    job = claim_next_recovery_job(conn, worker_id)
    if not job:
        return False
    process_recovery_job(conn, job)
    return True


def process_recovery_job(conn, job):
    device = job["device"]
    serial = device_serial(device)
    adb_transport = device_adb_transport(device)
    business = bool(job.get("business"))
    # The device row is the source of truth so a number set after the job was
    # opened is what re-login types. The job's phone is only a snapshot.
    phone = device.get("whatsapp_phone") or job.get("phone")

    try:
        ensure_device_ready(serial, adb_transport=adb_transport)
        wake_and_unlock_device(serial)
        mark_device_seen(conn, device["id"])

        whatsapp_package = get_whatsapp_package(serial, business=business)
        if not whatsapp_package:
            raise AutomationError("WhatsApp package not found on device for recovery.")

        status = job["status"]
        if status in (RECOVERY_STATUS_DETECTED, RECOVERY_STATUS_REQUESTING_REVIEW):
            _handle_review_stage(conn, job, serial, whatsapp_package, adb_transport)
        elif status == RECOVERY_STATUS_REVIEW_PENDING:
            _handle_review_pending_stage(conn, job, serial, whatsapp_package, adb_transport)
        elif status == RECOVERY_STATUS_RELOGIN:
            _handle_relogin_stage(conn, job, serial, whatsapp_package, adb_transport, phone)
        else:  # defensive: an unexpected status, just reschedule
            bump_attempt_and_reschedule(
                conn, job["id"], status, TRANSIENT_BACKOFF_SECONDS,
                error=f"unexpected status {status}",
            )
        print(f"[+] Recovery job {job['id']} processed (was {status}).")
    except Exception as exc:
        _handle_stage_error(conn, job, exc)
        print(f"[-] Recovery job {job['id']} errored: {exc}")
    finally:
        release_device_lease(
            conn, device["id"], job["worker_id"], job["device_locked_until"]
        )


def _handle_review_stage(conn, job, serial, whatsapp_package, adb_transport):
    if job["status"] == RECOVERY_STATUS_DETECTED:
        mark_requesting_review(conn, job["id"])
        # Keep the in-memory status in step with the row so a UI error below
        # reschedules `requesting_review` instead of dropping back to `detected`
        # and firing `session_recovery_started` again.
        job["status"] = RECOVERY_STATUS_REQUESTING_REVIEW
        notify_recovery_event(job, event=RECOVERY_EVENT_STARTED, reason="requesting_review")

    screen = request_account_review(serial, whatsapp_package, adb_transport=adb_transport)
    _apply_screen(conn, job, screen, pending_error="review not confirmed")


def _handle_review_pending_stage(conn, job, serial, whatsapp_package, adb_transport):
    screen = registration_state(serial, whatsapp_package, adb_transport=adb_transport)
    _apply_screen(conn, job, screen, pending_error=None)


def _apply_screen(conn, job, screen, pending_error):
    """Map a classified WhatsApp screen onto the next recovery status.

    `pending_error` is set while we are still trying to submit the review. A
    screen that is still the restricted/unknown page then retries soon. Once
    the appeal is in, the same screens wait out the long review backoff.
    """
    if screen == RECOVERY_SCREEN_CAN_REGISTER:
        mark_relogin(conn, job["id"])
    elif screen == RECOVERY_SCREEN_LOGGED_IN:
        _recover(conn, job)
    elif screen == RECOVERY_SCREEN_PERMANENT_BAN:
        _fail(conn, job, "account permanently banned; review not possible.")
    elif screen == RECOVERY_SCREEN_REVIEW_PENDING:
        mark_review_pending(conn, job["id"], _review_due())
    elif screen == RECOVERY_SCREEN_RESTRICTED and pending_error is None:
        # The appeal screen is back (review rejected, or it was never submitted).
        # Ask again on the next claim instead of sleeping for the review backoff.
        mark_requesting_review(conn, job["id"])
    elif pending_error is not None:
        _retry_or_fail(
            conn,
            job,
            RECOVERY_STATUS_REQUESTING_REVIEW,
            TRANSIENT_BACKOFF_SECONDS,
            f"{pending_error} (screen={screen})",
        )
    else:
        mark_review_pending(conn, job["id"], _review_due())


def _handle_relogin_stage(conn, job, serial, whatsapp_package, adb_transport, phone):
    screen = registration_state(serial, whatsapp_package, adb_transport=adb_transport)
    if screen == RECOVERY_SCREEN_LOGGED_IN:
        _recover(conn, job)
        return
    if screen == RECOVERY_SCREEN_PERMANENT_BAN:
        _fail(conn, job, "account permanently banned; cannot re-login.")
        return
    if screen == RECOVERY_SCREEN_REVIEW_PENDING:
        # Number not available yet after all; drop back to waiting.
        mark_review_pending(conn, job["id"], _review_due())
        return

    perform_relogin(serial, whatsapp_package, phone, adb_transport=adb_transport)
    _recover(conn, job)


def _handle_stage_error(conn, job, exc):
    # A failure before the detected -> requesting_review transition stays
    # `detected`, so the next successful pass is what emits the started webhook.
    _retry_or_fail(conn, job, job["status"], TRANSIENT_BACKOFF_SECONDS, str(exc))


def _retry_or_fail(conn, job, status, backoff_seconds, error):
    attempts = int(job.get("attempts") or 0)
    if attempts + 1 >= configured_max_attempts():
        _fail(conn, job, f"max attempts reached: {error}")
        return
    bump_attempt_and_reschedule(conn, job["id"], status, backoff_seconds, error=error)


def _recover(conn, job):
    updated = mark_recovered(conn, job["id"])
    if updated and updated["status"] == RECOVERY_STATUS_RECOVERED:
        notify_recovery_event(updated, event=RECOVERY_EVENT_RECOVERED, reason="recovered")


def _fail(conn, job, reason):
    updated = fail_recovery_job(conn, job["id"], reason)
    if updated and updated["status"] == RECOVERY_STATUS_FAILED:
        notify_recovery_event(updated, event=RECOVERY_EVENT_FAILED, reason=reason)


def _review_due():
    return to_iso(utcnow() + timedelta(seconds=configured_review_backoff_seconds()))
