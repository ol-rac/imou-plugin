"""ImouCoordinator — DataUpdateCoordinator for Imou device discovery and polling."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .exceptions import ImouAuthError, ImouError
from .models import ImouDeviceData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .api_client import ImouApiClient

_LOGGER = logging.getLogger(__name__)

type ImouHaConfigEntry = ConfigEntry[ImouCoordinator]


class ImouCoordinator(DataUpdateCoordinator[dict[str, ImouDeviceData]]):
    """Manages Imou device data via DataUpdateCoordinator.

    Lifecycle:
      - _async_setup: called once on first refresh — discovers all devices.
      - _async_update_data: called on each subsequent poll — returns current data
        (Phase 1 pass-through; will poll device statuses in Phase 3).
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
        """Return current device data (Phase 1 pass-through).

        Phase 3 will add live status polling here.

        Raises:
            ConfigEntryAuthFailed: when credentials are rejected.
            UpdateFailed: on any other API error (never crashes HA — NFR1).

        """
        try:
            # Phase 1: return the data populated by _async_setup unchanged.
            # Phase 3 will call self.client.async_get_devices() or status updates.
            return self.data or {}
        except ImouAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ImouError as err:
            raise UpdateFailed(str(err)) from err
