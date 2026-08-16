class AutomationError(Exception):
    """Base exception for expected automation failures."""


class AdbError(AutomationError):
    """Raised when an ADB command fails."""


class DeviceLockError(AutomationError):
    """Raised when a requested device is locked by another worker."""


class WhatsAppRestrictedError(AutomationError):
    """Raised when WhatsApp reports the account cannot currently send."""


class WhatsAppNotInstalledError(AutomationError):
    """Raised when the requested WhatsApp package is not installed."""
