"""DB-backed state machine for recovering a device's WhatsApp account after a
restriction/ban: request a review ("pedir analise"), wait for approval, then
re-register the same number and let WhatsApp auto-fill the SMS code.

Mirrors send_queue.py: a status column drives the machine, and a job is claimed
atomically together with the device lease (the same `worker_id`/`locked_until`
columns on `devices`) so a recovery never runs on a device at the same time as a
normal send, and vice versa.
"""

from datetime import timedelta

from .config import DEFAULT_LEASE_SECONDS, parse_positive_int
from .devices import (
    execute_write,
    fetch_all,
    fetch_one,
    get_device_by_id,
    lock_is_active,
    normalize_whatsapp_phone,
    normalize_worker_id,
    now_iso,
    to_iso,
    utcnow,
)

RECOVERY_STATUS_DETECTED = "detected"
RECOVERY_STATUS_REQUESTING_REVIEW = "requesting_review"
RECOVERY_STATUS_REVIEW_PENDING = "review_pending"
RECOVERY_STATUS_RELOGIN = "relogin"
RECOVERY_STATUS_RECOVERED = "recovered"
RECOVERY_STATUS_FAILED = "failed"
RECOVERY_STATUS_CANCELLED = "cancelled"

RECOVERY_STATUSES = (
    RECOVERY_STATUS_DETECTED,
    RECOVERY_STATUS_REQUESTING_REVIEW,
    RECOVERY_STATUS_REVIEW_PENDING,
    RECOVERY_STATUS_RELOGIN,
    RECOVERY_STATUS_RECOVERED,
    RECOVERY_STATUS_FAILED,
    RECOVERY_STATUS_CANCELLED,
)

# Non-terminal states: a device with a row in any of these has an in-flight
# recovery, so a new one is not enqueued and the worker will keep acting on it.
RECOVERY_ACTIVE_STATUSES = (
    RECOVERY_STATUS_DETECTED,
    RECOVERY_STATUS_REQUESTING_REVIEW,
    RECOVERY_STATUS_REVIEW_PENDING,
    RECOVERY_STATUS_RELOGIN,
)
RECOVERY_TERMINAL_STATUSES = (
    RECOVERY_STATUS_RECOVERED,
    RECOVERY_STATUS_FAILED,
    RECOVERY_STATUS_CANCELLED,
)

DEFAULT_RECOVERY_LIST_LIMIT = 50
MAX_RECOVERY_LIST_LIMIT = 500


def parse_recovery_limit(value):
    limit = parse_positive_int(value, "limit")
    return min(limit, MAX_RECOVERY_LIST_LIMIT)


def get_recovery_job(conn, job_id):
    return fetch_one(
        conn, "SELECT * FROM whatsapp_recovery_jobs WHERE id = %s", (job_id,)
    )


