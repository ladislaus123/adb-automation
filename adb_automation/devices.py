import os
import socket
from datetime import datetime, timedelta, timezone

import mysql.connector

from .config import parse_positive_int
from .errors import DeviceLockError

ADB_TRANSPORT_WIFI = "wifi"
ADB_TRANSPORT_USB = "usb"
ADB_TRANSPORTS = (ADB_TRANSPORT_WIFI, ADB_TRANSPORT_USB)


def utcnow():
    return datetime.now(timezone.utc)


def to_iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def now_iso():
    return to_iso(utcnow())


def normalize_worker_id(worker_id=None):
    if worker_id:
        return worker_id
    return f"{socket.gethostname()}-{os.getpid()}"


def normalize_adb_transport(adb_transport=None):
    if adb_transport is None:
        return ADB_TRANSPORT_WIFI
    if not isinstance(adb_transport, str):
        raise ValueError("adb_transport must be wifi or usb.")
    transport = adb_transport.strip().lower()
    if transport not in ADB_TRANSPORTS:
        raise ValueError("adb_transport must be wifi or usb.")
    return transport


def device_adb_transport(device):
    return normalize_adb_transport(device.get("adb_transport") or ADB_TRANSPORT_WIFI)


def device_serial(device):
    if device_adb_transport(device) == ADB_TRANSPORT_USB:
        return device["usb_serial"]
    return f"{device['ip']}:{device['port']}"


def fetch_one(conn, query, params=()):
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(query, params)
        return cursor.fetchone()
    finally:
        cursor.close()


def fetch_all(conn, query, params=()):
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        cursor.close()


def execute_write(conn, query, params=()):
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        lastrowid = cursor.lastrowid
    finally:
        cursor.close()
    return lastrowid


