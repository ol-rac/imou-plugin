"""Tests for ImouCoordinator and ImouEntity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.imou_ha.const import SLEEP_CHECK_INTERVAL
from custom_components.imou_ha.coordinator import ImouCoordinator
from custom_components.imou_ha.entity import ImouEntity
from custom_components.imou_ha.exceptions import ImouAuthError, ImouDeviceOfflineError, ImouDeviceSleepingError, ImouError
from custom_components.imou_ha.models import DeviceStatus, ImouDeviceData

SERIAL = "ABC123DEF456"
DOMAIN = "imou_ha"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_device_data(
    serial: str = SERIAL,
    status: DeviceStatus = DeviceStatus.ACTIVE,
    capabilities: set[str] | None = None,
) -> ImouDeviceData:
    return ImouDeviceData(
        serial=serial,
        name="Front Door Camera",
        model="IPC-C22EP",
        firmware="2.840.0000000.28.R",
        status=status,
        capabilities=capabilities or {"Dormant", "closedCamera"},
    )


def _make_mock_client(devices: dict[str, ImouDeviceData] | None = None) -> AsyncMock:
    client = AsyncMock()
    if devices is None:
        devices = {SERIAL: _make_device_data()}
    client.async_get_devices = AsyncMock(return_value=devices)
    client.async_get_device_online_status = AsyncMock(return_value=DeviceStatus.ACTIVE)
    client.async_get_device_power_info = AsyncMock(return_value=(85, "battery"))
    return client


# ---------------------------------------------------------------------------
# ImouCoordinator — _async_setup
# ---------------------------------------------------------------------------


class TestImouCoordinatorSetup:
    async def test_async_setup_populates_data(self, hass: HomeAssistant) -> None:
        """_async_setup must populate coordinator.data with discovered devices."""
        client = _make_mock_client()
        coordinator = ImouCoordinator(hass, client)

        await coordinator._async_setup()

        assert coordinator.data is not None
        assert SERIAL in coordinator.data
        assert isinstance(coordinator.data[SERIAL], ImouDeviceData)

    async def test_async_setup_discovers_device_fields(self, hass: HomeAssistant) -> None:
        """Discovered device must have all ImouDeviceData fields populated."""
        device = _make_device_data()
        client = _make_mock_client({SERIAL: device})
        coordinator = ImouCoordinator(hass, client)

        await coordinator._async_setup()

        result = coordinator.data[SERIAL]
        assert result.serial == SERIAL
        assert result.name == "Front Door Camera"
        assert result.model == "IPC-C22EP"
        assert result.firmware == "2.840.0000000.28.R"

    async def test_dormant_device_present_in_data(self, hass: HomeAssistant) -> None:
        """Device with Dormant capability must be present in coordinator data (DISC-04)."""
        device = _make_device_data(
            status=DeviceStatus.SLEEPING,
            capabilities={"Dormant"},
        )
        client = _make_mock_client({SERIAL: device})
        coordinator = ImouCoordinator(hass, client)

        await coordinator._async_setup()

        assert SERIAL in coordinator.data
        assert "Dormant" in coordinator.data[SERIAL].capabilities

    async def test_auth_error_in_setup_raises_config_entry_auth_failed(
        self, hass: HomeAssistant
    ) -> None:
        """ImouAuthError during _async_setup must raise ConfigEntryAuthFailed."""
        client = _make_mock_client()
        client.async_get_devices = AsyncMock(
            side_effect=ImouAuthError("invalid credentials")
        )
        coordinator = ImouCoordinator(hass, client)

        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_setup()

    async def test_imou_error_in_setup_raises_update_failed(
        self, hass: HomeAssistant
    ) -> None:
        """ImouError during _async_setup must raise UpdateFailed (never crashes HA — NFR1)."""
        client = _make_mock_client()
        client.async_get_devices = AsyncMock(
            side_effect=ImouError("cloud unreachable")
        )
        coordinator = ImouCoordinator(hass, client)

        with pytest.raises(UpdateFailed):
            await coordinator._async_setup()


# ---------------------------------------------------------------------------
# ImouCoordinator — _async_update_data
# ---------------------------------------------------------------------------


class TestImouCoordinatorUpdate:
    async def test_update_data_returns_existing_data(self, hass: HomeAssistant) -> None:
        """_async_update_data must return the data set by _async_setup."""
        client = _make_mock_client()
        coordinator = ImouCoordinator(hass, client)

        await coordinator._async_setup()
        data_before = coordinator.data

        # _async_update_data returns existing data unchanged in Phase 1
        result = await coordinator._async_update_data()
        assert result == data_before

    async def test_update_returns_empty_dict_when_no_data(self, hass: HomeAssistant) -> None:
        """_async_update_data must not crash when data is None/empty."""
        client = _make_mock_client({})
        coordinator = ImouCoordinator(hass, client)
        # Manually set data to None to test the safety fallback
        coordinator.data = None  # type: ignore[assignment]
        result = await coordinator._async_update_data()
        assert result == {}


# ---------------------------------------------------------------------------
# ImouEntity
# ---------------------------------------------------------------------------


class TestImouEntity:
    def _make_coordinator_with_data(
        self, hass: HomeAssistant, devices: dict[str, ImouDeviceData]
    ) -> ImouCoordinator:
        client = _make_mock_client(devices)
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = devices
        return coordinator

    async def test_unique_id_format(self, hass: HomeAssistant) -> None:
        """unique_id must follow imou_ha_{serial}_{entity_type} format (INFR-06)."""
        coordinator = self._make_coordinator_with_data(hass, {SERIAL: _make_device_data()})
        entity = ImouEntity(coordinator, SERIAL, "camera")
        assert entity.unique_id == f"imou_ha_{SERIAL}_camera"

    async def test_device_info_manufacturer_is_imou(self, hass: HomeAssistant) -> None:
        """device_info must return manufacturer='Imou' (DISC-02)."""
        coordinator = self._make_coordinator_with_data(hass, {SERIAL: _make_device_data()})
        entity = ImouEntity(coordinator, SERIAL, "camera")
        info = entity.device_info
        assert isinstance(info, dict)
        assert info["manufacturer"] == "Imou"

    async def test_device_info_identifiers(self, hass: HomeAssistant) -> None:
        """device_info identifiers must use DOMAIN and device serial."""
        coordinator = self._make_coordinator_with_data(hass, {SERIAL: _make_device_data()})
        entity = ImouEntity(coordinator, SERIAL, "camera")
        info = entity.device_info
        assert (DOMAIN, SERIAL) in info["identifiers"]

    async def test_device_info_model_and_firmware(self, hass: HomeAssistant) -> None:
        """device_info must include model and sw_version from device data."""
        coordinator = self._make_coordinator_with_data(hass, {SERIAL: _make_device_data()})
        entity = ImouEntity(coordinator, SERIAL, "camera")
        info = entity.device_info
        assert info["model"] == "IPC-C22EP"
        assert info["sw_version"] == "2.840.0000000.28.R"

    async def test_available_true_when_serial_in_data(self, hass: HomeAssistant) -> None:
        """available must return True when device serial is in coordinator data."""
        coordinator = self._make_coordinator_with_data(hass, {SERIAL: _make_device_data()})
        entity = ImouEntity(coordinator, SERIAL, "camera")
        assert entity.available is True

    async def test_available_false_when_serial_not_in_data(self, hass: HomeAssistant) -> None:
        """available must return False when device serial is not in coordinator data."""
        coordinator = self._make_coordinator_with_data(hass, {SERIAL: _make_device_data()})
        entity = ImouEntity(coordinator, "UNKNOWN_SERIAL", "camera")
        assert entity.available is False

    async def test_available_false_when_data_is_empty(self, hass: HomeAssistant) -> None:
        """available must handle empty coordinator data gracefully."""
        coordinator = self._make_coordinator_with_data(hass, {})
        entity = ImouEntity(coordinator, SERIAL, "camera")
        assert entity.available is False

    async def test_device_data_returns_correct_device(self, hass: HomeAssistant) -> None:
        """device_data must return the ImouDeviceData for the entity's serial."""
        device = _make_device_data()
        coordinator = self._make_coordinator_with_data(hass, {SERIAL: device})
        entity = ImouEntity(coordinator, SERIAL, "camera")
        assert entity.device_data is device

    async def test_available_false_when_device_sleeping(self, hass: HomeAssistant) -> None:
        """available must return False when device status is SLEEPING (D-11)."""
        device = _make_device_data(status=DeviceStatus.SLEEPING)
        coordinator = self._make_coordinator_with_data(hass, {SERIAL: device})
        entity = ImouEntity(coordinator, SERIAL, "camera")
        assert entity.available is False

    async def test_available_false_when_device_offline(self, hass: HomeAssistant) -> None:
        """available must return False when device status is OFFLINE (D-11)."""
        device = _make_device_data(status=DeviceStatus.OFFLINE)
        coordinator = self._make_coordinator_with_data(hass, {SERIAL: device})
        entity = ImouEntity(coordinator, SERIAL, "camera")
        assert entity.available is False

    async def test_extra_state_attributes_has_device_state(self, hass: HomeAssistant) -> None:
        """extra_state_attributes must include device_state key (D-01, STATE-02)."""
        device = _make_device_data(status=DeviceStatus.ACTIVE)
        coordinator = self._make_coordinator_with_data(hass, {SERIAL: device})
        entity = ImouEntity(coordinator, SERIAL, "camera")
        attrs = entity.extra_state_attributes
        assert "device_state" in attrs
        assert attrs["device_state"] == "active"


