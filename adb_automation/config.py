import os
from pathlib import Path

WHATSAPP_MESSENGER_PACKAGE = "com.whatsapp"
WHATSAPP_BUSINESS_PACKAGE = "com.whatsapp.w4b"
WHATSAPP_PACKAGES = (WHATSAPP_MESSENGER_PACKAGE, WHATSAPP_BUSINESS_PACKAGE)
STREAM_EXTRA = "android.intent.extra.STREAM"
DEFAULT_DB_HOST = "localhost"
DEFAULT_DB_PORT = 3306
DEFAULT_DB_USER = "root"
DEFAULT_DB_NAME = "adb_automation"
DEFAULT_LEASE_SECONDS = 600
DEFAULT_API_HOST = "0.0.0.0"
DEFAULT_API_PORT = 5000
DEFAULT_APPIUM_SERVER = "http://127.0.0.1:4723"
DEFAULT_QUEUE_POLL_SECONDS = 1
DB_HOST_ENV_VAR = "ADB_AUTOMATION_DB_HOST"
DB_PORT_ENV_VAR = "ADB_AUTOMATION_DB_PORT"
DB_USER_ENV_VAR = "ADB_AUTOMATION_DB_USER"
DB_PASSWORD_ENV_VAR = "ADB_AUTOMATION_DB_PASSWORD"
DB_NAME_ENV_VAR = "ADB_AUTOMATION_DB_NAME"
DB_ENV_VAR = "ADB_AUTOMATION_DB"
LEASE_ENV_VAR = "ADB_AUTOMATION_LEASE_SECONDS"
API_KEY_ENV_VAR = "ADB_AUTOMATION_API_KEY"
API_HOST_ENV_VAR = "ADB_AUTOMATION_API_HOST"
API_PORT_ENV_VAR = "ADB_AUTOMATION_API_PORT"
APPIUM_SERVER_ENV_VAR = "ADB_AUTOMATION_APPIUM_SERVER"
QUEUE_WORKERS_ENV_VAR = "ADB_AUTOMATION_QUEUE_WORKERS"
QUEUE_POLL_SECONDS_ENV_VAR = "ADB_AUTOMATION_QUEUE_POLL_SECONDS"
STOCHASTIC_ENABLED_ENV_VAR = "STOCHASTIC_ENABLED"


def load_env_file(path=".env"):
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ("'", '"')
        ):
            value = value[1:-1]

        os.environ[key] = value


def parse_positive_int(value, name):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer.")
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return parsed


def env_int(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return parse_positive_int(value, name)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None or not str(value).strip():
        return default

    lowered = str(value).strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be a boolean.")


load_env_file()
