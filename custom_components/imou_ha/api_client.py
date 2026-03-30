"""API client wrapper — sole pyimouapi boundary (ADR-1, D-16)."""

from __future__ import annotations

import logging
from typing import Any

from pyimouapi import ImouOpenApiClient
from pyimouapi.device import ImouDeviceManager
from pyimouapi.exceptions import (
    ConnectFailedException,
    ImouException,
    InvalidAppIdOrSecretException,
    RequestFailedException,
)

from .const import (
    CAPABILITY_DORMANT,
    ERROR_CODE_DEVICE_OFFLINE,
    ERROR_CODE_DEVICE_SLEEPING,
    ERROR_CODE_LICENSE_LIMIT,
    ERROR_CODE_RATE_LIMIT,
)
from .exceptions import (
    ImouAuthError,
    ImouDeviceOfflineError,
    ImouDeviceSleepingError,
    ImouError,
    ImouLicenseError,
    ImouRateLimitError,
)
from .models import DeviceStatus, ImouDeviceData

_LOGGER = logging.getLogger(__name__)


class ImouApiClient:
    """Sole boundary to the pyimouapi library.

    All pyimouapi exceptions are caught here and re-raised as ImouError
    subtypes. No pyimouapi types leak out of this class.
    """

    def __init__(self, app_id: str, app_secret: str, api_url: str) -> None:
        """Initialise the API client with Imou cloud credentials."""
        self._client = ImouOpenApiClient(app_id, app_secret, api_url)
        self._device_manager: ImouDeviceManager | None = None

    async def async_validate_credentials(self) -> None:
        """Validate credentials by obtaining an access token.

        Raises:
            ImouAuthError: when AppId/AppSecret are invalid.
            ImouError: for any other connection or API failure.

        """
        try:
            await self._client.async_get_token()
        except InvalidAppIdOrSecretException as err:
            _LOGGER.debug(
                "Credential validation failed — invalid AppId/AppSecret: %s", err,
            )
            raise ImouAuthError(str(err)) from err
        except ConnectFailedException as err:
            _LOGGER.debug("Credential validation failed — cannot connect: %s", err)
            msg = f"Cannot connect to Imou cloud: {err}"
            raise ImouError(msg) from err
        except ImouException as err:
            _LOGGER.debug("Credential validation failed — API error: %s", err)
            raise ImouError(str(err)) from err

    async def async_get_devices(self) -> dict[str, ImouDeviceData]:  # noqa: C901
        """Discover and return all devices bound to this account.

        Returns:
            dict keyed by device serial (device_id) to ImouDeviceData.

        Raises:
            ImouAuthError: when authentication fails.
            ImouLicenseError: when account device limit is reached (FL1001).
            ImouRateLimitError: when daily API rate limit is exceeded (OP1011).
            ImouDeviceOfflineError: when a device is reported offline (DV1007).
            ImouDeviceSleepingError: when a device is sleeping (DV1030).
            ImouError: for any other failure.

        """
        try:
            if self._device_manager is None:
                self._device_manager = ImouDeviceManager(self._client)
            raw_devices = await self._device_manager.async_get_devices()
        except InvalidAppIdOrSecretException as err:
            _LOGGER.debug("async_get_devices — invalid credentials: %s", err)
            raise ImouAuthError(str(err)) from err
        except ConnectFailedException as err:
            _LOGGER.debug("async_get_devices — connection failure: %s", err)
            msg = f"Cannot connect to Imou cloud: {err}"
            raise ImouError(msg) from err
        except RequestFailedException as err:
            raise self._translate_exception(err) from err
        except ImouException as err:
            _LOGGER.debug("async_get_devices — API error: %s", err)
            raise ImouError(str(err)) from err

        devices: dict[str, ImouDeviceData] = {}
        for device in raw_devices:
            serial = device.device_id

            # Parse capabilities — device_ability is a comma-separated string
            raw_ability: Any = device.device_ability
            if isinstance(raw_ability, list):
                capabilities = set(raw_ability)
            elif isinstance(raw_ability, str) and raw_ability not in ("", "unknown"):
                capabilities = {cap.strip() for cap in raw_ability.split(",")}
            else:
                capabilities = set()

            # Map device_status string to DeviceStatus enum (per pyimouapi values)
            raw_status = str(device.device_status)
            if raw_status == "1":
                status = DeviceStatus.ACTIVE
            elif raw_status == "4" or CAPABILITY_DORMANT in capabilities:
                status = DeviceStatus.SLEEPING
            else:
                status = DeviceStatus.OFFLINE

            devices[serial] = ImouDeviceData(
                serial=serial,
                name=device.device_name,
                model=device.device_model,
                firmware=device.device_version,
                status=status,
                capabilities=capabilities,
            )

        return devices

    def _translate_exception(self, err: RequestFailedException) -> ImouError:
        """Translate a RequestFailedException to a domain-specific ImouError.

        The message format from pyimouapi is "ERROR_CODE:description".
        """
        message = err.message if hasattr(err, "message") else str(err)
        _LOGGER.debug("Translating RequestFailedException: %s", message)

        # Extract error code from "CODE:description" format
        error_code = message.split(":")[0] if ":" in message else message

        if error_code == ERROR_CODE_LICENSE_LIMIT:
            return ImouLicenseError(message)
        if error_code == ERROR_CODE_RATE_LIMIT:
            return ImouRateLimitError(message)
        if error_code == ERROR_CODE_DEVICE_OFFLINE:
            return ImouDeviceOfflineError(message)
        if error_code == ERROR_CODE_DEVICE_SLEEPING:
            return ImouDeviceSleepingError(message)
        return ImouError(message)
