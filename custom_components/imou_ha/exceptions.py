"""Custom exceptions for the Imou integration."""


class ImouError(Exception):
    """Base exception for all Imou errors."""


class ImouAuthError(ImouError):
    """Authentication failed (TK1002, TK1003, InvalidAppIdOrSecret)."""


class ImouDeviceSleepingError(ImouError):
    """Device is sleeping (DV1030)."""


class ImouLicenseError(ImouError):
    """Account device limit reached (FL1001)."""


class ImouRateLimitError(ImouError):
    """Daily API rate limit exceeded (OP1011)."""


class ImouDeviceOfflineError(ImouError):
    """Device is offline (DV1007)."""
