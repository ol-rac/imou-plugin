"""ImouCoordinator — DataUpdateCoordinator for Imou device discovery and polling."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.components.persistent_notification import async_create as pn_create
from homeassistant.components.persistent_notification import async_dismiss as pn_dismiss
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .budget import BUDGET_STORAGE_KEY, ImouBudgetState
from .const import (
    CAPABILITY_ALARM_MD,
    CAPABILITY_ELECTRIC,
    CAPABILITY_MOTION_DETECT,
    CAPABILITY_PRIVACY,
    DEFAULT_ENABLE_THROTTLE,
    DEFAULT_RESERVE_SIZE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MONTHLY_API_LIMIT,
    OPT_ENABLE_THROTTLE,
    OPT_RESERVE_SIZE,
    SLEEP_CHECK_INTERVAL,
    THROTTLE_CRITICAL_PCT,
    THROTTLE_WARN_PCT,
)
from .exceptions import (
    ImouAuthError,
    ImouDeviceOfflineError,
    ImouDeviceSleepingError,
    ImouError,
    ImouNotSupportedError,
)
from .models import DeviceStatus, ImouDeviceData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .api_client import ImouApiClient

_LOGGER = logging.getLogger(__name__)

_ALARM_TIME_FMT = "%Y-%m-%d %H:%M:%S"
_NOTIFICATION_ID = "imou_budget_critical"

type ImouHaConfigEntry = ConfigEntry[ImouCoordinator]


class ImouCoordinator(DataUpdateCoordinator[dict[str, ImouDeviceData]]):
    """Manages Imou device data via DataUpdateCoordinator.

    Lifecycle:
      - _async_setup: called once on first refresh — discovers all devices.
      - _async_update_data: called on each subsequent poll — sleep-aware per-device polling.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: ImouApiClient,
        config_entry: ConfigEntry | None = None,
        budget_state: ImouBudgetState | None = None,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialise coordinator with HA instance and API client."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.config_entry = config_entry
        self._base_scan_interval = scan_interval
        self._sleep_check_times: dict[str, datetime] = {}
        # Budget state — shared with api_client (same object instance)
        self._budget_state = budget_state or ImouBudgetState()
        # Throttle settings from options
        self._throttle_enabled = (
            config_entry.options.get(OPT_ENABLE_THROTTLE, DEFAULT_ENABLE_THROTTLE)
            if config_entry is not None
            else DEFAULT_ENABLE_THROTTLE
        )
        self._reserve_size = (
            config_entry.options.get(OPT_RESERVE_SIZE, DEFAULT_RESERVE_SIZE)
            if config_entry is not None
            else DEFAULT_RESERVE_SIZE
        )
        self._notification_active = False

    @property
    def budget_state(self) -> ImouBudgetState:
        """Return the shared budget state for sensors to read."""
        return self._budget_state

    def _check_and_apply_throttle(self) -> None:
        """Adjust update_interval based on remaining API budget (D-09, D-13)."""
        if not self._throttle_enabled:
            self.update_interval = timedelta(seconds=self._base_scan_interval)
            return
        effective_limit = MONTHLY_API_LIMIT - self._reserve_size
        remaining = effective_limit - self._budget_state.calls_this_month
        pct_remaining = remaining / effective_limit if effective_limit > 0 else 1.0
        base = timedelta(seconds=self._base_scan_interval)
        if pct_remaining > THROTTLE_WARN_PCT:
            self.update_interval = base
            if self._notification_active:
                pn_dismiss(self.hass, _NOTIFICATION_ID)
                self._notification_active = False
        elif pct_remaining >= THROTTLE_CRITICAL_PCT:
            self.update_interval = base * 2
            _LOGGER.warning(
                "API budget <30%% remaining (%d calls left) — polling doubled",
                remaining,
            )
            if self._notification_active:
                pn_dismiss(self.hass, _NOTIFICATION_ID)
                self._notification_active = False
        else:
            self.update_interval = base * 4
            _LOGGER.warning(
                "API budget <10%% remaining (%d calls left) — polling quadrupled",
                remaining,
            )
            if not self._notification_active:
                pn_create(
                    self.hass,
                    message=(
                        "Imou API budget is critically low (<10% remaining). "
                        "Polling has been reduced to protect your remaining calls "
                        "for device control."
                    ),
                    title="Imou Integration — API Budget Warning",
                    notification_id=_NOTIFICATION_ID,
                )
                self._notification_active = True

    def _async_save_budget(self) -> None:
        """Persist budget state to config entry data."""
        if self.config_entry is None:
            return
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={**self.config_entry.data, BUDGET_STORAGE_KEY: self._budget_state.to_dict()},
        )

    async def _async_setup(self) -> None:
        """Discover devices on first coordinator refresh (HA 2024.8+ pattern).

        Raises:
            ConfigEntryAuthFailed: when credentials are rejected.
            UpdateFailed: on any other API error (never crashes HA — NFR1).

        """
        self._check_and_apply_throttle()
        try:
            self.data = await self.client.async_get_devices()
        except ImouAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ImouError as err:
            raise UpdateFailed(str(err)) from err

        _LOGGER.info("Discovered %d Imou devices", len(self.data))

    async def _async_update_data(self) -> dict[str, ImouDeviceData]:
        """Poll devices with sleep-aware skip logic (D-09).

        - POLL-01: Skip sleeping devices.
        - POLL-02: Resume polling when device wakes.
        - POLL-03: Wake-check sleeping/offline devices max every 5 min (D-10).
        - POLL-04: Active devices polled every cycle.
        """
        self._check_and_apply_throttle()

        if not self.data:
            self._async_save_budget()
            return {}

        now = datetime.now(UTC)
        sleep_interval = timedelta(seconds=SLEEP_CHECK_INTERVAL)

        for serial, device in self.data.items():
            if device.status in (DeviceStatus.SLEEPING, DeviceStatus.OFFLINE):
                # POLL-01/D-13: skip full poll, only wake-check
                last_check = self._sleep_check_times.get(serial)
                if last_check is None or (now - last_check) >= sleep_interval:
                    await self._async_check_wake(serial, device)
                    self._sleep_check_times[serial] = now
                continue
            # POLL-04: active device — full poll
            await self._async_poll_device(serial, device)
            # Clear sleep check timestamp when device is active
            self._sleep_check_times.pop(serial, None)

        self._async_save_budget()
        return self.data

    async def _async_check_wake(self, serial: str, device: ImouDeviceData) -> None:
        """Lightweight online check for sleeping/offline device (POLL-03)."""
        try:
            new_status = await self.client.async_get_device_online_status(serial)
            if new_status != device.status:
                _LOGGER.info(
                    "Device %s status changed: %s -> %s", serial, device.status.value, new_status.value,
                )
                device.status = new_status
        except ImouDeviceSleepingError:
            device.status = DeviceStatus.SLEEPING
        except ImouDeviceOfflineError:
            device.status = DeviceStatus.OFFLINE
        except ImouError as err:
            _LOGGER.debug("Wake check failed for %s: %s", serial, err)

    async def _async_poll_device(self, serial: str, device: ImouDeviceData) -> None:
        """Full status poll for active device (POLL-04)."""
        try:
            new_status = await self.client.async_get_device_online_status(serial)
            device.status = new_status

            if CAPABILITY_ELECTRIC in device.capabilities:
                battery_level, power_source = await self.client.async_get_device_power_info(serial)
                device.battery_level = battery_level
                device.battery_power_source = power_source

            if CAPABILITY_PRIVACY in device.capabilities:
                try:
                    device.privacy_enabled = await self.client.async_get_privacy_mode(serial)
                except ImouNotSupportedError:
                    _LOGGER.info("Device %s reports CloseCamera but doesn't support it (DV1026) — skipping privacy poll", serial)
                    device.capabilities.discard(CAPABILITY_PRIVACY)

            # Alarm poll must happen BEFORE last_updated is set so the time window uses
            # the previous poll's timestamp as begin_time (D-02, D-03).
            if CAPABILITY_MOTION_DETECT in device.capabilities or CAPABILITY_ALARM_MD in device.capabilities:
                try:
                    begin_str = device.last_updated.strftime(_ALARM_TIME_FMT)
                    end_str = datetime.now(UTC).strftime(_ALARM_TIME_FMT)
                    motion, human = await self.client.async_get_alarm_status(serial, begin_str, end_str)
                    device.motion_detected = motion
                    device.human_detected = human
                except ImouError as err:
                    _LOGGER.warning("Alarm status poll failed for device %s: %s", serial, err)

            device.last_updated = datetime.now(UTC)
        except ImouDeviceSleepingError:
            device.status = DeviceStatus.SLEEPING
            _LOGGER.info("Device %s transitioned to sleeping during poll", serial)
        except ImouDeviceOfflineError:
            device.status = DeviceStatus.OFFLINE
            _LOGGER.info("Device %s transitioned to offline during poll", serial)
        except ImouAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ImouError as err:
            _LOGGER.warning("Poll failed for device %s: %s", serial, err)
