"""Switch platform for the Imou integration (CTRL-01 through CTRL-04)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity

from .const import (
    CAPABILITY_DORMANT,
    CAPABILITY_PRIVACY,
    WAKE_UP_MAX_RETRIES,
    WAKE_UP_VERIFY_DELAY_SECONDS,
)
from .entity import ImouEntity
from .exceptions import (
    ImouDeviceOfflineError,
    ImouDeviceSleepingError,
    ImouError,
    ImouNotSupportedError,
)
from .models import DeviceStatus

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ImouCoordinator, ImouHaConfigEntry

_LOGGER = logging.getLogger(__name__)

# Command verification constants (D-10, D-11)
VERIFY_DELAY_SECONDS = 2
VERIFY_MAX_RETRIES = 3


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

    All cameras use poll-after-command verification after wake (if needed).
    Battery (Dormant) cameras: wake via closeDormant if sleeping, then poll-after-command.
    Powered cameras: send command, verify via poll-after-command.
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

    async def _async_wake_and_verify(self) -> bool:
        """Wake sleeping battery camera via closeDormant, verify ACTIVE status.

        Returns True when device reaches ACTIVE state within retry budget.
        Calls coordinator.async_request_refresh() on success so all entities update (D-11, D-13).
        """
        for attempt in range(WAKE_UP_MAX_RETRIES):
            _LOGGER.debug(
                "closeDormant attempt %d/%d for %s",
                attempt + 1, WAKE_UP_MAX_RETRIES, self._device_serial,
            )
            try:
                await self.coordinator.client.async_wake_up_via_dormant(self._device_serial)
            except ImouError as err:
                _LOGGER.debug("closeDormant call error (non-fatal): %s", err)

            await asyncio.sleep(WAKE_UP_VERIFY_DELAY_SECONDS)

            try:
                status = await self.coordinator.client.async_get_device_online_status(
                    self._device_serial,
                )
                if status == DeviceStatus.ACTIVE:
                    _LOGGER.debug("Device %s is ACTIVE after wake", self._device_serial)
                    self.device_data.status = DeviceStatus.ACTIVE
                    self.coordinator.async_set_updated_data(self.coordinator.data)
                    await self.coordinator.async_request_refresh()
                    return True
            except ImouError as err:
                _LOGGER.debug("Status check error on attempt %d: %s", attempt + 1, err)

        _LOGGER.warning(
            "Device %s did not reach ACTIVE after %d wake attempts",
            self._device_serial, WAKE_UP_MAX_RETRIES,
        )
        return False

    async def _async_execute_privacy_command(self, *, enable: bool) -> None:
        """Send privacy command with wake-up support for battery cameras.

        All cameras use poll-after-command verification after a successful command.
        Battery (Dormant) cameras: wake via closeDormant if sleeping, then retry command.
        Powered cameras: send command directly, no wake attempt.
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

            # Battery camera sleeping — wake and resend
            if not await self._async_wake_and_verify():
                _LOGGER.warning(
                    "Could not wake device %s after %d attempts",
                    self._device_serial, WAKE_UP_MAX_RETRIES,
                )
                return
            # Device is now ACTIVE — retry the privacy command once
            try:
                await self.coordinator.client.async_set_privacy_mode(
                    self._device_serial, enable,
                )
            except ImouError as err:
                _LOGGER.warning(
                    "Privacy command failed after wake for %s: %s",
                    self._device_serial, err,
                )
                return

        # Step 2: Poll-after-command verification for ALL cameras (battery and powered alike)
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
