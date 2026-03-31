"""Tests for ImouCoordinator and ImouEntity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.imou_ha.budget import ImouBudgetState
from custom_components.imou_ha.const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MONTHLY_API_LIMIT,
    DEFAULT_RESERVE_SIZE,
    SLEEP_CHECK_INTERVAL,
)
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
        capabilities=capabilities or {"Dormant", "CloseCamera"},
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


# ---------------------------------------------------------------------------
# ImouCoordinator — alarm polling (EVNT-01 data backbone)
# ---------------------------------------------------------------------------


class TestAlarmPolling:
    """Alarm polling integration in _async_poll_device."""

    async def test_alarm_polled_when_capability_motion_detect(self, hass: HomeAssistant) -> None:
        """_async_poll_device calls async_get_alarm_status for MobileDetect device."""
        device = _make_device_data(
            status=DeviceStatus.ACTIVE,
            capabilities={"MobileDetect"},
        )
        client = _make_mock_client({SERIAL: device})
        client.async_get_alarm_status = AsyncMock(return_value=(False, False))
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}

        await coordinator._async_poll_device(SERIAL, device)

        client.async_get_alarm_status.assert_called_once()

    async def test_alarm_polled_when_capability_alarm_md(self, hass: HomeAssistant) -> None:
        """_async_poll_device calls async_get_alarm_status for AlarmMD device."""
        device = _make_device_data(
            status=DeviceStatus.ACTIVE,
            capabilities={"AlarmMD"},
        )
        client = _make_mock_client({SERIAL: device})
        client.async_get_alarm_status = AsyncMock(return_value=(False, False))
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}

        await coordinator._async_poll_device(SERIAL, device)

        client.async_get_alarm_status.assert_called_once()

    async def test_alarm_not_polled_without_motion_capability(self, hass: HomeAssistant) -> None:
        """_async_poll_device does NOT call async_get_alarm_status for devices without motion capability."""
        device = _make_device_data(
            status=DeviceStatus.ACTIVE,
            capabilities={"Dormant", "CloseCamera"},
        )
        client = _make_mock_client({SERIAL: device})
        client.async_get_alarm_status = AsyncMock(return_value=(False, False))
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}

        await coordinator._async_poll_device(SERIAL, device)

        client.async_get_alarm_status.assert_not_called()

    async def test_motion_detected_set_true_when_alarm_returns_motion(self, hass: HomeAssistant) -> None:
        """device.motion_detected=True when alarm returns (True, False)."""
        device = _make_device_data(
            status=DeviceStatus.ACTIVE,
            capabilities={"MobileDetect"},
        )
        device.motion_detected = False
        client = _make_mock_client({SERIAL: device})
        client.async_get_alarm_status = AsyncMock(return_value=(True, False))
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}

        await coordinator._async_poll_device(SERIAL, device)

        assert device.motion_detected is True
        assert device.human_detected is False

    async def test_human_detected_set_true_when_alarm_returns_human(self, hass: HomeAssistant) -> None:
        """device.human_detected=True when alarm returns (False, True)."""
        device = _make_device_data(
            status=DeviceStatus.ACTIVE,
            capabilities={"MobileDetect"},
        )
        device.human_detected = False
        client = _make_mock_client({SERIAL: device})
        client.async_get_alarm_status = AsyncMock(return_value=(False, True))
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}

        await coordinator._async_poll_device(SERIAL, device)

        assert device.motion_detected is False
        assert device.human_detected is True

    async def test_both_flags_false_when_alarm_returns_no_events(self, hass: HomeAssistant) -> None:
        """Both flags reset to False when alarm returns (False, False)."""
        device = _make_device_data(
            status=DeviceStatus.ACTIVE,
            capabilities={"MobileDetect"},
        )
        device.motion_detected = True
        device.human_detected = True
        client = _make_mock_client({SERIAL: device})
        client.async_get_alarm_status = AsyncMock(return_value=(False, False))
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}

        await coordinator._async_poll_device(SERIAL, device)

        assert device.motion_detected is False
        assert device.human_detected is False

    async def test_alarm_uses_last_updated_as_begin_time(self, hass: HomeAssistant) -> None:
        """Alarm call uses device.last_updated (formatted) as begin_time."""
        from datetime import timezone
        known_time = datetime(2026, 3, 30, 10, 0, 0, tzinfo=UTC)
        device = _make_device_data(
            status=DeviceStatus.ACTIVE,
            capabilities={"MobileDetect"},
        )
        device.last_updated = known_time
        client = _make_mock_client({SERIAL: device})
        client.async_get_alarm_status = AsyncMock(return_value=(False, False))
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}

        await coordinator._async_poll_device(SERIAL, device)

        call_args = client.async_get_alarm_status.call_args
        assert call_args[0][0] == SERIAL
        assert call_args[0][1] == "2026-03-30 10:00:00"

    async def test_last_updated_set_after_alarm_call(self, hass: HomeAssistant) -> None:
        """device.last_updated is updated AFTER alarm call to maintain correct time window."""
        known_time = datetime(2026, 3, 30, 10, 0, 0, tzinfo=UTC)
        device = _make_device_data(
            status=DeviceStatus.ACTIVE,
            capabilities={"MobileDetect"},
        )
        device.last_updated = known_time

        times_when_called: list[datetime] = []

        async def capture_alarm_call(serial: str, begin_time: str, end_time: str) -> tuple[bool, bool]:
            # Capture device.last_updated at the time of alarm call
            times_when_called.append(device.last_updated)
            return (False, False)

        client = _make_mock_client({SERIAL: device})
        client.async_get_alarm_status = capture_alarm_call
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}

        await coordinator._async_poll_device(SERIAL, device)

        # When alarm was called, last_updated should still be the known_time (not yet updated)
        assert len(times_when_called) == 1
        assert times_when_called[0] == known_time
        # After poll, last_updated should be updated to a new time
        assert device.last_updated != known_time

    async def test_alarm_failure_does_not_crash_poll(self, hass: HomeAssistant) -> None:
        """ImouError from alarm call is caught and logged — poll completes normally."""
        device = _make_device_data(
            status=DeviceStatus.ACTIVE,
            capabilities={"MobileDetect"},
        )
        device.motion_detected = True  # pre-existing state
        device.human_detected = False
        client = _make_mock_client({SERIAL: device})
        client.async_get_alarm_status = AsyncMock(side_effect=ImouError("API fail"))
        coordinator = ImouCoordinator(hass, client)
        coordinator.data = {SERIAL: device}

        # Should not raise
        await coordinator._async_poll_device(SERIAL, device)

        # Previous values retained
        assert device.motion_detected is True
        assert device.human_detected is False


# ---------------------------------------------------------------------------
# ImouCoordinator — Budget throttle (BUDG-04, BUDG-05)
# ---------------------------------------------------------------------------


def _make_mock_entry(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    """Create a MockConfigEntry with optional options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Imou (1 cameras)",
        data={"app_id": "x", "app_secret": "y", "api_url": "api_fk"},
        options=options or {},
        version=1,
    )
    entry.add_to_hass(hass)
    return entry


