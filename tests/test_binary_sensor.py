"""Tests for Imou binary sensor platform entities."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.core import HomeAssistant

from custom_components.imou_ha.coordinator import ImouCoordinator
from custom_components.imou_ha.models import DeviceStatus, ImouDeviceData
from custom_components.imou_ha.binary_sensor import ImouOnlineSensor

SERIAL = "ABC123DEF456"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_device(
    serial: str = SERIAL,
    status: DeviceStatus = DeviceStatus.ACTIVE,
    capabilities: set[str] | None = None,
) -> ImouDeviceData:
    return ImouDeviceData(
        serial=serial,
        name="Test Camera",
        model="IPC-C22EP",
        firmware="2.840.0000000.28.R",
        status=status,
        capabilities=capabilities or {"Dormant", "closedCamera"},
    )


def _make_coordinator(
    hass: HomeAssistant,
    devices: dict[str, ImouDeviceData],
) -> ImouCoordinator:
    client = AsyncMock()
    client.async_get_devices = AsyncMock(return_value=devices)
    client.async_get_device_online_status = AsyncMock(return_value=DeviceStatus.ACTIVE)
    client.async_get_device_power_info = AsyncMock(return_value=(85, "battery"))
    coordinator = ImouCoordinator(hass, client)
    coordinator.data = devices
    return coordinator


# ---------------------------------------------------------------------------
# ImouOnlineSensor
# ---------------------------------------------------------------------------


class TestImouOnlineSensor:
    """Tests for ImouOnlineSensor — BinarySensorDeviceClass.CONNECTIVITY."""

    def _make_sensor(
        self,
        hass: HomeAssistant,
        status: DeviceStatus = DeviceStatus.ACTIVE,
        serial: str = SERIAL,
    ) -> ImouOnlineSensor:
        device = _make_device(serial=serial, status=status)
        coordinator = _make_coordinator(hass, {serial: device})
        return ImouOnlineSensor(coordinator, serial)

    def test_unique_id_format(self, hass: HomeAssistant) -> None:
        """unique_id must use imou_ha_{serial}_{entity_type} format (INFR-06)."""
        sensor = self._make_sensor(hass)
        assert sensor.unique_id == f"imou_ha_{SERIAL}_online"

    def test_device_class_is_connectivity(self, hass: HomeAssistant) -> None:
        """Device class must be CONNECTIVITY (STATE-05)."""
        sensor = self._make_sensor(hass)
        assert sensor._attr_device_class == BinarySensorDeviceClass.CONNECTIVITY

    def test_is_on_when_active(self, hass: HomeAssistant) -> None:
        """is_on must be True when device status is ACTIVE (STATE-05)."""
        sensor = self._make_sensor(hass, status=DeviceStatus.ACTIVE)
        assert sensor.is_on is True

    def test_is_on_false_when_sleeping(self, hass: HomeAssistant) -> None:
        """is_on must be False when device status is SLEEPING."""
        sensor = self._make_sensor(hass, status=DeviceStatus.SLEEPING)
        assert sensor.is_on is False

    def test_is_on_false_when_offline(self, hass: HomeAssistant) -> None:
        """is_on must be False when device status is OFFLINE."""
        sensor = self._make_sensor(hass, status=DeviceStatus.OFFLINE)
        assert sensor.is_on is False

    def test_is_on_none_when_serial_missing(self, hass: HomeAssistant) -> None:
        """is_on must be None when serial is not in coordinator data."""
        device = _make_device(serial=SERIAL, status=DeviceStatus.ACTIVE)
        coordinator = _make_coordinator(hass, {SERIAL: device})
        # Remove serial from data
        coordinator.data = {}
        sensor = ImouOnlineSensor(coordinator, SERIAL)
        assert sensor.is_on is None

    def test_available_when_active(self, hass: HomeAssistant) -> None:
        """available must be True when device is ACTIVE."""
        sensor = self._make_sensor(hass, status=DeviceStatus.ACTIVE)
        assert sensor.available is True

    def test_unavailable_when_sleeping(self, hass: HomeAssistant) -> None:
        """available must be False when device is SLEEPING (D-11).

        Base ImouEntity.available returns False for sleeping devices.
        Online sensor does not override this — intentional per D-11.
        """
        sensor = self._make_sensor(hass, status=DeviceStatus.SLEEPING)
        assert sensor.available is False

    def test_unavailable_when_offline(self, hass: HomeAssistant) -> None:
        """available must be False when device is OFFLINE (D-11, D-13).

        Base ImouEntity.available returns False for offline devices.
        Online sensor does not override this — intentional per D-11.
        """
        sensor = self._make_sensor(hass, status=DeviceStatus.OFFLINE)
        assert sensor.available is False