def list_recovery_jobs(conn, status=None, limit=DEFAULT_RECOVERY_LIST_LIMIT):
    limit = parse_recovery_limit(limit)
    if status:
        return fetch_all(
            conn,
            """
            SELECT * FROM whatsapp_recovery_jobs
            WHERE status = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (status, limit),
        )
    return fetch_all(
        conn,
        """
        SELECT * FROM whatsapp_recovery_jobs
        ORDER BY id DESC
        LIMIT %s
        """,
        (limit,),
    )


def active_recovery_for_device(conn, device_id):
    """Return the in-flight recovery row for a device, or None."""
    placeholders = ", ".join(["%s"] * len(RECOVERY_ACTIVE_STATUSES))
    return fetch_one(
        conn,
        f"""
        SELECT * FROM whatsapp_recovery_jobs
        WHERE device_id = %s AND status IN ({placeholders})
        ORDER BY id DESC
        LIMIT 1
        """,
        (device_id, *RECOVERY_ACTIVE_STATUSES),
    )


def enqueue_recovery_job(
    conn,
    device,
    business=False,
    phone=None,
    reason=None,
    lease_seconds=DEFAULT_LEASE_SECONDS,
):
    """Create a recovery job for a device unless one is already in flight.

    Idempotent per device: returns the existing active row if present, so it is
    safe to call from every send-job failure that trips the restricted/logged-out
    detection without piling up duplicate recoveries.
    """
    lease_seconds = parse_positive_int(lease_seconds, "lease seconds")
    # Lock the device row so two workers that both see "no active recovery"
    # cannot insert two jobs. The send-failure path calls this after its own
    # transaction has committed, so this does not nest inside that transaction.
    conn.start_transaction()
    try:
        locked = get_device_by_id(conn, device["id"], for_update=True)
        if not locked:
            raise ValueError(f"device not found: {device['id']}")
        existing = active_recovery_for_device(conn, device["id"])
        if existing:
            conn.commit()
            return existing

        raw_phone = phone if phone else locked.get("whatsapp_phone")
        phone_value = normalize_whatsapp_phone(raw_phone)
        timestamp = now_iso()
        # New jobs are immediately claimable.
        job_id = execute_write(
            conn,
            """
            INSERT INTO whatsapp_recovery_jobs (
                device_id, device_label, business, phone, status, stage, reason,
                attempts, next_attempt_at, lease_seconds, detected_at,
                created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                locked["id"],
                locked.get("name"),
                1 if business else 0,
                phone_value,
                RECOVERY_STATUS_DETECTED,
                RECOVERY_STATUS_DETECTED,
                str(reason) if reason is not None else None,
                0,
                timestamp,
                lease_seconds,
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_recovery_job(conn, job_id)


def claim_next_recovery_job(conn, worker_id):
    """Atomically claim the oldest due, actionable recovery job and lease its
    device. Returns the job (with `device` attached) or None."""
    worker_id = normalize_worker_id(worker_id)
    current = now_iso()
    placeholders = ", ".join(["%s"] * len(RECOVERY_ACTIVE_STATUSES))

    conn.start_transaction()
    try:
        jobs = fetch_all(
            conn,
            f"""
            SELECT * FROM whatsapp_recovery_jobs
            WHERE status IN ({placeholders})
              AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
            ORDER BY id ASC
            FOR UPDATE
            """,
            (*RECOVERY_ACTIVE_STATUSES, current),
        )

        for job in jobs:
            device = get_device_by_id(conn, job["device_id"], for_update=True)
            if not device:
                _fail_locked(conn, job["id"], f"device not found: {job['device_id']}")
                continue

            if lock_is_active(device, current):
                continue

            lease_seconds = parse_positive_int(
                job.get("lease_seconds") or DEFAULT_LEASE_SECONDS,
                "lease seconds",
            )
            locked_until = to_iso(utcnow() + timedelta(seconds=lease_seconds))
            timestamp = now_iso()

            execute_write(
                conn,
                """
                UPDATE devices
                SET worker_id = %s, locked_until = %s, updated_at = %s
                WHERE id = %s
                """,
                (worker_id, locked_until, timestamp, device["id"]),
            )
            execute_write(
                conn,
                """
                UPDATE whatsapp_recovery_jobs
                SET worker_id = %s, device_locked_until = %s,
                    started_at = COALESCE(started_at, %s), updated_at = %s
                WHERE id = %s
                """,
                (worker_id, locked_until, timestamp, timestamp, job["id"]),
            )
            conn.commit()

            claimed = get_recovery_job(conn, job["id"])
            claimed["device"] = get_device_by_id(conn, device["id"])
            return claimed

        conn.commit()
        return None
    except Exception:
        conn.rollback()
        raise


def _active_where_sql():
    """Updates only stick while the job is still active, so a cancel that
    commits mid-flight is not overwritten by the worker's next transition."""
    placeholders = ", ".join(["%s"] * len(RECOVERY_ACTIVE_STATUSES))
    return f"id = %s AND status IN ({placeholders})", RECOVERY_ACTIVE_STATUSES


def _fail_locked(conn, job_id, error):
    """Mark failed inside an already-open claim transaction (no commit here)."""
    timestamp = now_iso()
    where_sql, where_params = _active_where_sql()
    execute_write(
        conn,
        f"""
        UPDATE whatsapp_recovery_jobs
        SET status = %s, stage = %s, error = %s, finished_at = %s,
            next_attempt_at = NULL, updated_at = %s
        WHERE {where_sql}
        """,
        (
            RECOVERY_STATUS_FAILED,
            RECOVERY_STATUS_FAILED,
            str(error),
            timestamp,
            timestamp,
            job_id,
            *where_params,
        ),
    )


def _set_status(conn, job_id, status, stage=None, **columns):
    timestamp = now_iso()
    assignments = ["status = %s", "stage = %s", "updated_at = %s"]
    params = [status, stage if stage is not None else status, timestamp]
    for name, value in columns.items():
        assignments.append(f"{name} = %s")
        params.append(value)
    where_sql, where_params = _active_where_sql()
    params.append(job_id)
    params.extend(where_params)
    execute_write(
        conn,
        f"UPDATE whatsapp_recovery_jobs SET {', '.join(assignments)} WHERE {where_sql}",
        tuple(params),
    )
    conn.commit()
    return get_recovery_job(conn, job_id)


def mark_requesting_review(conn, job_id):
    """Move back to the review-request stage and make the job claimable now."""
    return _set_status(
        conn,
        job_id,
        RECOVERY_STATUS_REQUESTING_REVIEW,
        error=None,
        next_attempt_at=now_iso(),
    )


def mark_review_pending(conn, job_id, next_attempt_at, stage=None):
    timestamp = now_iso()
    active_placeholders = ", ".join(["%s"] * len(RECOVERY_ACTIVE_STATUSES))
    execute_write(
        conn,
        f"""
        UPDATE whatsapp_recovery_jobs
        SET status = %s, stage = %s,
            review_requested_at = COALESCE(review_requested_at, %s),
            next_attempt_at = %s, error = NULL, updated_at = %s
        WHERE id = %s AND status IN ({active_placeholders})
        """,
        (
            RECOVERY_STATUS_REVIEW_PENDING,
            stage or RECOVERY_STATUS_REVIEW_PENDING,
            timestamp,
            next_attempt_at,
            timestamp,
            job_id,
            *RECOVERY_ACTIVE_STATUSES,
        ),
    )
    conn.commit()
    return get_recovery_job(conn, job_id)


def mark_relogin(conn, job_id):
    """Move to re-login and make it immediately claimable."""
    return _set_status(
        conn,
        job_id,
        RECOVERY_STATUS_RELOGIN,
        error=None,
        next_attempt_at=now_iso(),
    )


def mark_recovered(conn, job_id):
    timestamp = now_iso()
    return _set_status(
        conn,
        job_id,
        RECOVERY_STATUS_RECOVERED,
        error=None,
        next_attempt_at=None,
        recovered_at=timestamp,
        finished_at=timestamp,
    )


def fail_recovery_job(conn, job_id, error):
    return _set_status(
        conn,
        job_id,
        RECOVERY_STATUS_FAILED,
        error=str(error),
        next_attempt_at=None,
        finished_at=now_iso(),
    )


def cancel_recovery_job(conn, job_id):
    return _set_status(
        conn,
        job_id,
        RECOVERY_STATUS_CANCELLED,
        next_attempt_at=None,
        finished_at=now_iso(),
    )


def bump_attempt_and_reschedule(
    conn, job_id, status, backoff_seconds, error=None
):
    """Increment the attempt counter and set `next_attempt_at = now + backoff`,
    keeping (or changing) the status so the worker retries later. Used both for a
    still-pending review (status review_pending) and a transient re-login failure
    (status relogin)."""
    backoff_seconds = parse_positive_int(backoff_seconds, "backoff seconds")
    next_attempt_at = to_iso(utcnow() + timedelta(seconds=backoff_seconds))
    timestamp = now_iso()
    active_placeholders = ", ".join(["%s"] * len(RECOVERY_ACTIVE_STATUSES))
    execute_write(
        conn,
        f"""
        UPDATE whatsapp_recovery_jobs
        SET status = %s, stage = %s, attempts = attempts + 1,
            next_attempt_at = %s, error = %s, updated_at = %s
        WHERE id = %s AND status IN ({active_placeholders})
        """,
        (
            status,
            status,
            next_attempt_at,
            str(error) if error is not None else None,
            timestamp,
            job_id,
            *RECOVERY_ACTIVE_STATUSES,
        ),
    )
    conn.commit()
    return get_recovery_job(conn, job_id)


def retry_recovery_job(conn, job_id):
    """Manual override: make an active job due right now."""
    job = get_recovery_job(conn, job_id)
    if not job:
        raise ValueError(f"recovery job not found: {job_id}")
    if job["status"] not in RECOVERY_ACTIVE_STATUSES:
        raise ValueError(
            f"recovery job {job_id} is {job['status']}; only active jobs can retry."
        )
    return _set_status(
        conn,
        job_id,
        job["status"],
        stage=job.get("stage"),
        error=None,
        next_attempt_at=now_iso(),
    )
