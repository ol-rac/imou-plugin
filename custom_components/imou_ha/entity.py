"""ImouEntity — base entity class for all Imou devices."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ImouCoordinator

if TYPE_CHECKING:
    from .models import ImouDeviceData


class ImouEntity(CoordinatorEntity[ImouCoordinator]):
    """Base entity class for all Imou camera entities.

    Provides:
    - Stable unique_id in format ``imou_ha_{serial}_{entity_type}`` (INFR-06).
    - device_info with manufacturer="Imou", model, firmware, and HA device identifiers.
    - available: False when the device serial is no longer in coordinator data.
    """

    def __init__(
        self,
        coordinator: ImouCoordinator,
        device_serial: str,
        entity_type: str,
    ) -> None:
        """Initialise entity with coordinator, device serial, and entity type."""
        super().__init__(coordinator)
        self._device_serial = device_serial
        self._entity_type = entity_type

    @property
    def device_data(self) -> ImouDeviceData:
        """Return the device data for this entity's device."""
        return self.coordinator.data[self._device_serial]

    @property
    def device_info(self) -> DeviceInfo:
        """Return HA device registry information for this device."""
        device = self.device_data
        return DeviceInfo(
            identifiers={(DOMAIN, device.serial)},
            name=device.name,
            manufacturer="Imou",
            model=device.model,
            sw_version=device.firmware,
        )

    @property
    def unique_id(self) -> str:
        """Return stable unique identifier (INFR-06)."""
        return f"imou_ha_{self._device_serial}_{self._entity_type}"

    @property
    def available(self) -> bool:
        """Return True only when device serial is present in coordinator data."""
        return self._device_serial in (self.coordinator.data or {})
