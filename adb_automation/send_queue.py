from datetime import timedelta

from .config import DEFAULT_LEASE_SECONDS, parse_positive_int
from .devices import (
    execute_write,
    fetch_all,
    fetch_one,
    get_device_by_id,
    lock_is_active,
    normalize_worker_id,
    now_iso,
    to_iso,
    utcnow,
)

JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_SUCCEEDED = "succeeded"
JOB_STATUS_FAILED = "failed"
JOB_STATUSES = (
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    JOB_STATUS_FAILED,
)

DEFAULT_JOB_LIST_LIMIT = 50
MAX_JOB_LIST_LIMIT = 500


def enqueue_send_job(
    conn,
    endpoint,
    device,
    device_selector,
    phone,
    text,
    file_path,
    business,
    worker_id,
    lease_seconds,
):
    timestamp = now_iso()
    job_id = execute_write(
        conn,
        """
        INSERT INTO send_jobs (
            status, endpoint, device_id, device_selector, phone, text, file_path,
            business, worker_id, lease_seconds, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            JOB_STATUS_PENDING,
            endpoint,
            device["id"],
            str(device_selector),
            phone,
            text,
            file_path,
            1 if business else 0,
            worker_id,
            lease_seconds,
            timestamp,
            timestamp,
        ),
    )
    conn.commit()
    return get_send_job(conn, job_id)


def get_send_job(conn, job_id):
    return fetch_one(conn, "SELECT * FROM send_jobs WHERE id = %s", (job_id,))


def list_send_jobs(conn, status=None, limit=DEFAULT_JOB_LIST_LIMIT):
    limit = parse_job_limit(limit)
    if status:
        return fetch_all(
            conn,
            """
            SELECT * FROM send_jobs
            WHERE status = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (status, limit),
        )
    return fetch_all(
        conn,
        """
        SELECT * FROM send_jobs
        ORDER BY id DESC
        LIMIT %s
        """,
        (limit,),
    )


def parse_job_limit(value):
    limit = parse_positive_int(value, "limit")
    return min(limit, MAX_JOB_LIST_LIMIT)


def claim_next_send_job(conn, queue_worker_id):
    queue_worker_id = normalize_worker_id(queue_worker_id)
    current = now_iso()

    conn.start_transaction()
    try:
        jobs = fetch_all(
            conn,
            """
            SELECT * FROM send_jobs
            WHERE status = %s
            ORDER BY id ASC
            FOR UPDATE
            """,
            (JOB_STATUS_PENDING,),
        )

        for job in jobs:
            device = get_device_by_id(conn, job["device_id"], for_update=True)
            if not device:
                mark_claim_failed(
                    conn,
                    job["id"],
                    f"device not found: {job['device_id']}",
                )
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
                (queue_worker_id, locked_until, timestamp, device["id"]),
            )
            execute_write(
                conn,
                """
                UPDATE send_jobs
                SET status = %s, queue_worker_id = %s,
                    device_locked_until = %s, started_at = %s, updated_at = %s
                WHERE id = %s
                """,
                (
                    JOB_STATUS_RUNNING,
                    queue_worker_id,
                    locked_until,
                    timestamp,
                    timestamp,
                    job["id"],
                ),
            )
            conn.commit()

            claimed_job = get_send_job(conn, job["id"])
            claimed_job["device"] = get_device_by_id(conn, device["id"])
            return claimed_job

        conn.commit()
        return None
    except Exception:
        conn.rollback()
        raise


def mark_claim_failed(conn, job_id, error):
    timestamp = now_iso()
    execute_write(
        conn,
        """
        UPDATE send_jobs
        SET status = %s, error = %s, finished_at = %s, updated_at = %s
        WHERE id = %s
        """,
        (JOB_STATUS_FAILED, error, timestamp, timestamp, job_id),
    )


def complete_send_job(conn, job_id):
    timestamp = now_iso()
    execute_write(
        conn,
        """
        UPDATE send_jobs
        SET status = %s, finished_at = %s, updated_at = %s
        WHERE id = %s AND status = %s
        """,
        (JOB_STATUS_SUCCEEDED, timestamp, timestamp, job_id, JOB_STATUS_RUNNING),
    )
    conn.commit()
    return get_send_job(conn, job_id)


def fail_send_job(conn, job_id, error):
    timestamp = now_iso()
    execute_write(
        conn,
        """
        UPDATE send_jobs
        SET status = %s, error = %s, finished_at = %s, updated_at = %s
        WHERE id = %s AND status = %s
        """,
        (
            JOB_STATUS_FAILED,
            str(error),
            timestamp,
            timestamp,
            job_id,
            JOB_STATUS_RUNNING,
        ),
    )
    conn.commit()
    return get_send_job(conn, job_id)
