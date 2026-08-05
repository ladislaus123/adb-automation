import unittest
from unittest.mock import Mock, patch

from adb_automation import db


class DatabaseConnectionTests(unittest.TestCase):
    def test_open_database_creates_database_and_connects_to_it(self):
        admin_conn = Mock()
        app_conn = Mock()
        admin_cursor = Mock()
        admin_conn.cursor.return_value = admin_cursor

        with patch(
            "adb_automation.db.mysql.connector.connect",
            side_effect=[admin_conn, app_conn],
        ) as connect:
            result = db.open_database(
                database="adb_automation",
                host="localhost",
                port=3306,
                user="root",
                password="secret",
            )

        self.assertIs(result, app_conn)
        self.assertEqual(connect.call_count, 2)
        connect.assert_any_call(
            host="localhost",
            port=3306,
            user="root",
            password="secret",
            auth_plugin="mysql_native_password",
            use_pure=True,
            autocommit=True,
        )
        connect.assert_any_call(
            host="localhost",
            port=3306,
            user="root",
            password="secret",
            database="adb_automation",
            auth_plugin="mysql_native_password",
            use_pure=True,
            autocommit=False,
        )
        admin_cursor.execute.assert_called_once_with(
            "CREATE DATABASE IF NOT EXISTS `adb_automation` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        admin_cursor.close.assert_called_once()
        admin_conn.close.assert_called_once()

    def test_database_name_rejects_unsafe_identifiers(self):
        with self.assertRaises(ValueError):
            db.validate_database_name("adb-automation;DROP")


class FakeSchemaCursor:
    def __init__(self):
        self.columns = {
            "ip": ("ip", "varchar(255)", "NO"),
            "port": ("port", "int", "NO"),
        }
        self.indexes = set()
        self.result = None

    def execute(self, query, params=None):
        params = params or ()
        normalized = " ".join(query.lower().split())
        if normalized.startswith("show columns from devices like"):
            self.result = self.columns.get(params[0])
            return
        if normalized.startswith("show index from devices where key_name"):
            self.result = {"Key_name": params[0]} if params[0] in self.indexes else None
            return
        if "add column adb_transport" in normalized:
            self.columns["adb_transport"] = ("adb_transport", "varchar(16)", "NO")
            return
        if "add column usb_serial" in normalized:
            self.columns["usb_serial"] = ("usb_serial", "varchar(255)", "YES")
            return
        if "modify ip" in normalized:
            self.columns["ip"] = ("ip", "varchar(255)", "YES")
            return
        if "modify port" in normalized:
            self.columns["port"] = ("port", "int", "YES")
            return
        if "add unique key uq_devices_usb_serial" in normalized:
            self.indexes.add("uq_devices_usb_serial")
            return
        raise AssertionError(f"unexpected query: {query}")

    def fetchone(self):
        return self.result


class DatabaseMigrationTests(unittest.TestCase):
    def test_migrate_devices_schema_adds_usb_columns_and_nullable_wifi_fields(self):
        cursor = FakeSchemaCursor()

        db.migrate_devices_schema(cursor)

        self.assertEqual(cursor.columns["adb_transport"][2], "NO")
        self.assertEqual(cursor.columns["usb_serial"][2], "YES")
        self.assertEqual(cursor.columns["ip"][2], "YES")
        self.assertEqual(cursor.columns["port"][2], "YES")
        self.assertIn("uq_devices_usb_serial", cursor.indexes)


if __name__ == "__main__":
    unittest.main()
