"""Tests for the ImouPrivacySwitch entity (CTRL-01 through CTRL-04)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.imou_ha.exceptions import (
    ImouDeviceOfflineError,
    ImouDeviceSleepingError,
)
from custom_components.imou_ha.models import DeviceStatus, ImouDeviceData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator(devices: dict) -> MagicMock:
    """Create a minimal mock coordinator with the given devices dict."""
    coordinator = MagicMock()
    coordinator.data = devices
    coordinator.client = AsyncMock()
    coordinator.client.async_set_privacy_mode = AsyncMock()
    coordinator.client.async_get_privacy_mode = AsyncMock(return_value=True)
    return coordinator


def _make_privacy_device(serial: str = "ABC123DEF456", privacy_enabled: bool | None = None) -> ImouDeviceData:
    """Return a device data with closedCamera capability."""
    return ImouDeviceData(
        serial=serial,
        name="Front Door Camera",
        model="IPC-C22EP",
        firmware="2.840.0000000.28.R",
        status=DeviceStatus.ACTIVE,
        capabilities={"Dormant", "closedCamera", "MobileDetect"},
        privacy_enabled=privacy_enabled,
    )


def _make_no_privacy_device(serial: str = "NOPRIVACY123") -> ImouDeviceData:
    """Return a device without closedCamera capability."""
    return ImouDeviceData(
        serial=serial,
        name="Basic Camera",
        model="IPC-A22EP",
        firmware="2.840.0000000.28.R",
        status=DeviceStatus.ACTIVE,
        capabilities={"Dormant", "MobileDetect"},
    )


# ---------------------------------------------------------------------------
# async_setup_entry tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_entry_creates_switch_for_privacy_capable_device(hass) -> None:
    """Test that async_setup_entry creates ImouPrivacySwitch for closedCamera devices (CTRL-01, D-08)."""
    from custom_components.imou_ha.switch import async_setup_entry

    device = _make_privacy_device()
    coordinator = _make_coordinator({"ABC123DEF456": device})

    entry = MagicMock()
    entry.runtime_data = coordinator

    added_entities = []
    async_add_entities = MagicMock(side_effect=lambda entities: added_entities.extend(entities))

    await async_setup_entry(hass, entry, async_add_entities)

    assert async_add_entities.called
    assert len(added_entities) == 1
    from custom_components.imou_ha.switch import ImouPrivacySwitch
    assert isinstance(added_entities[0], ImouPrivacySwitch)


@pytest.mark.asyncio
async def test_setup_entry_creates_no_switch_without_privacy_capability(hass) -> None:
    """Test that async_setup_entry creates no switch for devices without closedCamera."""
    from custom_components.imou_ha.switch import async_setup_entry

    device = _make_no_privacy_device()
    coordinator = _make_coordinator({"NOPRIVACY123": device})

    entry = MagicMock()
    entry.runtime_data = coordinator

    added_entities = []
    async_add_entities = MagicMock(side_effect=lambda entities: added_entities.extend(entities))

    await async_setup_entry(hass, entry, async_add_entities)

    assert async_add_entities.called
    assert len(added_entities) == 0


@pytest.mark.asyncio
async def test_setup_entry_mixed_devices(hass) -> None:
    """Test that async_setup_entry only creates switch for closedCamera capable devices."""
    from custom_components.imou_ha.switch import async_setup_entry

    privacy_device = _make_privacy_device("ABC123DEF456")
    no_privacy_device = _make_no_privacy_device("NOPRIVACY123")
    coordinator = _make_coordinator({
        "ABC123DEF456": privacy_device,
        "NOPRIVACY123": no_privacy_device,
    })

    entry = MagicMock()
    entry.runtime_data = coordinator

    added_entities = []
    async_add_entities = MagicMock(side_effect=lambda entities: added_entities.extend(entities))

    await async_setup_entry(hass, entry, async_add_entities)

    assert len(added_entities) == 1


# ---------------------------------------------------------------------------
# is_on property tests
# ---------------------------------------------------------------------------


def test_is_on_returns_true_when_privacy_enabled() -> None:
    """Test is_on returns True when device_data.privacy_enabled is True (D-09)."""
    from custom_components.imou_ha.switch import ImouPrivacySwitch

    device = _make_privacy_device(privacy_enabled=True)
    coordinator = _make_coordinator({"ABC123DEF456": device})
    switch = ImouPrivacySwitch.__new__(ImouPrivacySwitch)
    switch.coordinator = coordinator
    switch._device_serial = "ABC123DEF456"

    assert switch.is_on is True


def test_is_on_returns_false_when_privacy_disabled() -> None:
    """Test is_on returns False when device_data.privacy_enabled is False."""
    from custom_components.imou_ha.switch import ImouPrivacySwitch

    device = _make_privacy_device(privacy_enabled=False)
    coordinator = _make_coordinator({"ABC123DEF456": device})
    switch = ImouPrivacySwitch.__new__(ImouPrivacySwitch)
    switch.coordinator = coordinator
    switch._device_serial = "ABC123DEF456"

    assert switch.is_on is False


def test_is_on_returns_none_when_privacy_unknown() -> None:
    """Test is_on returns None when device_data.privacy_enabled is None."""
    from custom_components.imou_ha.switch import ImouPrivacySwitch

    device = _make_privacy_device(privacy_enabled=None)
    coordinator = _make_coordinator({"ABC123DEF456": device})
    switch = ImouPrivacySwitch.__new__(ImouPrivacySwitch)
    switch.coordinator = coordinator
    switch._device_serial = "ABC123DEF456"

    assert switch.is_on is None


# ---------------------------------------------------------------------------
# Command verification tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_on_confirms_state_on_match() -> None:
    """Test async_turn_on sends set_privacy_mode(True) and confirms state on poll match (CTRL-02, D-10)."""
    from custom_components.imou_ha.switch import ImouPrivacySwitch

    device = _make_privacy_device(privacy_enabled=False)
    coordinator = _make_coordinator({"ABC123DEF456": device})
    coordinator.client.async_get_privacy_mode = AsyncMock(return_value=True)

    switch = ImouPrivacySwitch.__new__(ImouPrivacySwitch)
    switch.coordinator = coordinator
    switch._device_serial = "ABC123DEF456"
    switch.async_write_ha_state = MagicMock()

    with patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock):
        await switch.async_turn_on()

    coordinator.client.async_set_privacy_mode.assert_called_once_with("ABC123DEF456", True)
    assert device.privacy_enabled is True
    switch.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_turn_off_confirms_state_on_match() -> None:
    """Test async_turn_off sends set_privacy_mode(False) and confirms state on poll match (CTRL-02)."""
    from custom_components.imou_ha.switch import ImouPrivacySwitch

    device = _make_privacy_device(privacy_enabled=True)
    coordinator = _make_coordinator({"ABC123DEF456": device})
    coordinator.client.async_get_privacy_mode = AsyncMock(return_value=False)

    switch = ImouPrivacySwitch.__new__(ImouPrivacySwitch)
    switch.coordinator = coordinator
    switch._device_serial = "ABC123DEF456"
    switch.async_write_ha_state = MagicMock()

    with patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock):
        await switch.async_turn_off()

    coordinator.client.async_set_privacy_mode.assert_called_once_with("ABC123DEF456", False)
    assert device.privacy_enabled is False
    switch.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_state_not_updated_optimistically() -> None:
    """Test that state is NOT updated before verification (D-14, non-optimistic pattern).

    privacy_enabled should remain unchanged until poll confirms the new state.
    """
    from custom_components.imou_ha.switch import ImouPrivacySwitch

    device = _make_privacy_device(privacy_enabled=False)
    coordinator = _make_coordinator({"ABC123DEF456": device})

    # Simulate slow/late confirmation: never returns True during first call
    # We'll track state BEFORE confirmation
    state_before_confirmation = []

    async def mock_get_privacy(*args):
        # Record privacy_enabled state at poll time
        state_before_confirmation.append(device.privacy_enabled)
        return True  # confirm on first poll

    coordinator.client.async_get_privacy_mode = AsyncMock(side_effect=mock_get_privacy)

    switch = ImouPrivacySwitch.__new__(ImouPrivacySwitch)
    switch.coordinator = coordinator
    switch._device_serial = "ABC123DEF456"
    switch.async_write_ha_state = MagicMock()

    with patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock):
        await switch.async_turn_on()

    # At the moment of polling, privacy_enabled should still be False (not yet confirmed)
    assert state_before_confirmation[0] is False
    # After confirmation, it should be True
    assert device.privacy_enabled is True


@pytest.mark.asyncio
async def test_sleeping_device_leaves_state_unchanged() -> None:
    """Test sleeping device raises ImouDeviceSleepingError — state unchanged, warning logged (CTRL-03, D-15)."""
    from custom_components.imou_ha.switch import ImouPrivacySwitch

    device = _make_privacy_device(privacy_enabled=False)
    coordinator = _make_coordinator({"ABC123DEF456": device})
    coordinator.client.async_set_privacy_mode = AsyncMock(
        side_effect=ImouDeviceSleepingError("DV1030:sleeping")
    )

    switch = ImouPrivacySwitch.__new__(ImouPrivacySwitch)
    switch.coordinator = coordinator
    switch._device_serial = "ABC123DEF456"
    switch.async_write_ha_state = MagicMock()

    with patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock):
        await switch.async_turn_on()

    # State should be unchanged
    assert device.privacy_enabled is False
    # No state write should happen
    switch.async_write_ha_state.assert_not_called()


@pytest.mark.asyncio
async def test_offline_device_leaves_state_unchanged() -> None:
    """Test offline device raises ImouDeviceOfflineError — state unchanged, warning logged (CTRL-03, D-15)."""
    from custom_components.imou_ha.switch import ImouPrivacySwitch

    device = _make_privacy_device(privacy_enabled=True)
    coordinator = _make_coordinator({"ABC123DEF456": device})
    coordinator.client.async_set_privacy_mode = AsyncMock(
        side_effect=ImouDeviceOfflineError("DV1007:offline")
    )

    switch = ImouPrivacySwitch.__new__(ImouPrivacySwitch)
    switch.coordinator = coordinator
    switch._device_serial = "ABC123DEF456"
    switch.async_write_ha_state = MagicMock()

    with patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock):
        await switch.async_turn_off()

    # State should be unchanged (still True since command failed)
    assert device.privacy_enabled is True
    switch.async_write_ha_state.assert_not_called()


@pytest.mark.asyncio
async def test_verification_timeout_reverts_state() -> None:
    """Test verification timeout after 3 retries — reverts to previous state (CTRL-04, D-16)."""
    from custom_components.imou_ha.switch import ImouPrivacySwitch

    device = _make_privacy_device(privacy_enabled=False)
    coordinator = _make_coordinator({"ABC123DEF456": device})
    # Always returns opposite of desired state (never confirms)
    coordinator.client.async_get_privacy_mode = AsyncMock(return_value=False)

    switch = ImouPrivacySwitch.__new__(ImouPrivacySwitch)
    switch.coordinator = coordinator
    switch._device_serial = "ABC123DEF456"
    switch.async_write_ha_state = MagicMock()

    with patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock):
        await switch.async_turn_on()

    # Should revert to False (previous state)
    assert device.privacy_enabled is False
    # State write should be called on revert
    switch.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_device_offline_during_verification_breaks_loop() -> None:
    """Test that offline error during verification polling breaks loop and reverts state (D-15)."""
    from custom_components.imou_ha.switch import ImouPrivacySwitch

    device = _make_privacy_device(privacy_enabled=False)
    coordinator = _make_coordinator({"ABC123DEF456": device})
    # Raises offline error during poll
    coordinator.client.async_get_privacy_mode = AsyncMock(
        side_effect=ImouDeviceOfflineError("DV1007:offline during verification")
    )

    switch = ImouPrivacySwitch.__new__(ImouPrivacySwitch)
    switch.coordinator = coordinator
    switch._device_serial = "ABC123DEF456"
    switch.async_write_ha_state = MagicMock()

    with patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock):
        await switch.async_turn_on()

    # Should revert to False
    assert device.privacy_enabled is False
    # State write should be called on revert
    switch.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_verification_succeeds_on_second_retry() -> None:
    """Test verification succeeds on 2nd retry (not just 1st attempt)."""
    from custom_components.imou_ha.switch import ImouPrivacySwitch

    device = _make_privacy_device(privacy_enabled=False)
    coordinator = _make_coordinator({"ABC123DEF456": device})
    # First poll returns False (no match), second poll returns True (match)
    coordinator.client.async_get_privacy_mode = AsyncMock(side_effect=[False, True])

    switch = ImouPrivacySwitch.__new__(ImouPrivacySwitch)
    switch.coordinator = coordinator
    switch._device_serial = "ABC123DEF456"
    switch.async_write_ha_state = MagicMock()

    with patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock):
        await switch.async_turn_on()

    # Should confirm on 2nd poll
    assert device.privacy_enabled is True
    switch.async_write_ha_state.assert_called_once()
    # Polled twice
    assert coordinator.client.async_get_privacy_mode.call_count == 2


@pytest.mark.asyncio
async def test_verify_max_retries_count() -> None:
    """Test that verification polls exactly VERIFY_MAX_RETRIES times on timeout."""
    from custom_components.imou_ha.switch import ImouPrivacySwitch, VERIFY_MAX_RETRIES

    device = _make_privacy_device(privacy_enabled=False)
    coordinator = _make_coordinator({"ABC123DEF456": device})
    # Never confirms
    coordinator.client.async_get_privacy_mode = AsyncMock(return_value=False)

    switch = ImouPrivacySwitch.__new__(ImouPrivacySwitch)
    switch.coordinator = coordinator
    switch._device_serial = "ABC123DEF456"
    switch.async_write_ha_state = MagicMock()

    with patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await switch.async_turn_on()

    # Should sleep VERIFY_MAX_RETRIES times
    assert mock_sleep.call_count == VERIFY_MAX_RETRIES
    assert coordinator.client.async_get_privacy_mode.call_count == VERIFY_MAX_RETRIES
