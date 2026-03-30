"""Sensor platform for the Imou integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.components.sensor import RestoreSensor
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CAPABILITY_ELECTRIC, DOMAIN
from .entity import ImouEntity
from .models import DeviceStatus

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .coordinator import ImouCoordinator, ImouHaConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ImouHaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Imou sensor entities from a config entry."""
    coordinator: ImouCoordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for serial, device in coordinator.data.items():
        entities.append(ImouDeviceStateSensor(coordinator, serial))
        if CAPABILITY_ELECTRIC in device.capabilities:
            entities.append(ImouBatterySensor(coordinator, serial))
    async_add_entities(entities)


class ImouDeviceStateSensor(ImouEntity, SensorEntity):
    """Sensor that reports device state: active, sleeping, or offline.

    Always remains available (D-12) — shows the real state even when sleeping/offline.
    This is the one entity that never goes unavailable for sleep/offline.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["active", "sleeping", "offline"]
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "device_state"

    def __init__(self, coordinator: ImouCoordinator, device_serial: str) -> None:
        """Initialise device state sensor."""
        super().__init__(coordinator, device_serial, "device_state")

    @property
    def native_value(self) -> str:
        """Return current device state as string."""
        return self.device_data.status.value

    @property
    def available(self) -> bool:
        """Always available when device serial is in coordinator data (D-12).

        Overrides base ImouEntity.available which returns False for sleeping/offline.
        Device state sensor must always show the real state, never go unavailable.
        """
        return self._device_serial in (self.coordinator.data or {})


class ImouBatterySensor(ImouEntity, RestoreSensor):
    """Sensor that reports battery level for Electric-capable devices.

    Goes unavailable when device is sleeping/offline (D-11).
    Restores last known value on HA restart (STATE-06).
    Exposes battery_power_source as an extra state attribute (STATE-04).
    """

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True
    _attr_translation_key = "battery"

    def __init__(self, coordinator: ImouCoordinator, device_serial: str) -> None:
        """Initialise battery sensor."""
        super().__init__(coordinator, device_serial, "battery")

    async def async_added_to_hass(self) -> None:
        """Restore last known battery value on startup (STATE-06).

        Must call super() first to register coordinator listener and restore mechanism
        (Pitfall 3 — both CoordinatorEntity and RestoreSensor register in super).
        """
        await super().async_added_to_hass()
        if (last_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last_data.native_value

    @property
    def native_value(self) -> int | None:
        """Return current battery level (0-100) or None if unknown."""
        return self.device_data.battery_level

    @property
    def available(self) -> bool:
        """Available only when device is active (D-11).

        Battery data is only reliable when device is awake and reporting.
        """
        return (
            self._device_serial in (self.coordinator.data or {})
            and self.device_data.status == DeviceStatus.ACTIVE
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes including battery_power_source (STATE-04)."""
        attrs = super().extra_state_attributes
        attrs["battery_power_source"] = self.device_data.battery_power_source
        return attrs
