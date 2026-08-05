import os
import re

import mysql.connector

from .config import (
    DB_ENV_VAR,
    DB_HOST_ENV_VAR,
    DB_NAME_ENV_VAR,
    DB_PASSWORD_ENV_VAR,
    DB_PORT_ENV_VAR,
    DB_USER_ENV_VAR,
    DEFAULT_DB_HOST,
    DEFAULT_DB_NAME,
    DEFAULT_DB_PORT,
    DEFAULT_DB_USER,
    parse_positive_int,
)

DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


def database_settings(database=None, host=None, port=None, user=None, password=None):
    database_name = (
        database
        or os.environ.get(DB_NAME_ENV_VAR)
        or os.environ.get(DB_ENV_VAR)
        or DEFAULT_DB_NAME
    )
    return {
        "database": validate_database_name(database_name),
        "host": host or os.environ.get(DB_HOST_ENV_VAR, DEFAULT_DB_HOST),
        "port": parse_positive_int(
            port or os.environ.get(DB_PORT_ENV_VAR, DEFAULT_DB_PORT), "database port"
        ),
        "user": user or os.environ.get(DB_USER_ENV_VAR, DEFAULT_DB_USER),
        "password": (
            password
            if password is not None
            else os.environ.get(DB_PASSWORD_ENV_VAR, "")
        ),
    }


def validate_database_name(database):
    database = (database or "").strip()
    if not database:
        raise ValueError("database name is required.")
    if not DATABASE_NAME_PATTERN.match(database):
        raise ValueError("database name may only contain letters, numbers, and _.")
    return database


def open_database(database=None, host=None, port=None, user=None, password=None):
    settings = database_settings(database, host, port, user, password)
    admin_conn = mysql.connector.connect(
        host=settings["host"],
        port=settings["port"],
        user=settings["user"],
        password=settings["password"],
        auth_plugin="mysql_native_password",
        use_pure=True,
        autocommit=True,
    )
    admin_cursor = admin_conn.cursor()
    try:
        admin_cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{settings['database']}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    finally:
        admin_cursor.close()
        admin_conn.close()

    conn = mysql.connector.connect(
        host=settings["host"],
        port=settings["port"],
        user=settings["user"],
        password=settings["password"],
        database=settings["database"],
        auth_plugin="mysql_native_password",
        use_pure=True,
        autocommit=False,
    )
    return conn


def _row_value(row, key, index):
    if isinstance(row, dict):
        return row.get(key)
    if row is None:
        return None
    try:
        return row[index]
    except (IndexError, TypeError):
        return None


def _device_column(cursor, column):
    cursor.execute("SHOW COLUMNS FROM devices LIKE %s", (column,))
    return cursor.fetchone()


def _device_column_exists(cursor, column):
    return _device_column(cursor, column) is not None


def _device_column_is_not_nullable(cursor, column):
    row = _device_column(cursor, column)
    return str(_row_value(row, "Null", 2) or "").upper() == "NO"


def _device_index_exists(cursor, index_name):
    cursor.execute("SHOW INDEX FROM devices WHERE Key_name = %s", (index_name,))
    return cursor.fetchone() is not None


def migrate_devices_schema(cursor):
    if not _device_column_exists(cursor, "adb_transport"):
        cursor.execute(
            """
            ALTER TABLE devices
            ADD COLUMN adb_transport VARCHAR(16) NOT NULL DEFAULT 'wifi' AFTER port
            """
        )

    if not _device_column_exists(cursor, "usb_serial"):
        cursor.execute(
            """
            ALTER TABLE devices
            ADD COLUMN usb_serial VARCHAR(255) NULL AFTER adb_transport
            """
        )

    if _device_column_is_not_nullable(cursor, "ip"):
        cursor.execute("ALTER TABLE devices MODIFY ip VARCHAR(255) NULL")
    if _device_column_is_not_nullable(cursor, "port"):
        cursor.execute("ALTER TABLE devices MODIFY port INTEGER NULL")

    if not _device_index_exists(cursor, "uq_devices_usb_serial"):
        cursor.execute(
            """
            ALTER TABLE devices
            ADD UNIQUE KEY uq_devices_usb_serial (usb_serial)
            """
        )


def init_database(conn):
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                name VARCHAR(255) NOT NULL,
                ip VARCHAR(255),
                port INTEGER,
                adb_transport VARCHAR(16) NOT NULL DEFAULT 'wifi',
                usb_serial VARCHAR(255),
                worker_id VARCHAR(255),
                locked_until VARCHAR(32),
                last_seen_at VARCHAR(32),
                created_at VARCHAR(32) NOT NULL,
                updated_at VARCHAR(32) NOT NULL,
                PRIMARY KEY (id),
                UNIQUE KEY uq_devices_name (name),
                UNIQUE KEY uq_devices_endpoint (ip, port),
                UNIQUE KEY uq_devices_usb_serial (usb_serial),
                KEY idx_devices_locked_until (locked_until)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        migrate_devices_schema(cursor)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS send_jobs (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                status VARCHAR(32) NOT NULL,
                endpoint VARCHAR(64) NOT NULL,
                device_id BIGINT UNSIGNED NOT NULL,
                device_selector VARCHAR(255) NOT NULL,
                phone VARCHAR(64) NOT NULL,
                text TEXT,
                file_path TEXT,
                business TINYINT(1) NOT NULL DEFAULT 0,
                worker_id VARCHAR(255),
                lease_seconds INTEGER NOT NULL,
                queue_worker_id VARCHAR(255),
                device_locked_until VARCHAR(32),
                error TEXT,
                created_at VARCHAR(32) NOT NULL,
                updated_at VARCHAR(32) NOT NULL,
                started_at VARCHAR(32),
                finished_at VARCHAR(32),
                PRIMARY KEY (id),
                KEY idx_send_jobs_status_id (status, id),
                KEY idx_send_jobs_device_status (device_id, status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        conn.commit()
    finally:
        cursor.close()
