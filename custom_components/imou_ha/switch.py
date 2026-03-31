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
    """Privacy mode switch with confirmed-state verification (CTRL-01 through CTRL-04).

    Non-optimistic: state holds previous confirmed value until poll-after-command
    confirms the new state (D-14). Reverts on failure or timeout (D-15, D-16).

    Battery (Dormant) cameras: command is trusted optimistically because the device
    goes to sleep immediately after responding, making poll-after-command unreliable.
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
        """Enable privacy mode with poll-after-command verification (CTRL-02)."""
        await self._async_execute_privacy_command(enable=True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Disable privacy mode with poll-after-command verification (CTRL-02)."""
        await self._async_execute_privacy_command(enable=False)

    async def _async_execute_privacy_command(self, *, enable: bool) -> None:
        """Send command and verify via poll-after-command (D-10, D-11, D-12).

        1. Send setDeviceCameraStatus command
        2. For battery cameras: trust the command (optimistic) — skip verification
        3. For powered cameras: poll getDeviceCameraStatus up to 3 times at 2s intervals
        4. On match: update device_data.privacy_enabled, write state (CONFIRMED)
        5. On sleeping/offline: revert, log warning (D-15, CTRL-03)
        6. On timeout: revert to previous state (D-16, CTRL-04)
        """
        previous = self.device_data.privacy_enabled

        # Step 1: Send command
        try:
            await self.coordinator.client.async_set_privacy_mode(
                self._device_serial,
                enable,
            )
        except ImouNotSupportedError:
            _LOGGER.warning(
                "Device %s does not support privacy mode (DV1026) — disabling entity",
                self._device_serial,
            )
            self._attr_available = False
            self.async_write_ha_state()
            return
        except (ImouDeviceSleepingError, ImouDeviceOfflineError) as err:
            _LOGGER.warning(
                "Privacy command failed for %s: %s",
                self._device_serial,
                err,
            )
            return  # state unchanged — already reflects reality

        # Step 2: Battery cameras — trust command, skip verification
        if CAPABILITY_DORMANT in self.device_data.capabilities:
            _LOGGER.debug(
                "Battery device %s — trusting privacy command (optimistic)",
                self._device_serial,
            )
            self.device_data.privacy_enabled = enable
            self.async_write_ha_state()
            return

        # Step 3: Powered cameras — poll-after-command verification (D-10, D-11)
        for _attempt in range(VERIFY_MAX_RETRIES):
            await asyncio.sleep(VERIFY_DELAY_SECONDS)
            try:
                actual = await self.coordinator.client.async_get_privacy_mode(
                    self._device_serial,
                )
                if actual == enable:
                    self.device_data.privacy_enabled = actual
                    self.async_write_ha_state()
                    return
            except (ImouDeviceSleepingError, ImouDeviceOfflineError):
                break

        # D-16/CTRL-04: TIMEOUT — revert to previous confirmed state
        _LOGGER.warning(
            "Privacy command verification timed out for %s, reverting to %s",
            self._device_serial,
            previous,
        )
        self.device_data.privacy_enabled = previous
        self.async_write_ha_state()
