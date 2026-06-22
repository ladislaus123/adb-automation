import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adb_automation import config


class EnvFileTests(unittest.TestCase):
    def test_load_env_file_reads_missing_values_and_strips_quotes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "ADB_AUTOMATION_DB_PASSWORD='secret!*'\n"
                "ADB_AUTOMATION_DB_HOST=localhost\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config.load_env_file(env_path)

                self.assertEqual(os.environ["ADB_AUTOMATION_DB_PASSWORD"], "secret!*")
                self.assertEqual(os.environ["ADB_AUTOMATION_DB_HOST"], "localhost")

    def test_load_env_file_does_not_override_existing_environment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "ADB_AUTOMATION_DB_PASSWORD=from-file\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ, {"ADB_AUTOMATION_DB_PASSWORD": "from-env"}, clear=True
            ):
                config.load_env_file(env_path)

                self.assertEqual(os.environ["ADB_AUTOMATION_DB_PASSWORD"], "from-env")


if __name__ == "__main__":
    unittest.main()
