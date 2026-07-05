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


if __name__ == "__main__":
    unittest.main()
