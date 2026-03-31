"""API client wrapper — sole pyimouapi boundary (ADR-1, D-16)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pyimouapi import ImouOpenApiClient
from pyimouapi.device import ImouDeviceManager
from pyimouapi.exceptions import (
    ConnectFailedException,
    ImouException,
    InvalidAppIdOrSecretException,
    RequestFailedException,
)

from .budget import ImouBudgetState
from .const import (
    CAPABILITY_DORMANT,
    CHANNEL_DEFAULT,
    ENABLE_TYPE_CLOSE_CAMERA,
    ENABLE_TYPE_CLOSE_DORMANT,
    ERROR_CODE_DEVICE_OFFLINE,
    ERROR_CODE_DEVICE_SLEEPING,
    ERROR_CODE_LICENSE_LIMIT,
    ERROR_CODE_LIVE_ALREADY_EXIST,
    ERROR_CODE_LIVE_NOT_EXIST,
    ERROR_CODE_NOT_SUPPORTED,
    ERROR_CODE_RATE_LIMIT,
)
from .exceptions import (
    ImouAuthError,
    ImouDeviceOfflineError,
    ImouDeviceSleepingError,
    ImouError,
    ImouLicenseError,
    ImouNotSupportedError,
    ImouRateLimitError,
)
from .models import DeviceStatus, ImouDeviceData

_LOGGER = logging.getLogger(__name__)


class ImouApiClient:
    """Sole boundary to the pyimouapi library.

    All pyimouapi exceptions are caught here and re-raised as ImouError
    subtypes. No pyimouapi types leak out of this class.
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        api_url: str,
        budget_state: ImouBudgetState | None = None,
    ) -> None:
        """Initialise the API client with Imou cloud credentials."""
        self._client = ImouOpenApiClient(app_id, app_secret, api_url)
        self._device_manager: ImouDeviceManager | None = None
        self._budget_state = budget_state

    def _increment_budget(self) -> None:
        """Increment the API budget counter if budget tracking is enabled."""
        if self._budget_state is not None:
            self._budget_state.increment(datetime.now(UTC))

    async def async_validate_credentials(self) -> None:
        """Validate credentials by obtaining an access token.

        Raises:
            ImouAuthError: when AppId/AppSecret are invalid.
            ImouError: for any other connection or API failure.

        """
        self._increment_budget()
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
        self._increment_budget()
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
        self._increment_budget()
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
        self, device_id: str,
    ) -> tuple[int | None, str]:
        """Get battery level and power source via /openapi/getDevicePowerInfo (ADR-1 boundary).

        Returns:
            (battery_level 0-100 or None, power_source "battery"/"adapter"/"unknown")

        Raises:
            ImouDeviceSleepingError: when device is sleeping (DV1030).
            ImouError: for any other failure.

        """
        self._increment_budget()
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

    async def async_get_alarm_status(
        self, device_id: str, begin_time: str, end_time: str,
    ) -> tuple[bool, bool]:
        """Get motion and human detection status via /openapi/getAlarmMessage (D-01).

        Calls the Imou cloud alarm message endpoint directly (pyimouapi 1.2.x has no
        wrapper for this endpoint — Pitfall 1 from RESEARCH.md).

        Args:
            device_id: Device serial number.
            begin_time: Start of alarm window, formatted "%Y-%m-%d %H:%M:%S".
            end_time: End of alarm window, formatted "%Y-%m-%d %H:%M:%S".

        Returns:
            (motion_detected, human_detected) tuple of bools.
            motion_detected: True when any alarm has type == 1 (MobileDetect).
            human_detected: True when any alarm has type in (0, 4)
                            (type 0 = human, type 4 = accessory human body).

        Raises:
            ImouDeviceSleepingError: when device is sleeping (DV1030).
            ImouDeviceOfflineError: when device is offline (DV1007).
            ImouError: for any other API failure.

        """
        self._increment_budget()
        try:
            data = await self._client.async_request_api(
                "/openapi/getAlarmMessage",
                {
                    "deviceId": device_id,
                    "channelId": "0",
                    "beginTime": begin_time,
                    "endTime": end_time,
                    "count": 30,
                },
            )
            alarms = data.get("alarms", [])
            motion = any(a.get("type") == 1 for a in alarms)
            human = any(a.get("type") in (0, 4) for a in alarms)
            return motion, human
        except RequestFailedException as err:
            raise self._translate_exception(err) from err
        except ImouException as err:
            raise ImouError(str(err)) from err

    async def async_get_stream_url(
        self, device_id: str, channel: str = "0",
    ) -> tuple[str | None, str | None]:
        """Get HLS stream URLs (HD and SD) for a device channel (STRM-01, D-01).

        Tries ``async_get_stream_url`` first; if session doesn't exist (LV1002) it
        creates one via ``async_create_stream_url``. If create returns LV1001 (session
        already exists from another client) falls back to get again.

        Args:
            device_id: Device serial number.
            channel: Channel ID, defaults to ``"0"`` for single-channel IPC cameras.

        Returns:
            (hd_url, sd_url) where hd_url is streams[0].hls and sd_url is streams[1].hls.
            Either may be None if not present in the response.

        Raises:
            ImouDeviceSleepingError: when device is sleeping (DV1030).
            ImouDeviceOfflineError: when device is offline (DV1007).
            ImouError: for any other failure.

        """
        self._increment_budget()
        if self._device_manager is None:
            self._device_manager = ImouDeviceManager(self._client)
        try:
            try:
                data = await self._device_manager.async_get_stream_url(device_id, channel)
            except RequestFailedException as err:
                message = err.message if hasattr(err, "message") else str(err)
                error_code = message.split(":")[0] if ":" in message else message
                if error_code == ERROR_CODE_LIVE_NOT_EXIST:
                    # Stream session does not exist — create one
                    try:
                        data = await self._device_manager.async_create_stream_url(
                            device_id, channel, stream_id=0,
                        )
                    except RequestFailedException as create_err:
                        create_msg = (
                            create_err.message
                            if hasattr(create_err, "message")
                            else str(create_err)
                        )
                        create_code = (
                            create_msg.split(":")[0] if ":" in create_msg else create_msg
                        )
                        if create_code == ERROR_CODE_LIVE_ALREADY_EXIST:
                            # Session created by another client — get it now
                            data = await self._device_manager.async_get_stream_url(
                                device_id, channel,
                            )
                        else:
                            raise self._translate_exception(create_err) from create_err
                else:
                    raise self._translate_exception(err) from err

            streams = data.get("streams", [])
            hd_url: str | None = next(
                (s["hls"] for s in streams if s.get("hls")), None,
            )
            sd_url: str | None = (
                streams[1]["hls"]
                if len(streams) > 1 and streams[1].get("hls")
                else None
            )
            return hd_url, sd_url
        except ImouException as err:
            raise ImouError(str(err)) from err

    async def async_get_privacy_mode(self, device_id: str) -> bool:
        """Get current privacy mode (closeCamera) state (CTRL-01).

        Args:
            device_id: Device serial number.

        Returns:
            True when privacy mode is enabled (camera lens covered), False otherwise.

        Raises:
            ImouDeviceSleepingError: when device is sleeping (DV1030).
            ImouError: for any other failure.

        """
        self._increment_budget()
        if self._device_manager is None:
            self._device_manager = ImouDeviceManager(self._client)
        try:
            data = await self._device_manager.async_get_device_status(
                device_id, CHANNEL_DEFAULT, ENABLE_TYPE_CLOSE_CAMERA,
            )
            return bool(data.get("enable", False))
        except RequestFailedException as err:
            raise self._translate_exception(err) from err
        except ImouException as err:
            raise ImouError(str(err)) from err

    async def async_set_privacy_mode(self, device_id: str, enabled: bool) -> None:
        """Set privacy mode (closeCamera) state (CTRL-01).

        Args:
            device_id: Device serial number.
            enabled: True to enable privacy mode (cover lens), False to disable.

        Raises:
            ImouDeviceSleepingError: when device is sleeping (DV1030).
            ImouError: for any other failure.

        """
        self._increment_budget()
        if self._device_manager is None:
            self._device_manager = ImouDeviceManager(self._client)
        try:
            await self._device_manager.async_set_device_status(
                device_id, CHANNEL_DEFAULT, ENABLE_TYPE_CLOSE_CAMERA, enabled,
            )
        except RequestFailedException as err:
            raise self._translate_exception(err) from err
        except ImouException as err:
            raise ImouError(str(err)) from err

    async def async_wake_up_via_dormant(self, device_id: str) -> None:
        """Wake up a sleeping device via setDeviceCameraStatus(closeDormant=True).

        This is the method used by imou_life — calls the API directly without
        channel_id, which is not needed for closeDormant.

        Raises:
            ImouError: for any failure.

        """
        self._increment_budget()
        try:
            await self._client.async_request_api(
                "/openapi/setDeviceCameraStatus",
                {
                    "deviceId": device_id,
                    "channelId": "0",
                    "enableType": ENABLE_TYPE_CLOSE_DORMANT,
                    "enable": True,
                },
            )
        except RequestFailedException as err:
            raise self._translate_exception(err) from err
        except ImouException as err:
            raise ImouError(str(err)) from err

    async def async_set_message_callback(
        self, callback_url: str, *, enable: bool,
    ) -> None:
        """Register or deregister Imou push notification callback URL (per D-02, D-03)."""
        self._increment_budget()
        try:
            if enable:
                params = {
                    "callbackFlag": "alarm,deviceStatus",
                    "callbackUrl": callback_url,
                    "status": "on",
                }
            else:
                params = {"status": "off"}
            await self._client.async_request_api("/openapi/setMessageCallback", params)
        except RequestFailedException as err:
            raise self._translate_exception(err) from err
        except ImouException as err:
            raise ImouError(str(err)) from err

    async def async_get_message_callback(self) -> dict[str, str]:
        """Get current Imou push notification callback configuration."""
        self._increment_budget()
        try:
            return await self._client.async_request_api("/openapi/getMessageCallback", {})
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
        if error_code == ERROR_CODE_NOT_SUPPORTED:
            return ImouNotSupportedError(message)
        return ImouError(message)
