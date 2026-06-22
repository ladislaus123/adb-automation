import argparse
import os
import sys

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
    DEFAULT_LEASE_SECONDS,
    LEASE_ENV_VAR,
    env_int,
)
from .db import init_database, open_database
from .devices import (
    add_device,
    device_serial,
    format_devices_table,
    list_devices,
    unlock_device,
)
from .errors import AutomationError
from .workflows import send_with_device_lease


def build_parser():
    parser = argparse.ArgumentParser(
        description="WhatsApp ADB automation with MariaDB-backed device leasing."
    )
    parser.add_argument(
        "--database",
        default=os.environ.get(DB_NAME_ENV_VAR)
        or os.environ.get(DB_ENV_VAR, DEFAULT_DB_NAME),
        help=(
            "MariaDB database name. Defaults to "
            f"${DB_NAME_ENV_VAR}, ${DB_ENV_VAR}, or {DEFAULT_DB_NAME}."
        ),
    )
    parser.add_argument(
        "--db-host",
        default=os.environ.get(DB_HOST_ENV_VAR, DEFAULT_DB_HOST),
        help=f"MariaDB host. Defaults to ${DB_HOST_ENV_VAR} or {DEFAULT_DB_HOST}.",
    )
    parser.add_argument(
        "--db-port",
        type=int,
        default=env_int(DB_PORT_ENV_VAR, DEFAULT_DB_PORT),
        help=f"MariaDB port. Defaults to ${DB_PORT_ENV_VAR} or {DEFAULT_DB_PORT}.",
    )
    parser.add_argument(
        "--db-user",
        default=os.environ.get(DB_USER_ENV_VAR, DEFAULT_DB_USER),
        help=f"MariaDB user. Defaults to ${DB_USER_ENV_VAR} or {DEFAULT_DB_USER}.",
    )
    parser.add_argument(
        "--db-password",
        default=os.environ.get(DB_PASSWORD_ENV_VAR),
        help=f"MariaDB password. Defaults to ${DB_PASSWORD_ENV_VAR}.",
    )

    subparsers = parser.add_subparsers(dest="command")

    send_parser = subparsers.add_parser("send", help="send WhatsApp text/media")
    send_parser.add_argument("--device", required=True, help="device id or name")
    send_parser.add_argument(
        "--phone", required=True, help="phone number with country code"
    )
    send_parser.add_argument("--text", help="message text")
    send_parser.add_argument("--file", dest="file_path", help="local image/video path")
    send_parser.add_argument(
        "-business",
        "--business",
        action="store_true",
        help="use WhatsApp Business instead of regular WhatsApp",
    )
    send_parser.add_argument("--worker-id", help="worker identity for the lease")
    send_parser.add_argument(
        "--lease-seconds",
        type=int,
        default=env_int(LEASE_ENV_VAR, DEFAULT_LEASE_SECONDS),
        help=(
            "device lease TTL in seconds. Defaults to "
            f"${LEASE_ENV_VAR} or {DEFAULT_LEASE_SECONDS}."
        ),
    )

    devices_parser = subparsers.add_parser("devices", help="manage device records")
    device_subparsers = devices_parser.add_subparsers(dest="devices_command")

    add_parser = device_subparsers.add_parser("add", help="add a Wi-Fi ADB device")
    add_parser.add_argument("--name", required=True, help="stable device name")
    add_parser.add_argument("--ip", required=True, help="device Wi-Fi IP")
    add_parser.add_argument("--port", required=True, type=int, help="device ADB port")

    device_subparsers.add_parser("list", help="list known devices")

    unlock_parser = device_subparsers.add_parser("unlock", help="clear a device lease")
    unlock_parser.add_argument("--device", required=True, help="device id or name")

    return parser


def handle_devices_command(conn, args):
    if args.devices_command == "add":
        device = add_device(conn, args.name, args.ip, args.port)
        print(
            f"[+] Added device {device['id']} {device['name']} "
            f"({device_serial(device)})."
        )
        return 0

    if args.devices_command == "list":
        print(format_devices_table(list_devices(conn)))
        return 0

    if args.devices_command == "unlock":
        device = unlock_device(conn, args.device)
        print(f"[+] Unlocked device {device['name']} ({device_serial(device)}).")
        return 0

    raise ValueError("missing devices command. Use add, list, or unlock.")


def main(argv=None):
    try:
        parser = build_parser()
    except ValueError as exc:
        print(f"[-] {exc}", file=sys.stderr)
        return 1

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    conn = None
    try:
        conn = open_database(
            database=args.database,
            host=args.db_host,
            port=args.db_port,
            user=args.db_user,
            password=args.db_password,
        )
        init_database(conn)

        if args.command == "devices":
            return handle_devices_command(conn, args)

        if args.command == "send":
            send_with_device_lease(
                conn,
                args.device,
                args.phone,
                args.text,
                args.file_path,
                args.worker_id,
                args.lease_seconds,
                business=args.business,
            )
            return 0

        raise ValueError(f"unknown command: {args.command}")
    except (AutomationError, ValueError, mysql.connector.Error) as exc:
        print(f"[-] {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()
