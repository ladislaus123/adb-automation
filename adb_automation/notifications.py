import json
import mimetypes
import os
import re
import uuid
from hashlib import sha1
from pathlib import Path

import mysql.connector
import requests

from .config import WEBHOOK_URL_ENV_VAR, parse_positive_int
from .devices import execute_write, fetch_all, fetch_one, now_iso

RECEIVED_MEDIA_DIR = Path(__file__).resolve().parent.parent / "received_media"
DEFAULT_NOTIFICATION_LIST_LIMIT = 50
MAX_NOTIFICATION_LIST_LIMIT = 500
MAX_INGEST_MEDIA_BYTES = 25 * 1024 * 1024
WEBHOOK_TIMEOUT_SECONDS = 5
FALLBACK_DEDUP_BUCKET_MS = 5 * 60 * 1000

PHONE_NUMBER_SENDER_PATTERN = re.compile(r"[\d+\-\s().]+")


def normalize_sender(sender):
    """Strip a phone-number-looking sender down to digits only (e.g. "+55 47 9757-1861"
    -> "554797571861"). Contact names (letters present) are returned unchanged."""
    if not sender:
        return sender

    sender = sender.strip()
    if not PHONE_NUMBER_SENDER_PATTERN.fullmatch(sender):
        return sender

    digits = re.sub(r"\D", "", sender)
    return digits or sender


def parse_notification_limit(value):
    limit = parse_positive_int(value, "limit")
    return min(limit, MAX_NOTIFICATION_LIST_LIMIT)


def stable_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dedup_timestamp_bucket(payload, messages):
    message_timestamps = [
        message.get("timestamp_ms")
        for message in messages
        if isinstance(message, dict) and message.get("timestamp_ms") is not None
    ]
    if message_timestamps:
        return message_timestamps

    post_time_ms = payload.get("post_time_ms")
    try:
        post_time_ms = int(post_time_ms)
    except (TypeError, ValueError):
        return None
    return post_time_ms // FALLBACK_DEDUP_BUCKET_MS


def build_notification_dedup_key(payload, sender, text, media_mime_type=None):
    messages = payload.get("messages")
    messages = messages if isinstance(messages, list) else []
    fingerprint = {
        "device_label": str(payload.get("device_label") or "").strip() or None,
        "package": str(payload.get("package") or "").strip() or None,
        "conversation_title": payload.get("conversation_title")
        if isinstance(payload.get("conversation_title"), str)
        else None,
        "sender": sender,
        "text": text,
        "message_timestamps": dedup_timestamp_bucket(payload, messages),
        "has_media": any(
            bool(message.get("has_media")) for message in messages if isinstance(message, dict)
        ),
        "mime_type": media_mime_type,
    }
    return sha1(stable_json(fingerprint).encode("utf-8")).hexdigest()


def save_media_bytes(media_bytes, mime_type):
    RECEIVED_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    mime_type = str(mime_type or "").split(";", 1)[0].strip()
    suffix = mimetypes.guess_extension(mime_type) or ".bin"
    filename = f"{uuid.uuid4().hex}{suffix}"
    path = RECEIVED_MEDIA_DIR / filename
    path.write_bytes(media_bytes)
    return str(path)


