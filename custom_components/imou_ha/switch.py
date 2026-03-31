"""Switch platform for the Imou integration (CTRL-01 through CTRL-04)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity

from .const import CAPABILITY_DORMANT, CAPABILITY_PRIVACY
from .entity import ImouEntity
from .exceptions import (
    ImouDeviceOfflineError,
    ImouDeviceSleepingError,
    ImouError,
    ImouNotSupportedError,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ImouCoordinator, ImouHaConfigEntry

_LOGGER = logging.getLogger(__name__)

# Command verification constants (D-10, D-11)
VERIFY_DELAY_SECONDS = 2
VERIFY_MAX_RETRIES = 3

# Wake-up timing for battery cameras
WAKE_UP_DELAY_SECONDS = 3
WAKE_UP_MAX_RETRIES = 3


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: ImouHaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Imou switch entities from a config entry (D-08: only closedCamera devices)."""
    coordinator: ImouCoordinator = entry.runtime_data
    entities = []
    for serial, device in coordinator.data.items():
        if CAPABILITY_PRIVACY in device.capabilities:
            entities.append(ImouPrivacySwitch(coordinator, serial))
    async_add_entities(entities)


class ImouPrivacySwitch(ImouEntity, SwitchEntity):
    """Privacy mode switch with wake-up support for battery cameras.

    Powered cameras: non-optimistic with poll-after-command verification.
    Battery (Dormant) cameras: wake up device first, then send command optimistically.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "privacy"

    def __init__(self, coordinator: ImouCoordinator, device_serial: str) -> None:
        """Initialise privacy switch."""
        super().__init__(coordinator, device_serial, "privacy")

    @property
    def is_on(self) -> bool | None:
        """Return True when privacy mode is ON (camera closed). None if unknown (D-09)."""
        return self.device_data.privacy_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Enable privacy mode."""
        await self._async_execute_privacy_command(enable=True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Disable privacy mode."""
        await self._async_execute_privacy_command(enable=False)

    async def _async_wake_and_retry(self, enable: bool) -> bool:
        """Wake a sleeping battery camera and retry the privacy command.

        Returns True if the command succeeded after wake-up.
        """
        for attempt in range(WAKE_UP_MAX_RETRIES):
            try:
                _LOGGER.debug(
                    "Waking battery device %s (attempt %d/%d)",
                    self._device_serial, attempt + 1, WAKE_UP_MAX_RETRIES,
                )
                await self.coordinator.client.async_wake_up_device(self._device_serial)
                await asyncio.sleep(WAKE_UP_DELAY_SECONDS)
                await self.coordinator.client.async_set_privacy_mode(
                    self._device_serial, enable,
                )
                return True
            except ImouDeviceSleepingError:
                _LOGGER.debug("Device %s still sleeping after wake attempt %d", self._device_serial, attempt + 1)
                continue
            except ImouError as err:
                _LOGGER.warning("Wake+command failed for %s: %s", self._device_serial, err)
                return False
        return False

    async def _async_execute_privacy_command(self, *, enable: bool) -> None:
        """Send privacy command with wake-up support for battery cameras.

        Battery cameras: wake up first if sleeping, then trust command (optimistic).
        Powered cameras: send command, verify via poll-after-command.
        """
        previous = self.device_data.privacy_enabled
        is_battery = CAPABILITY_DORMANT in self.device_data.capabilities

        # Step 1: Send command
        try:
            await self.coordinator.client.async_set_privacy_mode(
                self._device_serial, enable,
            )
        except ImouNotSupportedError:
            _LOGGER.warning(
                "Device %s does not support privacy mode (DV1026) — disabling entity",
                self._device_serial,
            )
            self._attr_available = False
            self.async_write_ha_state()
            return
        except (ImouDeviceSleepingError, ImouDeviceOfflineError):
            if not is_battery:
                _LOGGER.warning("Privacy command failed for %s: device unreachable", self._device_serial)
                return

            # Battery camera sleeping — wake up and retry
            if not await self._async_wake_and_retry(enable):
                _LOGGER.warning("Could not wake device %s after %d attempts", self._device_serial, WAKE_UP_MAX_RETRIES)
                return

        # Step 2: Battery cameras — trust command, skip verification
        if is_battery:
            _LOGGER.debug("Battery device %s — trusting privacy command (optimistic)", self._device_serial)
            self.device_data.privacy_enabled = enable
            self.async_write_ha_state()
            return

        # Step 3: Powered cameras — poll-after-command verification
        for _attempt in range(VERIFY_MAX_RETRIES):
            await asyncio.sleep(VERIFY_DELAY_SECONDS)
            try:
                actual = await self.coordinator.client.async_get_privacy_mode(self._device_serial)
                if actual == enable:
                    self.device_data.privacy_enabled = actual
                    self.async_write_ha_state()
                    return
            except (ImouDeviceSleepingError, ImouDeviceOfflineError):
                break

        # TIMEOUT — revert to previous confirmed state
        _LOGGER.warning(
            "Privacy command verification timed out for %s, reverting to %s",
            self._device_serial, previous,
        )
        self.device_data.privacy_enabled = previous
        self.async_write_ha_state()
