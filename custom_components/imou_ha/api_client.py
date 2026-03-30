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

    async def async_get_device_online_status(self, device_id: str) -> DeviceStatus:
        """Get device online status via /openapi/deviceOnline (ADR-1 boundary).

        Maps pyimouapi response codes to DeviceStatus:
          "1" -> ACTIVE, "4" -> SLEEPING, else -> OFFLINE.

        For IPC single-channel cameras, status is in channels[0].onLine.
        For IoT devices (no channels list), status is in top-level onLine.

        Raises:
            ImouDeviceSleepingError: when device is sleeping (DV1030).
            ImouDeviceOfflineError: when device is offline (DV1007).
            ImouError: for any other failure.
        """
        if self._device_manager is None:
            self._device_manager = ImouDeviceManager(self._client)
        try:
            data = await self._device_manager.async_get_device_online_status(device_id)
            channels = data.get("channels", [])
            if channels:
                if len(channels) > 1:
                    _LOGGER.warning(
                        "Device %s has %d channels; using channel 0",
                        device_id,
                        len(channels),
                    )
                raw_status = str(channels[0].get("onLine", "0"))
            else:
                raw_status = str(data.get("onLine", "0"))

            if raw_status == "1":
                return DeviceStatus.ACTIVE
            if raw_status == "4":
                return DeviceStatus.SLEEPING
            return DeviceStatus.OFFLINE
        except RequestFailedException as err:
            raise self._translate_exception(err) from err
        except ImouException as err:
            raise ImouError(str(err)) from err

    async def async_get_device_power_info(
        self, device_id: str
    ) -> tuple[int | None, str]:
        """Get battery level and power source via /openapi/getDevicePowerInfo (ADR-1 boundary).

        Returns:
            (battery_level 0-100 or None, power_source "battery"/"adapter"/"unknown")

        Raises:
            ImouDeviceSleepingError: when device is sleeping (DV1030).
            ImouError: for any other failure.
        """
        if self._device_manager is None:
            self._device_manager = ImouDeviceManager(self._client)
        try:
            data = await self._device_manager.async_get_device_power_info(device_id)
            electricitys = data.get("electricitys", [])
            if not electricitys:
                return None, "unknown"
            elec = electricitys[0]
            # litElec = lithium battery, alkElec = alkaline, electric = generic/adapter
            if "litElec" in elec:
                return int(elec["litElec"]), "battery"
            if "alkElec" in elec:
                return int(elec["alkElec"]), "battery"
            if "electric" in elec:
                return int(elec["electric"]), "adapter"
            return None, "unknown"
        except RequestFailedException as err:
            raise self._translate_exception(err) from err
        except ImouException as err:
            raise ImouError(str(err)) from err

    async def async_get_privacy_mode(self, device_id: str) -> bool:
        """Get privacy mode (closedCamera) status via /openapi/getDeviceCameraStatus.

        Returns:
            True when privacy mode is ON (camera closed), False when OFF.

        Raises:
            ImouDeviceSleepingError: when device is sleeping (DV1030).
            ImouDeviceOfflineError: when device is offline (DV1007).
            ImouError: for any other failure.
        """
        if self._device_manager is None:
            self._device_manager = ImouDeviceManager(self._client)
        try:
            data = await self._device_manager.async_get_device_camera_status(device_id)
            # Returns dict with "status": "close" (on) or "open" (off)
            return str(data.get("status", "open")) == "close"
        except RequestFailedException as err:
            raise self._translate_exception(err) from err
        except ImouException as err:
            raise ImouError(str(err)) from err

    async def async_set_privacy_mode(self, device_id: str, enabled: bool) -> None:
        """Set privacy mode (closedCamera) via /openapi/setDeviceCameraStatus.

        Args:
            device_id: Device serial number.
            enabled: True to close camera (privacy ON), False to open camera (privacy OFF).

        Raises:
            ImouDeviceSleepingError: when device is sleeping (DV1030).
            ImouDeviceOfflineError: when device is offline (DV1007).
            ImouError: for any other failure.
        """
        if self._device_manager is None:
            self._device_manager = ImouDeviceManager(self._client)
        # "close" = privacy ON (camera closed), "open" = privacy OFF (camera open)
        status = "close" if enabled else "open"
        try:
            await self._device_manager.async_set_device_camera_status(device_id, status)
        except RequestFailedException as err:
            raise self._translate_exception(err) from err
        except ImouException as err:
            raise ImouError(str(err)) from err

    async def async_get_alarm_status(
        self, device_id: str, begin_time: str, end_time: str
    ) -> tuple[bool, bool]:
        """Get alarm status (motion/human detection) for a device.

        Args:
            device_id: Device serial number.
            begin_time: Start of time window (ISO8601 format).
            end_time: End of time window (ISO8601 format).

        Returns:
            (motion_detected, human_detected) — both booleans.

        Raises:
            ImouDeviceSleepingError: when device is sleeping (DV1030).
            ImouDeviceOfflineError: when device is offline (DV1007).
            ImouError: for any other failure.
        """
        if self._device_manager is None:
            self._device_manager = ImouDeviceManager(self._client)
        try:
            data = await self._device_manager.async_get_device_alarm_message(
                device_id, begin_time, end_time
            )
            alarms = data.get("alarms", [])
            motion_detected = any(
                a.get("alarmType") == "motionDetect" for a in alarms
            )
            human_detected = any(
                a.get("alarmType") in ("humanDetect", "humanoid") for a in alarms
            )
            return motion_detected, human_detected
        except RequestFailedException as err:
            raise self._translate_exception(err) from err
        except ImouException as err:
            raise ImouError(str(err)) from err

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