def save_incoming_notification(conn, payload, media_bytes=None, media_mime_type=None):
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages is required and must be a non-empty list.")

    device_label = str(payload.get("device_label") or "").strip() or None
    package = str(payload.get("package") or "").strip() or None
    conversation_title = payload.get("conversation_title")

    first_message = messages[0] if isinstance(messages[0], dict) else {}
    sender = (first_message.get("sender") if isinstance(first_message, dict) else None) or (
        conversation_title if isinstance(conversation_title, str) else None
    )
    sender = normalize_sender(sender)
    text = "\n".join(
        str(message.get("text") or "") for message in messages if isinstance(message, dict)
    ).strip() or None
    dedup_key = build_notification_dedup_key(payload, sender, text, media_mime_type)

    media_path = save_media_bytes(media_bytes, media_mime_type) if media_bytes else None
    timestamp = now_iso()

    try:
        notification_id = execute_write(
            conn,
            """
            INSERT INTO received_notifications (
                device_label, package, sender, text, mime_type, media_path,
                payload_json, dedup_key, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                device_label,
                package,
                sender,
                text,
                media_mime_type,
                media_path,
                json.dumps(payload),
                dedup_key,
                timestamp,
            ),
        )
        conn.commit()
        return get_received_notification(conn, notification_id), True
    except mysql.connector.IntegrityError:
        conn.rollback()
        if media_path and os.path.exists(media_path):
            os.remove(media_path)
        notification = get_received_notification_by_dedup_key(conn, dedup_key)
        if notification:
            return notification, False
        raise


def get_received_notification(conn, notification_id):
    return fetch_one(
        conn, "SELECT * FROM received_notifications WHERE id = %s", (notification_id,)
    )


def get_received_notification_by_dedup_key(conn, dedup_key):
    return fetch_one(
        conn, "SELECT * FROM received_notifications WHERE dedup_key = %s", (dedup_key,)
    )


def list_received_notifications(conn, limit=DEFAULT_NOTIFICATION_LIST_LIMIT):
    limit = parse_notification_limit(limit)
    return fetch_all(
        conn,
        """
        SELECT * FROM received_notifications
        ORDER BY id DESC
        LIMIT %s
        """,
        (limit,),
    )


def build_webhook_event(notification):
    event = {
        "id": notification["id"],
        "device_label": notification["device_label"],
        "package": notification["package"],
        "sender": notification["sender"],
        "text": notification["text"],
        "mime_type": notification["mime_type"],
        "has_media": bool(notification["media_path"]),
        "media_url": f"/api/notifications/media/{notification['id']}"
        if notification["media_path"]
        else None,
        "created_at": notification["created_at"],
    }
    return event


def dispatch_webhook(event):
    webhook_url = os.environ.get(WEBHOOK_URL_ENV_VAR)
    if not webhook_url:
        return False

    try:
        response = requests.post(webhook_url, json=event, timeout=WEBHOOK_TIMEOUT_SECONDS)
        return response.ok
    except requests.RequestException as exc:
        print(f"[WARN] Could not deliver webhook to {webhook_url}: {exc}")
        return False


def whatsapp_package_for_business(business):
    """Match the receiver's business-vs-messenger disambiguation (it keys off a
    'w4b' substring in the package name)."""
    return "com.whatsapp.w4b" if business else "com.whatsapp"


def build_session_status_event(
    device_label, business, reason, job_id=None, phone=None, event="whatsapp_restricted"
):
    """Device-health event (not an inbound message). Carries the device label the
    receiver maps to its session plus the package so it can disambiguate a
    business/non-business pair sharing one device."""
    return {
        "event": event,
        "device_label": device_label,
        "package": whatsapp_package_for_business(bool(business)),
        "business": bool(business),
        "job_id": job_id,
        "phone": phone,
        "reason": reason,
        "detected_at": now_iso(),
    }


def notify_session_restricted(job, reason):
    """Fire-and-forget: tell the receiver a device's WhatsApp is restricted so it
    can mark the session unavailable. Never raises into the caller."""
    try:
        device = job.get("device") or {}
        device_label = device.get("name") if isinstance(device, dict) else None
        if not device_label:
            print("[WARN] Cannot send restricted webhook: job has no device label.")
            return False
        event = build_session_status_event(
            device_label=device_label,
            business=job.get("business"),
            reason=str(reason),
            job_id=job.get("id"),
            phone=job.get("phone"),
        )
        return dispatch_webhook(event)
    except Exception as exc:  # defensive: webhook delivery must never break the worker
        print(f"[WARN] Could not build/deliver restricted webhook: {exc}")
        return False


def notify_session_disconnected(job, reason, *, event):
    """Fire-and-forget: tell the receiver a device's WhatsApp session is gone so it
    can mark the session unavailable (CAIU) and pause its campaigns.

    `event` is 'session_disconnected' (account logged out) or 'device_offline'
    (the device dropped out of adb). Never raises into the caller."""
    try:
        device = job.get("device") or {}
        device_label = device.get("name") if isinstance(device, dict) else None
        if not device_label:
            print("[WARN] Cannot send disconnect webhook: job has no device label.")
            return False
        payload = build_session_status_event(
            device_label=device_label,
            business=job.get("business"),
            reason=str(reason),
            job_id=job.get("id"),
            phone=job.get("phone"),
            event=event,
        )
        return dispatch_webhook(payload)
    except Exception as exc:  # defensive: webhook delivery must never break the worker
        print(f"[WARN] Could not build/deliver disconnect webhook: {exc}")
        return False


RECOVERY_EVENT_STARTED = "session_recovery_started"
RECOVERY_EVENT_RECOVERED = "session_recovered"
RECOVERY_EVENT_FAILED = "session_recovery_failed"


def notify_recovery_event(recovery_job, *, event, reason=None):
    """Fire-and-forget: report progress of the ban -> review -> re-login recovery
    for a device so the receiver can update the session state (e.g. clear
    RESTRINGIDO/CAIU once `session_recovered` arrives). Never raises.

    `recovery_job` is a whatsapp_recovery_jobs row (it carries `device_label`,
    `business`, `phone` and `id` directly)."""
    try:
        device_label = recovery_job.get("device_label")
        if not device_label:
            device = recovery_job.get("device") or {}
            device_label = device.get("name") if isinstance(device, dict) else None
        if not device_label:
            print("[WARN] Cannot send recovery webhook: job has no device label.")
            return False
        payload = build_session_status_event(
            device_label=device_label,
            business=recovery_job.get("business"),
            reason=str(reason) if reason is not None else recovery_job.get("status"),
            job_id=recovery_job.get("id"),
            phone=recovery_job.get("phone"),
            event=event,
        )
        return dispatch_webhook(payload)
    except Exception as exc:  # defensive: delivery must never break the worker
        print(f"[WARN] Could not build/deliver recovery webhook: {exc}")
        return False
