"""Tests for the ImouWakeUpButton entity (WAKE-08 through WAKE-10)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.imou_ha.const import WAKE_UP_MAX_RETRIES
from custom_components.imou_ha.models import DeviceStatus, ImouDeviceData

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator(devices: dict) -> MagicMock:
    """Create a minimal mock coordinator with the given devices dict."""
    coordinator = MagicMock()
    coordinator.data = devices
    coordinator.client = AsyncMock()
    coordinator.client.async_wake_up_via_dormant = AsyncMock()
    coordinator.client.async_get_device_online_status = AsyncMock(
        return_value=DeviceStatus.ACTIVE,
    )
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


def _make_battery_device(serial: str = "BATTERY001") -> ImouDeviceData:
    """Return a device with Dormant capability (battery camera), status SLEEPING."""
    return ImouDeviceData(
        serial=serial,
        name="Battery Camera",
        model="IPC-B22EP",
        firmware="2.840.0000000.28.R",
        status=DeviceStatus.SLEEPING,
        capabilities={"Dormant", "MobileDetect"},
    )


def _make_powered_device(serial: str = "POWERED001") -> ImouDeviceData:
    """Return a powered (non-battery) device WITHOUT Dormant capability."""
    return ImouDeviceData(
        serial=serial,
        name="Powered Camera",
        model="IPC-C22EP",
        firmware="2.840.0000000.28.R",
        status=DeviceStatus.ACTIVE,
        capabilities={"CloseCamera", "MobileDetect"},
    )


# ---------------------------------------------------------------------------
# async_setup_entry tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_entry_creates_one_button_per_dormant_device(hass) -> None:
    """Test that async_setup_entry creates exactly ONE ImouWakeUpButton per Dormant device."""
    from custom_components.imou_ha.button import ImouWakeUpButton, async_setup_entry

    device = _make_battery_device()
    coordinator = _make_coordinator({"BATTERY001": device})

    entry = MagicMock()
    entry.runtime_data = coordinator

    added_entities = []
    async_add_entities = MagicMock(side_effect=lambda entities: added_entities.extend(entities))

    await async_setup_entry(hass, entry, async_add_entities)

    assert async_add_entities.called
    assert len(added_entities) == 1
    assert isinstance(added_entities[0], ImouWakeUpButton)


@pytest.mark.asyncio
async def test_setup_entry_no_button_for_powered_device(hass) -> None:
    """Test that async_setup_entry creates no button for non-Dormant devices."""
    from custom_components.imou_ha.button import async_setup_entry

    device = _make_powered_device()
    coordinator = _make_coordinator({"POWERED001": device})

    entry = MagicMock()
    entry.runtime_data = coordinator

    added_entities = []
    async_add_entities = MagicMock(side_effect=lambda entities: added_entities.extend(entities))

    await async_setup_entry(hass, entry, async_add_entities)

    assert async_add_entities.called
    assert len(added_entities) == 0


@pytest.mark.asyncio
async def test_setup_entry_mixed_devices(hass) -> None:
    """Test that async_setup_entry creates ONE button for one Dormant + one powered device."""
    from custom_components.imou_ha.button import ImouWakeUpButton, async_setup_entry

    battery_device = _make_battery_device("BATTERY001")
    powered_device = _make_powered_device("POWERED001")
    coordinator = _make_coordinator({
        "BATTERY001": battery_device,
        "POWERED001": powered_device,
    })

    entry = MagicMock()
    entry.runtime_data = coordinator

    added_entities = []
    async_add_entities = MagicMock(side_effect=lambda entities: added_entities.extend(entities))

    await async_setup_entry(hass, entry, async_add_entities)

    assert len(added_entities) == 1
    assert isinstance(added_entities[0], ImouWakeUpButton)


# ---------------------------------------------------------------------------
# available property tests
# ---------------------------------------------------------------------------


def test_wake_up_button_available_when_sleeping() -> None:
    """Test that ImouWakeUpButton.available returns True even when device is SLEEPING."""
    from custom_components.imou_ha.button import ImouWakeUpButton

    device = _make_battery_device()
    device.status = DeviceStatus.SLEEPING
    coordinator = _make_coordinator({"BATTERY001": device})

    button = ImouWakeUpButton.__new__(ImouWakeUpButton)
    button.coordinator = coordinator
    button._device_serial = "BATTERY001"

    assert button.available is True


def test_wake_up_button_available_when_active() -> None:
    """Test that ImouWakeUpButton.available returns True when device is ACTIVE."""
    from custom_components.imou_ha.button import ImouWakeUpButton

    device = _make_battery_device()
    device.status = DeviceStatus.ACTIVE
    coordinator = _make_coordinator({"BATTERY001": device})

    button = ImouWakeUpButton.__new__(ImouWakeUpButton)
    button.coordinator = coordinator
    button._device_serial = "BATTERY001"

    assert button.available is True


# ---------------------------------------------------------------------------
# async_press tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_press_wakes_and_refreshes() -> None:
    """Test async_press calls async_wake_up_via_dormant, checks status, and refreshes coordinator."""
    from custom_components.imou_ha.button import ImouWakeUpButton

    device = _make_battery_device()
    coordinator = _make_coordinator({"BATTERY001": device})
    coordinator.client.async_get_device_online_status = AsyncMock(
        return_value=DeviceStatus.ACTIVE,
    )

    button = ImouWakeUpButton.__new__(ImouWakeUpButton)
    button.coordinator = coordinator
    button._device_serial = "BATTERY001"

    with patch("custom_components.imou_ha.button.asyncio.sleep", new_callable=AsyncMock):
        await button.async_press()

    coordinator.client.async_wake_up_via_dormant.assert_awaited_once_with("BATTERY001")
    coordinator.client.async_get_device_online_status.assert_awaited()
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_press_retries_on_failure() -> None:
    """Test async_press retries WAKE_UP_MAX_RETRIES times and does not raise when all fail."""
    from custom_components.imou_ha.button import ImouWakeUpButton

    device = _make_battery_device()
    coordinator = _make_coordinator({"BATTERY001": device})
    # Never reaches ACTIVE
    coordinator.client.async_get_device_online_status = AsyncMock(
        return_value=DeviceStatus.SLEEPING,
    )

    button = ImouWakeUpButton.__new__(ImouWakeUpButton)
    button.coordinator = coordinator
    button._device_serial = "BATTERY001"

    with patch("custom_components.imou_ha.button.asyncio.sleep", new_callable=AsyncMock):
        await button.async_press()  # must not raise

    assert coordinator.client.async_wake_up_via_dormant.await_count == WAKE_UP_MAX_RETRIES
    coordinator.async_request_refresh.assert_not_awaited()


# ---------------------------------------------------------------------------
# translation key test
# ---------------------------------------------------------------------------


def test_button_translation_key() -> None:
    """Test that ImouWakeUpButton has the correct translation key."""
    from custom_components.imou_ha.button import ImouWakeUpButton

    # Verify translation key via instance (class attr is name-mangled, instance resolves correctly)
    button = ImouWakeUpButton.__new__(ImouWakeUpButton)
    button.coordinator = MagicMock()
    button._device_serial = "BATTERY001"

    assert button._attr_translation_key == "wake_up"