# ---------------------------------------------------------------------------
# ImouCoordinator — sleep-aware polling (POLL-01 through POLL-04)
# ---------------------------------------------------------------------------


class TestCoordinatorSleepSkip:
    """POLL-01: Sleeping devices are skipped during poll."""

    async def test_sleeping_device_not_polled(self, hass: HomeAssistant) -> None:
        device = _make_device_data(status=DeviceStatus.SLEEPING)
        client = _make_mock_client({SERIAL: device})
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}
        # Set a recent sleep check so wake-check is also skipped
        coordinator._sleep_check_times[SERIAL] = datetime.now(UTC)

        await coordinator._async_update_data()

        client.async_get_device_power_info.assert_not_called()

    async def test_offline_device_not_polled(self, hass: HomeAssistant) -> None:
        device = _make_device_data(status=DeviceStatus.OFFLINE)
        client = _make_mock_client({SERIAL: device})
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}
        coordinator._sleep_check_times[SERIAL] = datetime.now(UTC)

        await coordinator._async_update_data()

        client.async_get_device_power_info.assert_not_called()


class TestCoordinatorWakeCheck:
    """POLL-03: Wake check for sleeping devices max every 5 min."""

    async def test_wake_check_runs_when_no_prior_check(self, hass: HomeAssistant) -> None:
        device = _make_device_data(status=DeviceStatus.SLEEPING)
        client = _make_mock_client({SERIAL: device})
        client.async_get_device_online_status = AsyncMock(return_value=DeviceStatus.SLEEPING)
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}

        await coordinator._async_update_data()

        client.async_get_device_online_status.assert_called_once_with(SERIAL)

    async def test_wake_check_skipped_within_5min(self, hass: HomeAssistant) -> None:
        device = _make_device_data(status=DeviceStatus.SLEEPING)
        client = _make_mock_client({SERIAL: device})
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}
        coordinator._sleep_check_times[SERIAL] = datetime.now(UTC)

        await coordinator._async_update_data()

        client.async_get_device_online_status.assert_not_called()

    async def test_wake_check_runs_after_5min(self, hass: HomeAssistant) -> None:
        device = _make_device_data(status=DeviceStatus.SLEEPING)
        client = _make_mock_client({SERIAL: device})
        client.async_get_device_online_status = AsyncMock(return_value=DeviceStatus.SLEEPING)
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}
        coordinator._sleep_check_times[SERIAL] = datetime.now(UTC) - timedelta(seconds=SLEEP_CHECK_INTERVAL + 1)

        await coordinator._async_update_data()

        client.async_get_device_online_status.assert_called_once_with(SERIAL)