class TestCoordinatorThrottle:
    """Stepped threshold throttle tests (D-09, D-13)."""

    async def test_normal_budget_keeps_base_interval(self, hass: HomeAssistant) -> None:
        """Coordinator with >30% budget remaining keeps base update_interval."""
        entry = _make_mock_entry(hass)
        budget = ImouBudgetState(calls_this_month=0)
        client = _make_mock_client()
        coordinator = ImouCoordinator(hass, client, entry, budget)

        coordinator._check_and_apply_throttle()

        assert coordinator.update_interval == timedelta(seconds=DEFAULT_SCAN_INTERVAL)

    async def test_warn_budget_doubles_interval(self, hass: HomeAssistant) -> None:
        """Coordinator with 10-30% budget remaining doubles update_interval."""
        entry = _make_mock_entry(hass)
        effective_limit = MONTHLY_API_LIMIT - DEFAULT_RESERVE_SIZE
        # Set calls so remaining is 20% of effective_limit
        budget = ImouBudgetState(calls_this_month=int(effective_limit * 0.8))
        client = _make_mock_client()
        coordinator = ImouCoordinator(hass, client, entry, budget)

        coordinator._check_and_apply_throttle()

        assert coordinator.update_interval == timedelta(seconds=DEFAULT_SCAN_INTERVAL * 2)

    async def test_critical_budget_quadruples_interval(self, hass: HomeAssistant) -> None:
        """Coordinator with <10% budget remaining quadruples update_interval."""
        entry = _make_mock_entry(hass)
        effective_limit = MONTHLY_API_LIMIT - DEFAULT_RESERVE_SIZE
        # Set calls so remaining is 5% of effective_limit
        budget = ImouBudgetState(calls_this_month=int(effective_limit * 0.95))
        client = _make_mock_client()
        coordinator = ImouCoordinator(hass, client, entry, budget)

        with patch("custom_components.imou_ha.coordinator.pn_create"):
            coordinator._check_and_apply_throttle()

        assert coordinator.update_interval == timedelta(seconds=DEFAULT_SCAN_INTERVAL * 4)

    async def test_throttle_uses_effective_limit_with_reserve(self, hass: HomeAssistant) -> None:
        """Throttle thresholds use (MONTHLY_API_LIMIT - reserve_size) as effective limit (D-13)."""
        entry = _make_mock_entry(hass, options={"reserve_size": 1000})
        effective_limit = MONTHLY_API_LIMIT - 1000
        # Set exactly at 30% remaining of effective limit — should be in warn zone
        calls = int(effective_limit * 0.71)
        budget = ImouBudgetState(calls_this_month=calls)
        client = _make_mock_client()
        coordinator = ImouCoordinator(hass, client, entry, budget)

        coordinator._check_and_apply_throttle()

        assert coordinator.update_interval == timedelta(seconds=DEFAULT_SCAN_INTERVAL * 2)

    async def test_throttle_disabled_keeps_base_interval(self, hass: HomeAssistant) -> None:
        """Throttle disabled via options — interval stays at base even with low budget."""
        entry = _make_mock_entry(hass, options={"enable_throttle": False})
        effective_limit = MONTHLY_API_LIMIT - DEFAULT_RESERVE_SIZE
        budget = ImouBudgetState(calls_this_month=int(effective_limit * 0.95))
        client = _make_mock_client()
        coordinator = ImouCoordinator(hass, client, entry, budget)

        coordinator._check_and_apply_throttle()

        assert coordinator.update_interval == timedelta(seconds=DEFAULT_SCAN_INTERVAL)

    async def test_critical_creates_persistent_notification(self, hass: HomeAssistant) -> None:
        """Critical threshold creates persistent notification."""
        entry = _make_mock_entry(hass)
        effective_limit = MONTHLY_API_LIMIT - DEFAULT_RESERVE_SIZE
        budget = ImouBudgetState(calls_this_month=int(effective_limit * 0.95))
        client = _make_mock_client()
        coordinator = ImouCoordinator(hass, client, entry, budget)

        with patch("custom_components.imou_ha.coordinator.pn_create") as mock_create:
            coordinator._check_and_apply_throttle()
            mock_create.assert_called_once()
            assert coordinator._notification_active is True

    async def test_recovery_dismisses_notification(self, hass: HomeAssistant) -> None:
        """Normal threshold dismisses persistent notification."""
        entry = _make_mock_entry(hass)
        budget = ImouBudgetState(calls_this_month=0)
        client = _make_mock_client()
        coordinator = ImouCoordinator(hass, client, entry, budget)
        coordinator._notification_active = True

        with patch("custom_components.imou_ha.coordinator.pn_dismiss") as mock_dismiss:
            coordinator._check_and_apply_throttle()
            mock_dismiss.assert_called_once()
            assert coordinator._notification_active is False


