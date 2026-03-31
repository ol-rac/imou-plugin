"""Button platform for the Imou integration — wake up battery cameras."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity

from .const import CAPABILITY_DORMANT
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
    """Set up Imou button entities — two wake methods for battery cameras."""
    coordinator: ImouCoordinator = entry.runtime_data
    entities = []
    for serial, device in coordinator.data.items():
        if CAPABILITY_DORMANT in device.capabilities:
            entities.append(ImouWakeUpDormantButton(coordinator, serial))
            entities.append(ImouWakeUpApiButton(coordinator, serial))
    async_add_entities(entities)


class ImouWakeUpDormantButton(ImouEntity, ButtonEntity):
    """Wake up via closeDormant (imou_life method)."""

    _attr_has_entity_name = True
    _attr_translation_key = "wake_up_dormant"

    def __init__(self, coordinator: ImouCoordinator, device_serial: str) -> None:
        """Initialise wake up dormant button."""
        super().__init__(coordinator, device_serial, "wake_up_dormant")

    @property
    def available(self) -> bool:
        """Always available — the whole point is to wake sleeping devices."""
        return self._device_serial in (self.coordinator.data or {})

    async def async_press(self) -> None:
        """Wake up the device via closeDormant with retry."""
        _LOGGER.warning(
            "TEST: Device %s capabilities: %s",
            self._device_serial, self.device_data.capabilities,
        )
        for attempt in range(5):
            _LOGGER.warning(
                "TEST: closeDormant attempt %d/5 for %s", attempt + 1, self._device_serial,
            )
            try:
                await self.coordinator.client.async_wake_up_via_dormant(self._device_serial)
                _LOGGER.warning("TEST: closeDormant call succeeded for %s", self._device_serial)
            except ImouError as err:
                _LOGGER.warning("TEST: closeDormant call error: %s (will check status anyway)", err)

            # Wait for device to wake up
            await asyncio.sleep(5)

            # Check if device is online now
            try:
                status = await self.coordinator.client.async_get_device_online_status(self._device_serial)
                _LOGGER.warning(
                    "TEST: Device %s status after attempt %d: %s",
                    self._device_serial, attempt + 1, status.value,
                )
                if status == DeviceStatus.ACTIVE:
                    _LOGGER.warning("TEST: Device %s is AWAKE!", self._device_serial)
                    return
            except ImouError as err:
                _LOGGER.warning("TEST: Status check error: %s", err)

        _LOGGER.warning("TEST: Device %s did NOT wake after 5 attempts", self._device_serial)


class ImouWakeUpApiButton(ImouEntity, ButtonEntity):
    """Wake up via wakeUpDevice API endpoint."""

    _attr_has_entity_name = True
    _attr_translation_key = "wake_up_api"

    def __init__(self, coordinator: ImouCoordinator, device_serial: str) -> None:
        """Initialise wake up API button."""
        super().__init__(coordinator, device_serial, "wake_up_api")

    @property
    def available(self) -> bool:
        """Always available — the whole point is to wake sleeping devices."""
        return self._device_serial in (self.coordinator.data or {})

    async def async_press(self) -> None:
        """Wake up the device via wakeUpDevice API."""
        _LOGGER.warning(
            "TEST: Sending wakeUpDevice to %s", self._device_serial,
        )
        try:
            await self.coordinator.client.async_wake_up_device(self._device_serial)
            status = await self.coordinator.client.async_get_device_online_status(self._device_serial)
            _LOGGER.warning(
                "TEST: wakeUpDevice sent to %s — device status after: %s",
                self._device_serial, status.value,
            )
        except ImouError as err:
            _LOGGER.warning("TEST: wakeUpDevice FAILED for %s: %s", self._device_serial, err)