class TestCoordinatorWakeResume:
    """POLL-02: Resume full polling when device wakes."""

    async def test_wake_transitions_status_to_active(self, hass: HomeAssistant) -> None:
        device = _make_device_data(status=DeviceStatus.SLEEPING)
        client = _make_mock_client({SERIAL: device})
        client.async_get_device_online_status = AsyncMock(return_value=DeviceStatus.ACTIVE)
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}

        await coordinator._async_update_data()

        assert device.status == DeviceStatus.ACTIVE


class TestCoordinatorActivePoll:
    """POLL-04: Active devices polled every cycle."""

    async def test_active_device_polled(self, hass: HomeAssistant) -> None:
        device = _make_device_data(status=DeviceStatus.ACTIVE)
        client = _make_mock_client({SERIAL: device})
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}

        await coordinator._async_update_data()

        client.async_get_device_online_status.assert_called_once_with(SERIAL)

    async def test_active_device_with_electric_gets_battery_polled(self, hass: HomeAssistant) -> None:
        device = _make_device_data(
            status=DeviceStatus.ACTIVE,
            capabilities={"Dormant", "Electric"},
        )
        client = _make_mock_client({SERIAL: device})
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}

        await coordinator._async_update_data()

        client.async_get_device_power_info.assert_called_once_with(SERIAL)
        assert device.battery_level == 85
        assert device.battery_power_source == "battery"

    async def test_active_device_without_electric_no_battery_poll(self, hass: HomeAssistant) -> None:
        device = _make_device_data(
            status=DeviceStatus.ACTIVE,
            capabilities={"Dormant"},  # no Electric
        )
        client = _make_mock_client({SERIAL: device})
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}

        await coordinator._async_update_data()

        client.async_get_device_power_info.assert_not_called()

    async def test_sleeping_error_during_poll_transitions_to_sleeping(self, hass: HomeAssistant) -> None:
        device = _make_device_data(status=DeviceStatus.ACTIVE)
        client = _make_mock_client({SERIAL: device})
        client.async_get_device_online_status = AsyncMock(side_effect=ImouDeviceSleepingError("DV1030"))
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}

        await coordinator._async_update_data()

        assert device.status == DeviceStatus.SLEEPING

    async def test_empty_data_returns_empty_dict(self, hass: HomeAssistant) -> None:
        client = _make_mock_client({})
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {}

        result = await coordinator._async_update_data()

        assert result == {}
