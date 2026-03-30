"""Tests for imou_ha data models and exceptions."""

from datetime import datetime

import pytest

from custom_components.imou_ha.exceptions import (
    ImouAuthError,
    ImouDeviceOfflineError,
    ImouDeviceSleepingError,
    ImouError,
    ImouLicenseError,
    ImouRateLimitError,
)
from custom_components.imou_ha.models import (
    CommandState,
    DeviceStatus,
    ImouDeviceData,
)


class TestDeviceStatus:
    def test_active_value(self) -> None:
        assert DeviceStatus.ACTIVE == "active"

    def test_sleeping_value(self) -> None:
        assert DeviceStatus.SLEEPING == "sleeping"

    def test_offline_value(self) -> None:
        assert DeviceStatus.OFFLINE == "offline"

    def test_has_exactly_three_members(self) -> None:
        assert len(DeviceStatus) == 3


class TestCommandState:
    def test_all_values(self) -> None:
        expected = {"idle", "pending", "verifying", "confirmed", "failed", "timeout"}
        actual = {member.value for member in CommandState}
        assert actual == expected

    def test_has_exactly_six_members(self) -> None:
        assert len(CommandState) == 6


class TestImouDeviceData:
    def test_required_fields(self, sample_device_data: ImouDeviceData) -> None:
        assert sample_device_data.serial == "ABC123DEF456"
        assert sample_device_data.name == "Front Door Camera"
        assert sample_device_data.model == "IPC-C22EP"
        assert sample_device_data.firmware == "2.840.0000000.28.R"
        assert sample_device_data.status == DeviceStatus.ACTIVE

    def test_default_capabilities(self) -> None:
        device = ImouDeviceData(
            serial="X", name="X", model="X", firmware="X",
            status=DeviceStatus.ACTIVE,
        )
        assert device.capabilities == set()

    def test_default_battery_level_is_none(self) -> None:
        device = ImouDeviceData(
            serial="X", name="X", model="X", firmware="X",
            status=DeviceStatus.ACTIVE,
        )
        assert device.battery_level is None

    def test_default_battery_power_source_is_unknown(self) -> None:
        device = ImouDeviceData(
            serial="X", name="X", model="X", firmware="X",
            status=DeviceStatus.ACTIVE,
        )
        assert device.battery_power_source == "unknown"

    def test_default_privacy_enabled_is_none(self) -> None:
        device = ImouDeviceData(
            serial="X", name="X", model="X", firmware="X",
            status=DeviceStatus.ACTIVE,
        )
        assert device.privacy_enabled is None

    def test_default_motion_detected_is_false(self) -> None:
        device = ImouDeviceData(
            serial="X", name="X", model="X", firmware="X",
            status=DeviceStatus.ACTIVE,
        )
        assert device.motion_detected is False

    def test_default_human_detected_is_false(self) -> None:
        device = ImouDeviceData(
            serial="X", name="X", model="X", firmware="X",
            status=DeviceStatus.ACTIVE,
        )
        assert device.human_detected is False

    def test_last_updated_is_datetime(self) -> None:
        device = ImouDeviceData(
            serial="X", name="X", model="X", firmware="X",
            status=DeviceStatus.ACTIVE,
        )
        assert isinstance(device.last_updated, datetime)

    def test_capabilities_accepts_dormant(self, sample_device_data: ImouDeviceData) -> None:
        assert "Dormant" in sample_device_data.capabilities

    def test_capabilities_is_set_type(self, sample_device_data: ImouDeviceData) -> None:
        assert isinstance(sample_device_data.capabilities, set)


class TestExceptionHierarchy:
    @pytest.mark.parametrize(
        "exc_class",
        [
            ImouAuthError,
            ImouDeviceSleepingError,
            ImouLicenseError,
            ImouRateLimitError,
            ImouDeviceOfflineError,
        ],
    )
    def test_subclass_of_imou_error(self, exc_class: type) -> None:
        assert issubclass(exc_class, ImouError)

    @pytest.mark.parametrize(
        "exc_class",
        [
            ImouAuthError,
            ImouDeviceSleepingError,
            ImouLicenseError,
            ImouRateLimitError,
            ImouDeviceOfflineError,
        ],
    )
    def test_catchable_as_imou_error(self, exc_class: type) -> None:
        with pytest.raises(ImouError):
            raise exc_class("test")

    def test_imou_error_is_base_exception(self) -> None:
        assert issubclass(ImouError, Exception)
