"""Tests for switch platform — ImouPrivacySwitch entity (02-02)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.imou_ha.exceptions import (
    ImouDeviceOfflineError,
    ImouDeviceSleepingError,
)
from custom_components.imou_ha.models import DeviceStatus, ImouDeviceData


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def device_with_privacy() -> ImouDeviceData:
    """Return device data with closedCamera capability."""
    return ImouDeviceData(
        serial="ABC123DEF456",
        name="Front Door Camera",
        model="IPC-C22EP",
        firmware="2.840.0000000.28.R",
        status=DeviceStatus.ACTIVE,
        capabilities={"Dormant", "closedCamera", "MobileDetect"},
        privacy_enabled=False,
    )


@pytest.fixture
def device_without_privacy() -> ImouDeviceData:
    """Return device data WITHOUT closedCamera capability."""
    return ImouDeviceData(
        serial="XYZ789ABC000",
        name="Back Door Camera",
        model="IPC-A10",
        firmware="1.0",
        status=DeviceStatus.ACTIVE,
        capabilities={"Dormant"},
    )


@pytest.fixture
def mock_coordinator(hass, device_with_privacy):
    """Return a mock coordinator with one privacy-capable device."""
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.data = {"ABC123DEF456": device_with_privacy}
    coordinator.client = AsyncMock()
    coordinator.client.async_set_privacy_mode = AsyncMock(return_value=None)
    coordinator.client.async_get_privacy_mode = AsyncMock(return_value=True)
    return coordinator


@pytest.fixture
def privacy_switch(mock_coordinator):
    """Return an ImouPrivacySwitch instance."""
    from custom_components.imou_ha.switch import ImouPrivacySwitch

    return ImouPrivacySwitch(mock_coordinator, "ABC123DEF456")


# ---------------------------------------------------------------------------
# async_setup_entry tests
# ---------------------------------------------------------------------------


class TestAsyncSetupEntry:
    """Tests for async_setup_entry — entity creation filtering."""

    async def test_setup_creates_switch_for_closedcamera_device(
        self, hass, device_with_privacy, device_without_privacy
    ):
        """async_setup_entry creates ImouPrivacySwitch only for closedCamera devices."""
        from unittest.mock import MagicMock

        from custom_components.imou_ha.switch import ImouPrivacySwitch, async_setup_entry

        coordinator = MagicMock()
        coordinator.hass = hass
        coordinator.data = {
            "ABC123DEF456": device_with_privacy,
            "XYZ789ABC000": device_without_privacy,
        }

        entry = MagicMock()
        entry.runtime_data = coordinator

        added_entities = []
        async_add_entities = MagicMock(
            side_effect=lambda entities: added_entities.extend(entities)
        )

        await async_setup_entry(hass, entry, async_add_entities)

        assert len(added_entities) == 1
        assert isinstance(added_entities[0], ImouPrivacySwitch)
        assert added_entities[0]._device_serial == "ABC123DEF456"

    async def test_setup_creates_no_switch_without_closedcamera(
        self, hass, device_without_privacy
    ):
        """async_setup_entry creates NO switch when no closedCamera device present."""
        from unittest.mock import MagicMock

        from custom_components.imou_ha.switch import async_setup_entry

        coordinator = MagicMock()
        coordinator.hass = hass
        coordinator.data = {"XYZ789ABC000": device_without_privacy}

        entry = MagicMock()
        entry.runtime_data = coordinator

        added_entities = []
        async_add_entities = MagicMock(
            side_effect=lambda entities: added_entities.extend(entities)
        )

        await async_setup_entry(hass, entry, async_add_entities)

        assert len(added_entities) == 0


# ---------------------------------------------------------------------------
# is_on property tests
# ---------------------------------------------------------------------------


class TestIsOn:
    """Tests for ImouPrivacySwitch.is_on property."""

    def test_is_on_true_when_privacy_enabled(
        self, privacy_switch, device_with_privacy
    ):
        """is_on returns True when device_data.privacy_enabled is True."""
        device_with_privacy.privacy_enabled = True
        assert privacy_switch.is_on is True

    def test_is_on_false_when_privacy_disabled(
        self, privacy_switch, device_with_privacy
    ):
        """is_on returns False when device_data.privacy_enabled is False."""
        device_with_privacy.privacy_enabled = False
        assert privacy_switch.is_on is False

    def test_is_on_none_when_privacy_unknown(
        self, privacy_switch, device_with_privacy
    ):
        """is_on returns None when device_data.privacy_enabled is None."""
        device_with_privacy.privacy_enabled = None
        assert privacy_switch.is_on is None


# ---------------------------------------------------------------------------
# Command execution tests
# ---------------------------------------------------------------------------


class TestPrivacyCommandExecution:
    """Tests for confirmed-state command execution (async_turn_on/off)."""

    @patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock)
    async def test_turn_on_confirms_state_on_match(
        self, mock_sleep, privacy_switch, mock_coordinator, device_with_privacy
    ):
        """async_turn_on sends set_privacy_mode(True), polls, confirms state on match."""
        device_with_privacy.privacy_enabled = False
        mock_coordinator.client.async_set_privacy_mode = AsyncMock(return_value=None)
        mock_coordinator.client.async_get_privacy_mode = AsyncMock(return_value=True)
        privacy_switch.async_write_ha_state = MagicMock()

        await privacy_switch.async_turn_on()

        mock_coordinator.client.async_set_privacy_mode.assert_called_once_with(
            "ABC123DEF456", True
        )
        mock_coordinator.client.async_get_privacy_mode.assert_called_once_with(
            "ABC123DEF456"
        )
        assert device_with_privacy.privacy_enabled is True
        privacy_switch.async_write_ha_state.assert_called_once()

    @patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock)
    async def test_turn_off_confirms_state_on_match(
        self, mock_sleep, privacy_switch, mock_coordinator, device_with_privacy
    ):
        """async_turn_off sends set_privacy_mode(False), polls, confirms state on match."""
        device_with_privacy.privacy_enabled = True
        mock_coordinator.client.async_set_privacy_mode = AsyncMock(return_value=None)
        mock_coordinator.client.async_get_privacy_mode = AsyncMock(return_value=False)
        privacy_switch.async_write_ha_state = MagicMock()

        await privacy_switch.async_turn_off()

        mock_coordinator.client.async_set_privacy_mode.assert_called_once_with(
            "ABC123DEF456", False
        )
        assert device_with_privacy.privacy_enabled is False
        privacy_switch.async_write_ha_state.assert_called_once()

    @patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock)
    async def test_state_not_updated_optimistically(
        self, mock_sleep, privacy_switch, mock_coordinator, device_with_privacy
    ):
        """State NOT updated optimistically before verification — privacy_enabled unchanged until poll confirms."""
        device_with_privacy.privacy_enabled = False
        # Make get_privacy_mode hang so we can check intermediate state
        # We capture the privacy_enabled value at time of first get call
        captured_before_confirm = []

        async def capture_privacy_mode(_serial):
            # At this point verification is happening — privacy_enabled should still be False
            captured_before_confirm.append(device_with_privacy.privacy_enabled)
            return True  # confirm success

        mock_coordinator.client.async_set_privacy_mode = AsyncMock(return_value=None)
        mock_coordinator.client.async_get_privacy_mode = AsyncMock(
            side_effect=capture_privacy_mode
        )
        privacy_switch.async_write_ha_state = MagicMock()

        await privacy_switch.async_turn_on()

        # Before confirmation, privacy_enabled was still False (non-optimistic)
        assert captured_before_confirm[0] is False

    async def test_sleeping_device_raises_sleeping_error_state_unchanged(
        self, privacy_switch, mock_coordinator, device_with_privacy
    ):
        """sleeping device raises ImouDeviceSleepingError — state unchanged, warning logged."""
        device_with_privacy.privacy_enabled = False
        mock_coordinator.client.async_set_privacy_mode = AsyncMock(
            side_effect=ImouDeviceSleepingError("DV1030:sleeping")
        )
        privacy_switch.async_write_ha_state = MagicMock()

        await privacy_switch.async_turn_on()

        # state unchanged
        assert device_with_privacy.privacy_enabled is False
        # async_write_ha_state never called (no state change needed)
        privacy_switch.async_write_ha_state.assert_not_called()

    async def test_offline_device_raises_offline_error_state_unchanged(
        self, privacy_switch, mock_coordinator, device_with_privacy
    ):
        """offline device raises ImouDeviceOfflineError — state unchanged, warning logged."""
        device_with_privacy.privacy_enabled = True
        mock_coordinator.client.async_set_privacy_mode = AsyncMock(
            side_effect=ImouDeviceOfflineError("DV1007:offline")
        )
        privacy_switch.async_write_ha_state = MagicMock()

        await privacy_switch.async_turn_off()

        # state unchanged
        assert device_with_privacy.privacy_enabled is True
        privacy_switch.async_write_ha_state.assert_not_called()

    @patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock)
    async def test_verification_timeout_reverts_to_previous_state(
        self, mock_sleep, privacy_switch, mock_coordinator, device_with_privacy
    ):
        """Verification timeout after 3 retries — reverts to previous state."""
        device_with_privacy.privacy_enabled = False  # previous state
        mock_coordinator.client.async_set_privacy_mode = AsyncMock(return_value=None)
        # Always return opposite of desired — never confirms
        mock_coordinator.client.async_get_privacy_mode = AsyncMock(return_value=False)
        privacy_switch.async_write_ha_state = MagicMock()

        await privacy_switch.async_turn_on()  # wants True, but poll always returns False

        # Should have retried VERIFY_MAX_RETRIES times
        from custom_components.imou_ha.switch import VERIFY_MAX_RETRIES
        assert mock_coordinator.client.async_get_privacy_mode.call_count == VERIFY_MAX_RETRIES

        # State reverted to previous (False)
        assert device_with_privacy.privacy_enabled is False
        # async_write_ha_state called for the revert
        privacy_switch.async_write_ha_state.assert_called_once()

    @patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock)
    async def test_device_goes_offline_during_verification(
        self, mock_sleep, privacy_switch, mock_coordinator, device_with_privacy
    ):
        """Device goes offline during verification polling — breaks loop, reverts state."""
        device_with_privacy.privacy_enabled = False
        mock_coordinator.client.async_set_privacy_mode = AsyncMock(return_value=None)
        # First poll raises offline error — verification loop broken
        mock_coordinator.client.async_get_privacy_mode = AsyncMock(
            side_effect=ImouDeviceOfflineError("DV1007:offline during verification")
        )
        privacy_switch.async_write_ha_state = MagicMock()

        await privacy_switch.async_turn_on()

        # Loop broke after first attempt
        mock_coordinator.client.async_get_privacy_mode.assert_called_once()
        # State reverted to previous (False)
        assert device_with_privacy.privacy_enabled is False
        privacy_switch.async_write_ha_state.assert_called_once()

    @patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock)
    async def test_verification_succeeds_on_second_retry(
        self, mock_sleep, privacy_switch, mock_coordinator, device_with_privacy
    ):
        """Verification succeeds on 2nd retry (not just 1st attempt)."""
        device_with_privacy.privacy_enabled = False
        mock_coordinator.client.async_set_privacy_mode = AsyncMock(return_value=None)
        # First poll doesn't match (False), second matches (True)
        mock_coordinator.client.async_get_privacy_mode = AsyncMock(
            side_effect=[False, True]
        )
        privacy_switch.async_write_ha_state = MagicMock()

        await privacy_switch.async_turn_on()

        # Polled twice before confirming
        assert mock_coordinator.client.async_get_privacy_mode.call_count == 2
        assert device_with_privacy.privacy_enabled is True
        privacy_switch.async_write_ha_state.assert_called_once()

    @patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock)
    async def test_sleep_called_between_retries(
        self, mock_sleep, privacy_switch, mock_coordinator, device_with_privacy
    ):
        """asyncio.sleep called with VERIFY_DELAY_SECONDS between each poll."""
        device_with_privacy.privacy_enabled = False
        mock_coordinator.client.async_set_privacy_mode = AsyncMock(return_value=None)
        mock_coordinator.client.async_get_privacy_mode = AsyncMock(return_value=True)
        privacy_switch.async_write_ha_state = MagicMock()

        await privacy_switch.async_turn_on()

        from custom_components.imou_ha.switch import VERIFY_DELAY_SECONDS
        mock_sleep.assert_called_once_with(VERIFY_DELAY_SECONDS)

    @patch("custom_components.imou_ha.switch.asyncio.sleep", new_callable=AsyncMock)
    async def test_write_ha_state_only_called_on_confirmed_or_revert(
        self, mock_sleep, privacy_switch, mock_coordinator, device_with_privacy
    ):
        """async_write_ha_state called exactly once — only on CONFIRMED or TIMEOUT revert."""
        device_with_privacy.privacy_enabled = False
        mock_coordinator.client.async_set_privacy_mode = AsyncMock(return_value=None)
        mock_coordinator.client.async_get_privacy_mode = AsyncMock(return_value=True)
        privacy_switch.async_write_ha_state = MagicMock()

        await privacy_switch.async_turn_on()

        # Exactly one call on confirmation
        privacy_switch.async_write_ha_state.assert_called_once()
