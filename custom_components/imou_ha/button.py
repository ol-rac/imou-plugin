"""Button platform for the Imou integration — wake up battery cameras (D-09, D-10)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity

from .const import (
    CAPABILITY_DORMANT,
    WAKE_UP_MAX_RETRIES,
    WAKE_UP_VERIFY_DELAY_SECONDS,
)
from .entity import ImouEntity
from .exceptions import ImouError
from .models import DeviceStatus

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ImouCoordinator, ImouHaConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: ImouHaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Imou button entities — single wake button per battery camera (D-09)."""
    coordinator: ImouCoordinator = entry.runtime_data
    entities = []
    for serial, device in coordinator.data.items():
        if CAPABILITY_DORMANT in device.capabilities:
            entities.append(ImouWakeUpButton(coordinator, serial))
    async_add_entities(entities)


class ImouWakeUpButton(ImouEntity, ButtonEntity):
    """Wake up battery camera via closeDormant with status verification (D-09, D-10)."""

    _attr_has_entity_name = True
    _attr_translation_key = "wake_up"

    def __init__(self, coordinator: ImouCoordinator, device_serial: str) -> None:
        """Initialise wake up button."""
        super().__init__(coordinator, device_serial, "wake_up")

    @property
    def available(self) -> bool:
        """Always available when device is known — the whole point is to wake sleeping devices."""
        return self._device_serial in (self.coordinator.data or {})

    async def _async_wake_and_verify(self) -> bool:
        """Wake sleeping battery camera via closeDormant, verify ACTIVE status.

        Returns True when device reaches ACTIVE state within retry budget.
        Calls coordinator.async_request_refresh() on success so all entities update (D-11, D-12).
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
                    await self.coordinator.async_request_refresh()
                    return True
            except ImouError as err:
                _LOGGER.debug("Status check error on attempt %d: %s", attempt + 1, err)

        _LOGGER.warning(
            "Device %s did not reach ACTIVE after %d wake attempts",
            self._device_serial, WAKE_UP_MAX_RETRIES,
        )
        return False

    async def async_press(self) -> None:
        """Wake up the battery camera via closeDormant with status verification (D-10, D-12)."""
        if not await self._async_wake_and_verify():
            _LOGGER.warning("Wake up failed for %s", self._device_serial)
