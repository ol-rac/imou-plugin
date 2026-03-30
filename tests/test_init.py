"""Tests for the Imou integration lifecycle (__init__.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.imou_ha.const import (
    CONF_API_URL,
    CONF_APP_ID,
    CONF_APP_SECRET,
    DEFAULT_API_URL,
    DOMAIN,
)
from custom_components.imou_ha.coordinator import ImouCoordinator
from custom_components.imou_ha.models import DeviceStatus, ImouDeviceData

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

MOCK_ENTRY_DATA = {
    CONF_APP_ID: "test_app_id",
    CONF_APP_SECRET: "test_app_secret",
    CONF_API_URL: DEFAULT_API_URL,
}

MOCK_DEVICES = {
    "CAM001": ImouDeviceData(
        serial="CAM001",
        name="Front Door",
        model="IPC-C22EP",
        firmware="2.840.0",
        status=DeviceStatus.ACTIVE,
        capabilities=set(),
    ),
}


def _create_mock_entry(hass: HomeAssistant):
    """Create a MockConfigEntry for imou_ha."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Imou (1 cameras)",
        data=MOCK_ENTRY_DATA,
        version=1,
    )
    entry.add_to_hass(hass)
    return entry


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_setup_entry_creates_coordinator(hass):
    """async_setup_entry stores an ImouCoordinator in entry.runtime_data."""
    entry = _create_mock_entry(hass)

    with (
        patch(
            "custom_components.imou_ha.ImouApiClient",
            return_value=AsyncMock(),
        ),
        patch.object(
            ImouCoordinator,
            "async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch.object(
            ImouCoordinator,
            "_async_setup",
            new_callable=AsyncMock,
        ),
    ):
        result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data, ImouCoordinator)


@pytest.mark.asyncio
async def test_async_setup_entry_calls_first_refresh(hass):
    """async_config_entry_first_refresh is called exactly once during setup."""
    entry = _create_mock_entry(hass)
    mock_refresh = AsyncMock()

    with (
        patch(
            "custom_components.imou_ha.ImouApiClient",
            return_value=AsyncMock(),
        ),
        patch.object(
            ImouCoordinator,
            "async_config_entry_first_refresh",
            mock_refresh,
        ),
        patch.object(
            ImouCoordinator,
            "_async_setup",
            new_callable=AsyncMock,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    mock_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_setup_entry_stores_in_runtime_data(hass):
    """Coordinator is stored in entry.runtime_data, NOT in hass.data."""
    entry = _create_mock_entry(hass)

    with (
        patch(
            "custom_components.imou_ha.ImouApiClient",
            return_value=AsyncMock(),
        ),
        patch.object(
            ImouCoordinator,
            "async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch.object(
            ImouCoordinator,
            "_async_setup",
            new_callable=AsyncMock,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hasattr(entry, "runtime_data")
    assert isinstance(entry.runtime_data, ImouCoordinator)
    # Not in hass.data under DOMAIN
    assert DOMAIN not in hass.data or not isinstance(hass.data.get(DOMAIN), dict)


@pytest.mark.asyncio
async def test_async_unload_entry_returns_true(hass):
    """async_unload_entry returns True and entry state is NOT_LOADED."""
    entry = _create_mock_entry(hass)

    with (
        patch(
            "custom_components.imou_ha.ImouApiClient",
            return_value=AsyncMock(),
        ),
        patch.object(
            ImouCoordinator,
            "async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch.object(
            ImouCoordinator,
            "_async_setup",
            new_callable=AsyncMock,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED

        result = await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    assert entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.asyncio
async def test_credentials_not_in_hass_data(hass):
    """Credentials (INFR-08) must never appear in hass.data — only in config_entry.data."""
    entry = _create_mock_entry(hass)

    with (
        patch(
            "custom_components.imou_ha.ImouApiClient",
            return_value=AsyncMock(),
        ),
        patch.object(
            ImouCoordinator,
            "async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch.object(
            ImouCoordinator,
            "_async_setup",
            new_callable=AsyncMock,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Credentials in entry.data
    assert CONF_APP_ID in entry.data
    assert CONF_APP_SECRET in entry.data

    # NOT in hass.data under the domain
    domain_data = hass.data.get(DOMAIN, {})
    if isinstance(domain_data, dict):
        assert CONF_APP_SECRET not in domain_data
        assert CONF_APP_ID not in domain_data
