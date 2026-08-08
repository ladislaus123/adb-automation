import json
import mimetypes
import os
import uuid
from pathlib import Path

import requests

from .config import WEBHOOK_URL_ENV_VAR, parse_positive_int
from .devices import execute_write, fetch_all, fetch_one, now_iso

RECEIVED_MEDIA_DIR = Path(__file__).resolve().parent.parent / "received_media"
DEFAULT_NOTIFICATION_LIST_LIMIT = 50
MAX_NOTIFICATION_LIST_LIMIT = 500
MAX_INGEST_MEDIA_BYTES = 25 * 1024 * 1024
WEBHOOK_TIMEOUT_SECONDS = 5


def parse_notification_limit(value):
    limit = parse_positive_int(value, "limit")
    return min(limit, MAX_NOTIFICATION_LIST_LIMIT)


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
    text = "\n".join(
        str(message.get("text") or "") for message in messages if isinstance(message, dict)
    ).strip() or None

    media_path = save_media_bytes(media_bytes, media_mime_type) if media_bytes else None
    timestamp = now_iso()

    notification_id = execute_write(
        conn,
        """
        INSERT INTO received_notifications (
            device_label, package, sender, text, mime_type, media_path,
            payload_json, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            device_label,
            package,
            sender,
            text,
            media_mime_type,
            media_path,
            json.dumps(payload),
            timestamp,
        ),
    )
    conn.commit()
    return get_received_notification(conn, notification_id)


def get_received_notification(conn, notification_id):
    return fetch_one(
        conn, "SELECT * FROM received_notifications WHERE id = %s", (notification_id,)
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
