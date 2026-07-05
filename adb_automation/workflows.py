import os

from .adb import ensure_device_ready, wake_and_unlock_device
from .devices import (
    acquire_device_lease,
    device_serial,
    mark_device_seen,
    normalize_worker_id,
    release_device_lease,
)
from .whatsapp import normalize_phone, send_whatsapp


def send_with_device_lease(
    conn, selector, phone, text, file_path, worker_id, lease_seconds, business=False
):
    phone = normalize_phone(phone)
    if not text and not file_path:
        raise ValueError("you must provide either text or a valid file path.")
    if file_path and not os.path.exists(file_path):
        raise ValueError(f"media file not found: {file_path}")

    worker_id = normalize_worker_id(worker_id)
    device = acquire_device_lease(conn, selector, worker_id, lease_seconds)
    serial = device_serial(device)
    print(f"[*] Leased device {device['name']} ({serial}) to worker {worker_id}.")

    try:
        ensure_device_ready(serial)
        wake_and_unlock_device(serial)
        mark_device_seen(conn, device["id"])
        send_whatsapp(serial, phone, text=text, file_path=file_path, business=business)
    finally:
        release_device_lease(conn, device["id"], worker_id, device["locked_until"])
        print(f"[*] Released device {device['name']} ({serial}).")
