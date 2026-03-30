"""Binary sensor platform for the Imou integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CAPABILITY_ALARM_MD,
    CAPABILITY_HUMAN_DETECT,
    CAPABILITY_HUMAN_DETECT_AI,
    CAPABILITY_HUMAN_DETECT_SMD,
    CAPABILITY_MOTION_DETECT,
)
from .entity import ImouEntity
from .models import DeviceStatus

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .coordinator import ImouCoordinator, ImouHaConfigEntry

_LOGGER = logging.getLogger(__name__)

HUMAN_DETECT_CAPS = frozenset({
    CAPABILITY_HUMAN_DETECT,
    CAPABILITY_HUMAN_DETECT_AI,
    CAPABILITY_HUMAN_DETECT_SMD,
})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ImouHaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Imou binary sensor entities from a config entry."""
    coordinator: ImouCoordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    for serial, device in coordinator.data.items():
        entities.append(ImouOnlineSensor(coordinator, serial))
        if CAPABILITY_MOTION_DETECT in device.capabilities or CAPABILITY_ALARM_MD in device.capabilities:
            entities.append(ImouMotionSensor(coordinator, serial))
        if device.capabilities & HUMAN_DETECT_CAPS:
            entities.append(ImouHumanDetectionSensor(coordinator, serial))
    async_add_entities(entities)


class ImouOnlineSensor(ImouEntity, BinarySensorEntity):
    """Binary sensor that reports whether a device is online (connectivity).

    is_on is True when device is ACTIVE, False for SLEEPING or OFFLINE.
    Goes unavailable when the device is sleeping/offline (D-11) via base ImouEntity.available.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_translation_key = "online"

    def __init__(self, coordinator: ImouCoordinator, device_serial: str) -> None:
        """Initialise online binary sensor."""
        super().__init__(coordinator, device_serial, "online")

    @property
    def is_on(self) -> bool | None:
        """Return True if device is active (online), False otherwise, None if unknown."""
        if self._device_serial not in (self.coordinator.data or {}):
            return None
        return self.device_data.status == DeviceStatus.ACTIVE


class ImouMotionSensor(ImouEntity, BinarySensorEntity):
    """Binary sensor for motion detection (EVNT-02).

    is_on reflects device.motion_detected from coordinator data.
    Goes unavailable when the device is sleeping/offline (D-14) via base ImouEntity.available.
    """

    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_has_entity_name = True
    _attr_translation_key = "motion"

    def __init__(self, coordinator: ImouCoordinator, device_serial: str) -> None:
        """Initialise motion binary sensor."""
        super().__init__(coordinator, device_serial, "motion")

    @property
    def is_on(self) -> bool | None:
        """Return True if motion was detected in the last poll window, None if unknown."""
        if self._device_serial not in (self.coordinator.data or {}):
            return None
        return self.device_data.motion_detected


class ImouHumanDetectionSensor(ImouEntity, BinarySensorEntity):
    """Binary sensor for human detection (EVNT-03).

    is_on reflects device.human_detected from coordinator data.
    Goes unavailable when the device is sleeping/offline (D-14) via base ImouEntity.available.
    """

    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_has_entity_name = True
    _attr_translation_key = "human_detection"

    def __init__(self, coordinator: ImouCoordinator, device_serial: str) -> None:
        """Initialise human detection binary sensor."""
        super().__init__(coordinator, device_serial, "human_detection")

    @property
    def is_on(self) -> bool | None:
        """Return True if a human was detected in the last poll window, None if unknown."""
        if self._device_serial not in (self.coordinator.data or {}):
            return None
        return self.device_data.human_detected
