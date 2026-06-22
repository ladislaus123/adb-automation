class AutomationError(Exception):
    """Base exception for expected automation failures."""


class AdbError(AutomationError):
    """Raised when an ADB command fails."""


class DeviceLockError(AutomationError):
    """Raised when a requested device is locked by another worker."""
