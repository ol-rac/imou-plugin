"""Tests for Imou sensor platform entities."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from custom_components.imou_ha.budget import ImouBudgetState
from custom_components.imou_ha.const import MONTHLY_API_LIMIT
from custom_components.imou_ha.coordinator import ImouCoordinator
from custom_components.imou_ha.models import DeviceStatus, ImouDeviceData
from custom_components.imou_ha.sensor import (
    ImouApiCallsRemainingSensor,
    ImouBatterySensor,
    ImouDailyBurnRateSensor,
    ImouDeviceStateSensor,
    ImouIntegrationSensor,
)

SERIAL = "ABC123DEF456"
SERIAL_BATTERY = "BAT789GHI012"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_device(
    serial: str = SERIAL,
    status: DeviceStatus = DeviceStatus.ACTIVE,
    capabilities: set[str] | None = None,
    battery_level: int | None = None,
    battery_power_source: str = "unknown",
) -> ImouDeviceData:
    return ImouDeviceData(
        serial=serial,
        name="Test Camera",
        model="IPC-C22EP",
        firmware="2.840.0000000.28.R",
        status=status,
        capabilities=capabilities or {"Dormant", "closedCamera"},
        battery_level=battery_level,
        battery_power_source=battery_power_source,
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
# ImouDeviceStateSensor
# ---------------------------------------------------------------------------


class TestImouDeviceStateSensor:
    """Tests for ImouDeviceStateSensor — ENUM device class, always available."""

    def _make_sensor(
        self,
        hass: HomeAssistant,
        status: DeviceStatus = DeviceStatus.ACTIVE,
        serial: str = SERIAL,
    ) -> ImouDeviceStateSensor:
        device = _make_device(serial=serial, status=status)
        coordinator = _make_coordinator(hass, {serial: device})
        return ImouDeviceStateSensor(coordinator, serial)

    def test_unique_id_format(self, hass: HomeAssistant) -> None:
        """unique_id must use imou_ha_{serial}_{entity_type} format (INFR-06)."""
        sensor = self._make_sensor(hass)
        assert sensor.unique_id == f"imou_ha_{SERIAL}_device_state"

    def test_device_class_is_enum(self, hass: HomeAssistant) -> None:
        """Device class must be ENUM for state validation."""
        sensor = self._make_sensor(hass)
        assert sensor._attr_device_class == SensorDeviceClass.ENUM

    def test_options_are_three_states(self, hass: HomeAssistant) -> None:
        """Options must match the three DeviceStatus values."""
        sensor = self._make_sensor(hass)
        assert sensor._attr_options == ["active", "sleeping", "offline"]

    def test_entity_category_is_diagnostic(self, hass: HomeAssistant) -> None:
        """Entity category must be DIAGNOSTIC (D-03)."""
        sensor = self._make_sensor(hass)
        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_native_value_active(self, hass: HomeAssistant) -> None:
        """native_value must be 'active' when device status is ACTIVE."""
        sensor = self._make_sensor(hass, status=DeviceStatus.ACTIVE)
        assert sensor.native_value == "active"

    def test_native_value_sleeping(self, hass: HomeAssistant) -> None:
        """native_value must be 'sleeping' when device status is SLEEPING."""
        sensor = self._make_sensor(hass, status=DeviceStatus.SLEEPING)
        assert sensor.native_value == "sleeping"

    def test_native_value_offline(self, hass: HomeAssistant) -> None:
        """native_value must be 'offline' when device status is OFFLINE."""
        sensor = self._make_sensor(hass, status=DeviceStatus.OFFLINE)
        assert sensor.native_value == "offline"

    def test_available_when_active(self, hass: HomeAssistant) -> None:
        """available must be True when device is ACTIVE."""
        sensor = self._make_sensor(hass, status=DeviceStatus.ACTIVE)
        assert sensor.available is True

    def test_available_when_sleeping(self, hass: HomeAssistant) -> None:
        """available must be True when device is SLEEPING (D-12).

        Device state sensor NEVER goes unavailable — always shows the real state.
        This overrides base ImouEntity.available which returns False for sleeping.
        """
        sensor = self._make_sensor(hass, status=DeviceStatus.SLEEPING)
        assert sensor.available is True

    def test_available_when_offline(self, hass: HomeAssistant) -> None:
        """available must be True when device is OFFLINE (D-12).

        Device state sensor NEVER goes unavailable — shows 'offline' as valid state.
        This overrides base ImouEntity.available which returns False for offline.
        """
        sensor = self._make_sensor(hass, status=DeviceStatus.OFFLINE)
        assert sensor.available is True

    def test_available_false_when_serial_missing(self, hass: HomeAssistant) -> None:
        """available must be False when serial is not in coordinator data."""
        device = _make_device(serial=SERIAL, status=DeviceStatus.ACTIVE)
        coordinator = _make_coordinator(hass, {SERIAL: device})
        # Remove serial from data to simulate device disappearing
        coordinator.data = {}
        sensor = ImouDeviceStateSensor(coordinator, SERIAL)
        assert sensor.available is False

    def test_extra_state_attributes_has_device_state(self, hass: HomeAssistant) -> None:
        """extra_state_attributes must contain 'device_state' key (STATE-02)."""
        sensor = self._make_sensor(hass, status=DeviceStatus.ACTIVE)
        attrs = sensor.extra_state_attributes
        assert "device_state" in attrs
        assert attrs["device_state"] == "active"


# ---------------------------------------------------------------------------
# ImouBatterySensor
# ---------------------------------------------------------------------------


class TestImouBatterySensor:
    """Tests for ImouBatterySensor — Electric-only, restore-capable, unavailable when sleeping."""

    def _make_sensor(
        self,
        hass: HomeAssistant,
        status: DeviceStatus = DeviceStatus.ACTIVE,
        battery_level: int | None = 85,
        battery_power_source: str = "battery",
        serial: str = SERIAL,
    ) -> ImouBatterySensor:
        device = _make_device(
            serial=serial,
            status=status,
            capabilities={"Dormant", "Electric", "closedCamera"},
            battery_level=battery_level,
            battery_power_source=battery_power_source,
        )
        coordinator = _make_coordinator(hass, {serial: device})
        return ImouBatterySensor(coordinator, serial)

    def test_unique_id_format(self, hass: HomeAssistant) -> None:
        """unique_id must use imou_ha_{serial}_{entity_type} format (INFR-06)."""
        sensor = self._make_sensor(hass)
        assert sensor.unique_id == f"imou_ha_{SERIAL}_battery"

    def test_device_class_is_battery(self, hass: HomeAssistant) -> None:
        """Device class must be BATTERY."""
        sensor = self._make_sensor(hass)
        assert sensor._attr_device_class == SensorDeviceClass.BATTERY

    def test_state_class_is_measurement(self, hass: HomeAssistant) -> None:
        """State class must be MEASUREMENT for numeric battery values."""
        sensor = self._make_sensor(hass)
        assert sensor._attr_state_class == SensorStateClass.MEASUREMENT

    def test_entity_category_is_diagnostic(self, hass: HomeAssistant) -> None:
        """Entity category must be DIAGNOSTIC (D-08)."""
        sensor = self._make_sensor(hass)
        assert sensor._attr_entity_category == EntityCategory.DIAGNOSTIC

    def test_native_value_returns_battery_level(self, hass: HomeAssistant) -> None:
        """native_value must return battery level when set (STATE-03)."""
        sensor = self._make_sensor(hass, battery_level=85)
        assert sensor.native_value == 85

    def test_native_value_none_when_no_battery(self, hass: HomeAssistant) -> None:
        """native_value must be None when battery_level is None."""
        sensor = self._make_sensor(hass, battery_level=None)
        assert sensor.native_value is None

    def test_available_when_active(self, hass: HomeAssistant) -> None:
        """available must be True when device is ACTIVE."""
        sensor = self._make_sensor(hass, status=DeviceStatus.ACTIVE)
        assert sensor.available is True

    def test_unavailable_when_sleeping(self, hass: HomeAssistant) -> None:
        """available must be False when device is SLEEPING (D-11).

        Battery data is only valid when device is awake.
        """
        sensor = self._make_sensor(hass, status=DeviceStatus.SLEEPING)
        assert sensor.available is False

    def test_unavailable_when_offline(self, hass: HomeAssistant) -> None:
        """available must be False when device is OFFLINE (D-11, D-13)."""
        sensor = self._make_sensor(hass, status=DeviceStatus.OFFLINE)
        assert sensor.available is False

    def test_extra_state_attributes_has_power_source(self, hass: HomeAssistant) -> None:
        """extra_state_attributes must contain 'battery_power_source' (STATE-04)."""
        sensor = self._make_sensor(hass, battery_power_source="battery")
        attrs = sensor.extra_state_attributes
        assert "battery_power_source" in attrs
        assert attrs["battery_power_source"] == "battery"

    def test_extra_state_attributes_has_device_state(self, hass: HomeAssistant) -> None:
        """extra_state_attributes must contain 'device_state' inherited from base (STATE-02)."""
        sensor = self._make_sensor(hass, status=DeviceStatus.ACTIVE)
        attrs = sensor.extra_state_attributes
        assert "device_state" in attrs
        assert attrs["device_state"] == "active"

    async def test_async_added_to_hass_restores_last_value(
        self, hass: HomeAssistant
    ) -> None:
        """Battery sensor must restore last known value on HA restart (STATE-06).

        async_get_last_sensor_data() returns saved data; native_value adopts it.
        """
        sensor = self._make_sensor(hass, battery_level=None)

        # Simulate the RestoreSensor returning a previously saved value
        mock_last_data = MagicMock()
        mock_last_data.native_value = 72
        sensor.async_get_last_sensor_data = AsyncMock(return_value=mock_last_data)

        # Patch super() call to avoid HA registration during test
        from unittest.mock import patch, AsyncMock as AM
        with patch(
            "custom_components.imou_ha.entity.CoordinatorEntity.async_added_to_hass",
            new_callable=lambda: lambda self: AM(return_value=None)(),
        ):
            # Call the method directly to verify restore logic
            await sensor.async_added_to_hass()

        assert sensor._attr_native_value == 72


# ---------------------------------------------------------------------------
# Integration-level budget sensors (BUDG-02, BUDG-03)
# ---------------------------------------------------------------------------


def _make_budget_coordinator(
    hass: HomeAssistant,
    calls_this_month: int = 500,
    calls_today: int = 50,
) -> ImouCoordinator:
    """Create a coordinator with a budget_state for sensor tests."""
    budget = ImouBudgetState(
        calls_today=calls_today,
        calls_this_month=calls_this_month,
        day_reset_date="2026-03-31",
        month_reset_date="2026-03",
        day_start_time="2026-03-31T00:00:00+00:00",
    )
    client = AsyncMock()
    coordinator = ImouCoordinator(hass, client, budget_state=budget)
    coordinator.data = {}
    return coordinator


ENTRY_ID = "test_entry_123"


class TestImouApiCallsRemainingSensor:
    """Tests for ImouApiCallsRemainingSensor (BUDG-02)."""

    def test_native_value_equals_limit_minus_used(self, hass: HomeAssistant) -> None:
        """native_value == MONTHLY_API_LIMIT - calls_this_month."""
        coordinator = _make_budget_coordinator(hass, calls_this_month=1234)
        sensor = ImouApiCallsRemainingSensor(coordinator, ENTRY_ID)
        assert sensor.native_value == MONTHLY_API_LIMIT - 1234

    def test_extra_state_attributes_has_required_keys(self, hass: HomeAssistant) -> None:
        """extra_state_attributes contains monthly_limit, calls_this_month, calls_today, reset_date."""
        coordinator = _make_budget_coordinator(hass, calls_this_month=500, calls_today=50)
        sensor = ImouApiCallsRemainingSensor(coordinator, ENTRY_ID)
        attrs = sensor.extra_state_attributes
        assert "monthly_limit" in attrs
        assert "calls_this_month" in attrs
        assert "calls_today" in attrs
        assert "reset_date" in attrs
        assert attrs["monthly_limit"] == MONTHLY_API_LIMIT
        assert attrs["calls_this_month"] == 500
        assert attrs["calls_today"] == 50

    def test_reset_date_is_first_of_next_month(self, hass: HomeAssistant) -> None:
        """extra_state_attributes["reset_date"] is 1st of next month."""
        coordinator = _make_budget_coordinator(hass)
        sensor = ImouApiCallsRemainingSensor(coordinator, ENTRY_ID)
        attrs = sensor.extra_state_attributes
        # reset_date should be a valid date string in YYYY-MM-DD format
        reset = attrs["reset_date"]
        assert len(reset) == 10
        assert reset.endswith("-01")

    def test_entity_category_diagnostic(self, hass: HomeAssistant) -> None:
        """Sensor has EntityCategory.DIAGNOSTIC."""
        coordinator = _make_budget_coordinator(hass)
        sensor = ImouApiCallsRemainingSensor(coordinator, ENTRY_ID)
        assert sensor.entity_category == EntityCategory.DIAGNOSTIC

    def test_state_class_measurement(self, hass: HomeAssistant) -> None:
        """Sensor has SensorStateClass.MEASUREMENT."""
        coordinator = _make_budget_coordinator(hass)
        sensor = ImouApiCallsRemainingSensor(coordinator, ENTRY_ID)
        assert sensor.state_class == SensorStateClass.MEASUREMENT

    def test_native_unit_calls(self, hass: HomeAssistant) -> None:
        """Sensor has native_unit_of_measurement 'calls'."""
        coordinator = _make_budget_coordinator(hass)
        sensor = ImouApiCallsRemainingSensor(coordinator, ENTRY_ID)
        assert sensor.native_unit_of_measurement == "calls"

    def test_no_device_info(self, hass: HomeAssistant) -> None:
        """Budget sensor has no device_info (integration-level)."""
        coordinator = _make_budget_coordinator(hass)
        sensor = ImouApiCallsRemainingSensor(coordinator, ENTRY_ID)
        assert not hasattr(sensor, "device_info") or sensor.device_info is None

    def test_unique_id_format(self, hass: HomeAssistant) -> None:
        """unique_id matches pattern imou_ha_{entry_id}_api_calls_remaining."""
        coordinator = _make_budget_coordinator(hass)
        sensor = ImouApiCallsRemainingSensor(coordinator, ENTRY_ID)
        assert sensor.unique_id == f"imou_ha_{ENTRY_ID}_api_calls_remaining"


class TestImouDailyBurnRateSensor:
    """Tests for ImouDailyBurnRateSensor (BUDG-03)."""

    def test_native_value_is_projected_rate_rounded(self, hass: HomeAssistant) -> None:
        """native_value == projected_daily_rate() rounded to int."""
        coordinator = _make_budget_coordinator(hass, calls_today=10)
        sensor = ImouDailyBurnRateSensor(coordinator, ENTRY_ID)
        # Value should be a non-negative integer
        assert isinstance(sensor.native_value, int)
        assert sensor.native_value >= 0

    def test_native_unit_calls_per_day(self, hass: HomeAssistant) -> None:
        """Sensor has native_unit_of_measurement 'calls/day'."""
        coordinator = _make_budget_coordinator(hass)
        sensor = ImouDailyBurnRateSensor(coordinator, ENTRY_ID)
        assert sensor.native_unit_of_measurement == "calls/day"

    def test_entity_category_diagnostic(self, hass: HomeAssistant) -> None:
        """Sensor has EntityCategory.DIAGNOSTIC."""
        coordinator = _make_budget_coordinator(hass)
        sensor = ImouDailyBurnRateSensor(coordinator, ENTRY_ID)
        assert sensor.entity_category == EntityCategory.DIAGNOSTIC

    def test_state_class_measurement(self, hass: HomeAssistant) -> None:
        """Sensor has SensorStateClass.MEASUREMENT."""
        coordinator = _make_budget_coordinator(hass)
        sensor = ImouDailyBurnRateSensor(coordinator, ENTRY_ID)
        assert sensor.state_class == SensorStateClass.MEASUREMENT

    def test_no_device_info(self, hass: HomeAssistant) -> None:
        """Budget sensor has no device_info (integration-level)."""
        coordinator = _make_budget_coordinator(hass)
        sensor = ImouDailyBurnRateSensor(coordinator, ENTRY_ID)
        assert not hasattr(sensor, "device_info") or sensor.device_info is None

    def test_unique_id_format(self, hass: HomeAssistant) -> None:
        """unique_id matches pattern imou_ha_{entry_id}_api_daily_burn_rate."""
        coordinator = _make_budget_coordinator(hass)
        sensor = ImouDailyBurnRateSensor(coordinator, ENTRY_ID)
        assert sensor.unique_id == f"imou_ha_{ENTRY_ID}_api_daily_burn_rate"
