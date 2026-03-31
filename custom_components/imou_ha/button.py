"""Button platform for the Imou integration — wake up battery cameras."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity

from .const import CAPABILITY_DORMANT
from .entity import ImouEntity
from .exceptions import ImouError

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
    """Set up Imou button entities — wake up for battery cameras only."""
    coordinator: ImouCoordinator = entry.runtime_data
    entities = []
    for serial, device in coordinator.data.items():
        if CAPABILITY_DORMANT in device.capabilities:
            entities.append(ImouWakeUpButton(coordinator, serial))
    async_add_entities(entities)


class ImouWakeUpButton(ImouEntity, ButtonEntity):
    """Wake up button for battery-powered Imou cameras."""

    _attr_has_entity_name = True
    _attr_translation_key = "wake_up"

    def __init__(self, coordinator: ImouCoordinator, device_serial: str) -> None:
        """Initialise wake up button."""
        super().__init__(coordinator, device_serial, "wake_up")

    @property
    def available(self) -> bool:
        """Always available — the whole point is to wake sleeping devices."""
        return self._device_serial in (self.coordinator.data or {})

    async def async_press(self) -> None:
        """Wake up the device."""
        try:
            await self.coordinator.client.async_wake_up_device(self._device_serial)
            _LOGGER.info("Wake-up command sent to %s", self._device_serial)
        except ImouError as err:
            _LOGGER.warning("Failed to wake device %s: %s", self._device_serial, err)
