"""ImouCoordinator — DataUpdateCoordinator for Imou device discovery and polling."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CAPABILITY_ELECTRIC, DEFAULT_SCAN_INTERVAL, DOMAIN, SLEEP_CHECK_INTERVAL
from .exceptions import ImouAuthError, ImouDeviceOfflineError, ImouDeviceSleepingError, ImouError
from .models import DeviceStatus, ImouDeviceData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .api_client import ImouApiClient

_LOGGER = logging.getLogger(__name__)

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
        self._sleep_check_times: dict[str, datetime] = {}

    async def _async_setup(self) -> None:
        """Discover devices on first coordinator refresh (HA 2024.8+ pattern).

        Raises:
            ConfigEntryAuthFailed: when credentials are rejected.
            UpdateFailed: on any other API error (never crashes HA — NFR1).

        """
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
        if not self.data:
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

        return self.data

    async def _async_check_wake(self, serial: str, device: ImouDeviceData) -> None:
        """Lightweight online check for sleeping/offline device (POLL-03)."""
        try:
            new_status = await self.client.async_get_device_online_status(serial)
            if new_status != device.status:
                _LOGGER.info(
                    "Device %s status changed: %s -> %s", serial, device.status.value, new_status.value
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
            device.last_updated = datetime.now(UTC)

            if CAPABILITY_ELECTRIC in device.capabilities:
                battery_level, power_source = await self.client.async_get_device_power_info(serial)
                device.battery_level = battery_level
                device.battery_power_source = power_source
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