def add_device(
    conn,
    name,
    ip=None,
    port=None,
    adb_transport=ADB_TRANSPORT_WIFI,
    usb_serial=None,
):
    name, ip, port, adb_transport, usb_serial = validate_device_fields(
        name,
        ip,
        port,
        adb_transport,
        usb_serial,
    )
    timestamp = now_iso()
    try:
        device_id = execute_write(
            conn,
            """
            INSERT INTO devices (
                name, ip, port, adb_transport, usb_serial, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (name, ip, port, adb_transport, usb_serial, timestamp, timestamp),
        )
        conn.commit()
    except mysql.connector.IntegrityError as exc:
        conn.rollback()
        raise ValueError(
            "device name, IP/port, or USB serial already exists in the database."
        ) from exc
    return get_device_by_id(conn, device_id)


def validate_device_fields(
    name,
    ip=None,
    port=None,
    adb_transport=ADB_TRANSPORT_WIFI,
    usb_serial=None,
):
    name = (name or "").strip()
    if not name:
        raise ValueError("device name is required.")

    adb_transport = normalize_adb_transport(adb_transport)
    if adb_transport == ADB_TRANSPORT_USB:
        usb_serial = (usb_serial or "").strip()
        if not usb_serial:
            raise ValueError("usb_serial is required for USB devices.")
        return name, None, None, adb_transport, usb_serial

    ip = (ip or "").strip()
    port = parse_positive_int(port, "port")
    if port > 65535:
        raise ValueError("port must be between 1 and 65535.")
    if not ip:
        raise ValueError("device IP is required.")
    return name, ip, port, adb_transport, None


def update_device(
    conn,
    device_id,
    name=None,
    ip=None,
    port=None,
    adb_transport=None,
    usb_serial=None,
):
    conn.start_transaction()
    try:
        device = get_device_by_id(conn, device_id, for_update=True)
        if not device:
            raise ValueError("device not found.")

        if lock_is_active(device):
            raise DeviceLockError(
                "device "
                f"{device['name']} is locked by {device['worker_id']} "
                f"until {device['locked_until']}."
            )

        next_transport = normalize_adb_transport(
            device.get("adb_transport") if adb_transport is None else adb_transport
        )
        next_name = device["name"] if name is None else name
        if next_transport == ADB_TRANSPORT_USB:
            next_ip = None
            next_port = None
            next_usb_serial = (
                device.get("usb_serial") if usb_serial is None else usb_serial
            )
        else:
            next_ip = device.get("ip") if ip is None else ip
            next_port = device.get("port") if port is None else port
            next_usb_serial = None

        (
            next_name,
            next_ip,
            next_port,
            next_transport,
            next_usb_serial,
        ) = validate_device_fields(
            next_name,
            next_ip,
            next_port,
            next_transport,
            next_usb_serial,
        )

        duplicate_name = find_device_by_name(conn, next_name)
        if duplicate_name and duplicate_name["id"] != device["id"]:
            raise ValueError("device name already exists.")

        if next_transport == ADB_TRANSPORT_USB:
            duplicate_usb = find_device_by_usb_serial(conn, next_usb_serial)
            if duplicate_usb and duplicate_usb["id"] != device["id"]:
                raise ValueError("device USB serial already exists.")
        else:
            duplicate_endpoint = find_device_by_endpoint(conn, next_ip, next_port)
            if duplicate_endpoint and duplicate_endpoint["id"] != device["id"]:
                raise ValueError("device IP/port already exists.")

        timestamp = now_iso()
        execute_write(
            conn,
            """
            UPDATE devices
            SET name = %s, ip = %s, port = %s,
                adb_transport = %s, usb_serial = %s, updated_at = %s
            WHERE id = %s
            """,
            (
                next_name,
                next_ip,
                next_port,
                next_transport,
                next_usb_serial,
                timestamp,
                device["id"],
            ),
        )
        conn.commit()
    except mysql.connector.IntegrityError as exc:
        conn.rollback()
        raise ValueError(
            "device name, IP/port, or USB serial already exists in the database."
        ) from exc
    except Exception:
        conn.rollback()
        raise

    return get_device_by_id(conn, device["id"])


def get_device_by_id(conn, device_id, for_update=False):
    suffix = " FOR UPDATE" if for_update else ""
    return fetch_one(
        conn, f"SELECT * FROM devices WHERE id = %s{suffix}", (device_id,)
    )


def find_device_by_name(conn, name, for_update=False):
    name = str(name or "").strip()
    if not name:
        raise ValueError("device name is required.")
    suffix = " FOR UPDATE" if for_update else ""
    return fetch_one(
        conn, f"SELECT * FROM devices WHERE name = %s{suffix}", (name,)
    )


def find_device(conn, selector, for_update=False):
    selector = str(selector).strip()
    if not selector:
        raise ValueError("device selector is required.")
    if selector.isdigit():
        row = get_device_by_id(conn, int(selector), for_update=for_update)
        if row:
            return row
    return find_device_by_name(conn, selector, for_update=for_update)


def find_device_by_endpoint(conn, ip, port):
    ip = (ip or "").strip()
    port = parse_positive_int(port, "port")
    if port > 65535:
        raise ValueError("port must be between 1 and 65535.")
    if not ip:
        raise ValueError("device IP is required.")
    return fetch_one(
        conn, "SELECT * FROM devices WHERE ip = %s AND port = %s", (ip, port)
    )


def find_device_by_usb_serial(conn, usb_serial):
    usb_serial = (usb_serial or "").strip()
    if not usb_serial:
        raise ValueError("usb_serial is required.")
    return fetch_one(
        conn,
        "SELECT * FROM devices WHERE usb_serial = %s",
        (usb_serial,),
    )


def list_devices(conn):
    return fetch_all(conn, "SELECT * FROM devices ORDER BY id ASC")


def lock_is_active(device, current_iso=None):
    locked_until = device["locked_until"]
    if not locked_until:
        return False
    return locked_until > (current_iso or now_iso())


def acquire_device_lease(conn, selector, worker_id, lease_seconds):
    worker_id = normalize_worker_id(worker_id)
    lease_seconds = parse_positive_int(lease_seconds, "lease seconds")
    current = now_iso()
    until = to_iso(utcnow() + timedelta(seconds=lease_seconds))

    conn.start_transaction()
    try:
        device = find_device(conn, selector, for_update=True)
        if not device:
            raise ValueError(f"device not found: {selector}")

        if lock_is_active(device, current):
            raise DeviceLockError(
                "device "
                f"{device['name']} is locked by {device['worker_id']} "
                f"until {device['locked_until']}."
            )

        execute_write(
            conn,
            """
            UPDATE devices
            SET worker_id = %s, locked_until = %s, updated_at = %s
            WHERE id = %s
            """,
            (worker_id, until, current, device["id"]),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return get_device_by_id(conn, device["id"])


def release_device_lease(conn, device_id, worker_id, locked_until):
    timestamp = now_iso()
    execute_write(
        conn,
        """
        UPDATE devices
        SET worker_id = NULL, locked_until = NULL, updated_at = %s
        WHERE id = %s AND worker_id = %s AND locked_until = %s
        """,
        (timestamp, device_id, worker_id, locked_until),
    )
    conn.commit()


def unlock_device(conn, selector):
    device = find_device(conn, selector)
    if not device:
        raise ValueError(f"device not found: {selector}")
    timestamp = now_iso()
    execute_write(
        conn,
        """
        UPDATE devices
        SET worker_id = NULL, locked_until = NULL, updated_at = %s
        WHERE id = %s
        """,
        (timestamp, device["id"]),
    )
    conn.commit()
    return get_device_by_id(conn, device["id"])


def mark_device_seen(conn, device_id):
    timestamp = now_iso()
    execute_write(
        conn,
        "UPDATE devices SET last_seen_at = %s, updated_at = %s WHERE id = %s",
        (timestamp, timestamp, device_id),
    )
    conn.commit()


def format_devices_table(devices):
    headers = ("ID", "Name", "Transport", "Serial", "Status", "Worker", "Last seen")
    rows = []
    current = now_iso()
    for device in devices:
        transport = device_adb_transport(device)
        serial = device_serial(device)
        if lock_is_active(device, current):
            status = f"locked until {device['locked_until']}"
        else:
            status = "available"
        rows.append(
            (
                str(device["id"]),
                device["name"],
                transport,
                serial,
                status,
                device["worker_id"] or "-",
                device["last_seen_at"] or "-",
            )
        )

    widths = []
    for index, header in enumerate(headers):
        column_width = len(header)
        if rows:
            column_width = max(column_width, *(len(row[index]) for row in rows))
        widths.append(column_width)
    lines = [
        "  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)),
        "  ".join("-" * width for width in widths),
    ]
    lines.extend(
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in rows
    )
    return "\n".join(lines)