class TestCoordinatorBudgetPersistence:
    """Budget state saved to config entry after poll."""

    async def test_budget_saved_after_update_data(self, hass: HomeAssistant) -> None:
        """Budget state saved to config entry data after _async_update_data."""
        entry = _make_mock_entry(hass)
        budget = ImouBudgetState(calls_this_month=42, calls_today=5, day_reset_date="2026-03-31", month_reset_date="2026-03")
        client = _make_mock_client({})
        coordinator = ImouCoordinator(hass, client, entry, budget)
        coordinator.data = {}

        with patch("custom_components.imou_ha.coordinator.pn_create"), \
             patch("custom_components.imou_ha.coordinator.pn_dismiss"), \
             patch.object(hass.config_entries, "async_update_entry") as mock_update:
            await coordinator._async_update_data()

        # async_update_entry should be called with budget data
        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args
        new_data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        from custom_components.imou_ha.budget import BUDGET_STORAGE_KEY
        assert BUDGET_STORAGE_KEY in new_data
        assert new_data[BUDGET_STORAGE_KEY]["calls_this_month"] == 42


class TestCoordinatorSharedBudgetState:
    """Proves client and coordinator share the same ImouBudgetState object."""

    async def test_shared_budget_state_identity(self, hass: HomeAssistant) -> None:
        """api_client and coordinator share the SAME ImouBudgetState object."""
        from custom_components.imou_ha.api_client import ImouApiClient

        budget_state = ImouBudgetState()
        with patch("custom_components.imou_ha.api_client.ImouOpenApiClient"):
            client = ImouApiClient("app", "secret", "url", budget_state=budget_state)
        entry = _make_mock_entry(hass)
        coordinator = ImouCoordinator(hass, client, entry, budget_state)

        # Increment via client's reference
        client._budget_state.increment(datetime.now(UTC))

        # Verify coordinator sees the same increment
        assert coordinator.budget_state.calls_this_month == 1
        assert coordinator.budget_state is client._budget_state

    async def test_constructor_accepts_all_params(self, hass: HomeAssistant) -> None:
        """ImouCoordinator(hass, client, entry, budget_state, scan_interval) instantiates without error."""
        entry = _make_mock_entry(hass)
        budget = ImouBudgetState()
        client = _make_mock_client()
        coordinator = ImouCoordinator(hass, client, entry, budget, 600)

        assert coordinator._base_scan_interval == 600
        assert coordinator.config_entry is entry
        assert coordinator._budget_state is budget
