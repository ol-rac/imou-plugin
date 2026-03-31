"""Tests for Imou binary sensor platform entities."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.core import HomeAssistant

from custom_components.imou_ha.binary_sensor import (
    ImouHumanDetectionSensor,
    ImouMotionSensor,
    ImouOnlineSensor,
)
from custom_components.imou_ha.coordinator import ImouCoordinator
from custom_components.imou_ha.models import DeviceStatus, ImouDeviceData

SERIAL = "ABC123DEF456"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_device(
    serial: str = SERIAL,
    status: DeviceStatus = DeviceStatus.ACTIVE,
    capabilities: set[str] | None = None,
    motion_detected: bool = False,
    human_detected: bool = False,
) -> ImouDeviceData:
    return ImouDeviceData(
        serial=serial,
        name="Test Camera",
        model="IPC-C22EP",
        firmware="2.840.0000000.28.R",
        status=status,
        capabilities=capabilities or {"Dormant", "CloseCamera"},
        motion_detected=motion_detected,
        human_detected=human_detected,
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


# ---------------------------------------------------------------------------
# ImouMotionSensor
# ---------------------------------------------------------------------------


class TestImouMotionSensor:
    """Tests for ImouMotionSensor — BinarySensorDeviceClass.MOTION (D-12)."""

    def _make_sensor(
        self,
        hass: HomeAssistant,
        status: DeviceStatus = DeviceStatus.ACTIVE,
        motion_detected: bool = False,
        serial: str = SERIAL,
    ) -> ImouMotionSensor:
        device = _make_device(
            serial=serial,
            status=status,
            capabilities={"MobileDetect"},
            motion_detected=motion_detected,
        )
        coordinator = _make_coordinator(hass, {serial: device})
        return ImouMotionSensor(coordinator, serial)

    def test_unique_id_format(self, hass: HomeAssistant) -> None:
        """unique_id must be imou_ha_{serial}_motion."""
        sensor = self._make_sensor(hass)
        assert sensor.unique_id == f"imou_ha_{SERIAL}_motion"

    def test_device_class_is_motion(self, hass: HomeAssistant) -> None:
        """Device class must be MOTION (D-12)."""
        sensor = self._make_sensor(hass)
        assert sensor._attr_device_class == BinarySensorDeviceClass.MOTION

    def test_translation_key_is_motion(self, hass: HomeAssistant) -> None:
        """Translation key must be 'motion' (D-12)."""
        sensor = self._make_sensor(hass)
        assert sensor._attr_translation_key == "motion"

    def test_is_on_true_when_motion_detected(self, hass: HomeAssistant) -> None:
        """is_on must be True when device.motion_detected is True."""
        sensor = self._make_sensor(hass, motion_detected=True)
        assert sensor.is_on is True

    def test_is_on_false_when_no_motion(self, hass: HomeAssistant) -> None:
        """is_on must be False when device.motion_detected is False."""
        sensor = self._make_sensor(hass, motion_detected=False)
        assert sensor.is_on is False

    def test_is_on_none_when_serial_missing(self, hass: HomeAssistant) -> None:
        """is_on must be None when serial is not in coordinator data."""
        device = _make_device(serial=SERIAL, capabilities={"MobileDetect"})
        coordinator = _make_coordinator(hass, {SERIAL: device})
        coordinator.data = {}
        sensor = ImouMotionSensor(coordinator, SERIAL)
        assert sensor.is_on is None

    def test_unavailable_when_sleeping(self, hass: HomeAssistant) -> None:
        """available must be False when device is SLEEPING (D-14)."""
        sensor = self._make_sensor(hass, status=DeviceStatus.SLEEPING)
        assert sensor.available is False

    def test_unavailable_when_offline(self, hass: HomeAssistant) -> None:
        """available must be False when device is OFFLINE (D-14)."""
        sensor = self._make_sensor(hass, status=DeviceStatus.OFFLINE)
        assert sensor.available is False

    def test_no_available_override(self, hass: HomeAssistant) -> None:
        """ImouMotionSensor must NOT define its own available property."""
        assert "available" not in ImouMotionSensor.__dict__


# ---------------------------------------------------------------------------
# ImouHumanDetectionSensor
# ---------------------------------------------------------------------------


class TestImouHumanDetectionSensor:
    """Tests for ImouHumanDetectionSensor — BinarySensorDeviceClass.MOTION (D-13)."""

    def _make_sensor(
        self,
        hass: HomeAssistant,
        status: DeviceStatus = DeviceStatus.ACTIVE,
        human_detected: bool = False,
        serial: str = SERIAL,
        capabilities: set[str] | None = None,
    ) -> ImouHumanDetectionSensor:
        device = _make_device(
            serial=serial,
            status=status,
            capabilities=capabilities or {"HeaderDetect"},
            human_detected=human_detected,
        )
        coordinator = _make_coordinator(hass, {serial: device})
        return ImouHumanDetectionSensor(coordinator, serial)

    def test_unique_id_format(self, hass: HomeAssistant) -> None:
        """unique_id must be imou_ha_{serial}_human_detection."""
        sensor = self._make_sensor(hass)
        assert sensor.unique_id == f"imou_ha_{SERIAL}_human_detection"

    def test_device_class_is_motion(self, hass: HomeAssistant) -> None:
        """Device class must be MOTION (D-13)."""
        sensor = self._make_sensor(hass)
        assert sensor._attr_device_class == BinarySensorDeviceClass.MOTION

    def test_translation_key_is_human_detection(self, hass: HomeAssistant) -> None:
        """Translation key must be 'human_detection' (D-13)."""
        sensor = self._make_sensor(hass)
        assert sensor._attr_translation_key == "human_detection"

    def test_is_on_true_when_human_detected(self, hass: HomeAssistant) -> None:
        """is_on must be True when device.human_detected is True."""
        sensor = self._make_sensor(hass, human_detected=True)
        assert sensor.is_on is True

    def test_is_on_false_when_no_human(self, hass: HomeAssistant) -> None:
        """is_on must be False when device.human_detected is False."""
        sensor = self._make_sensor(hass, human_detected=False)
        assert sensor.is_on is False

    def test_no_available_override(self, hass: HomeAssistant) -> None:
        """ImouHumanDetectionSensor must NOT define its own available property."""
        assert "available" not in ImouHumanDetectionSensor.__dict__


# ---------------------------------------------------------------------------
# TestBinarySensorSetup — async_setup_entry capability gating (D-06, D-07, D-08)
# ---------------------------------------------------------------------------


class TestBinarySensorSetup:
    """Tests for async_setup_entry gating of motion and human detection sensors."""

    async def _run_setup(
        self,
        hass: HomeAssistant,
        devices: dict[str, ImouDeviceData],
    ) -> list:
        """Run async_setup_entry and return the entities list passed to async_add_entities."""
        from custom_components.imou_ha.binary_sensor import async_setup_entry

        coordinator = _make_coordinator(hass, devices)
        entry = MagicMock()
        entry.runtime_data = coordinator

        added: list = []
        async_add = MagicMock(side_effect=lambda entities: added.extend(entities))

        await async_setup_entry(hass, entry, async_add)
        return added

    @pytest.mark.asyncio
    async def test_motion_sensor_created_for_mobile_detect(
        self, hass: HomeAssistant,
    ) -> None:
        """ImouMotionSensor is created for device with MobileDetect capability (D-06)."""
        device = _make_device(capabilities={"MobileDetect"})
        entities = await self._run_setup(hass, {SERIAL: device})
        types = [type(e) for e in entities]
        assert ImouMotionSensor in types

    @pytest.mark.asyncio
    async def test_motion_sensor_created_for_alarm_md(
        self, hass: HomeAssistant,
    ) -> None:
        """ImouMotionSensor is created for device with AlarmMD capability (D-06)."""
        device = _make_device(capabilities={"AlarmMD"})
        entities = await self._run_setup(hass, {SERIAL: device})
        types = [type(e) for e in entities]
        assert ImouMotionSensor in types

    @pytest.mark.asyncio
    async def test_motion_sensor_not_created_without_motion_caps(
        self, hass: HomeAssistant,
    ) -> None:
        """ImouMotionSensor is NOT created for device without motion capabilities (D-08)."""
        device = _make_device(capabilities={"CloseCamera", "Dormant"})
        entities = await self._run_setup(hass, {SERIAL: device})
        types = [type(e) for e in entities]
        assert ImouMotionSensor not in types

    @pytest.mark.asyncio
    async def test_human_sensor_created_for_header_detect(
        self, hass: HomeAssistant,
    ) -> None:
        """ImouHumanDetectionSensor is created for device with HeaderDetect capability (D-07)."""
        device = _make_device(capabilities={"HeaderDetect"})
        entities = await self._run_setup(hass, {SERIAL: device})
        types = [type(e) for e in entities]
        assert ImouHumanDetectionSensor in types

    @pytest.mark.asyncio
    async def test_human_sensor_created_for_ai_human(
        self, hass: HomeAssistant,
    ) -> None:
        """ImouHumanDetectionSensor is created for device with AiHuman capability (D-07)."""
        device = _make_device(capabilities={"AiHuman"})
        entities = await self._run_setup(hass, {SERIAL: device})
        types = [type(e) for e in entities]
        assert ImouHumanDetectionSensor in types

    @pytest.mark.asyncio
    async def test_human_sensor_created_for_smdh(
        self, hass: HomeAssistant,
    ) -> None:
        """ImouHumanDetectionSensor is created for device with SMDH capability (D-07)."""
        device = _make_device(capabilities={"SMDH"})
        entities = await self._run_setup(hass, {SERIAL: device})
        types = [type(e) for e in entities]
        assert ImouHumanDetectionSensor in types

    @pytest.mark.asyncio
    async def test_human_sensor_not_created_without_human_caps(
        self, hass: HomeAssistant,
    ) -> None:
        """ImouHumanDetectionSensor is NOT created for device without human detection caps (D-08)."""
        device = _make_device(capabilities={"MobileDetect"})
        entities = await self._run_setup(hass, {SERIAL: device})
        types = [type(e) for e in entities]
        assert ImouHumanDetectionSensor not in types
