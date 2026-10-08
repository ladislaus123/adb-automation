class AutomationError(Exception):
    """Base exception for expected automation failures."""


class AdbError(AutomationError):
    """Raised when an ADB command fails."""


class DeviceLockError(AutomationError):
    """Raised when a requested device is locked by another worker."""


class WhatsAppRestrictedError(AutomationError):
    """Raised when WhatsApp reports the account cannot currently send."""


class WhatsAppLoggedOutError(AutomationError):
    """Raised when WhatsApp shows the login/registration screen, i.e. the
    session is gone (the account is logged out on the device)."""


class WhatsAppNotInstalledError(AutomationError):
    """Raised when the requested WhatsApp package is not installed."""


class WhatsAppRecoveryError(AutomationError):
    """Base for failures while driving the ban -> review -> re-login recovery
    flow (requesting an account review or re-registering the number)."""


class ReviewUnavailableError(WhatsAppRecoveryError):
    """Raised when the 'request a review' (pedir analise) action cannot be
    found/performed on the restricted screen."""


class OtpNotReceivedError(WhatsAppRecoveryError):
    """Raised when re-login could not be confirmed: WhatsApp did not auto-fill
    the SMS code and no code could be read back within the wait window."""
