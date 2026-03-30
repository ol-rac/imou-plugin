"""Shared test fixtures for imou_ha tests."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from custom_components.imou_ha.models import DeviceStatus, ImouDeviceData

# ---------------------------------------------------------------------------
# Enable custom integration discovery for config flow tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Automatically enable custom integrations in all tests.

    The enable_custom_integrations fixture (from pytest-homeassistant-custom-component)
    pops the cached custom components map so HA re-discovers the imou_ha integration
    from custom_components/ during config flow tests.
    """
    return enable_custom_integrations


@pytest.fixture
def sample_device_data() -> ImouDeviceData:
    """Return a sample ImouDeviceData for testing."""
    return ImouDeviceData(
        serial="ABC123DEF456",
        name="Front Door Camera",
        model="IPC-C22EP",
        firmware="2.840.0000000.28.R",
        status=DeviceStatus.ACTIVE,
        capabilities={"Dormant", "closedCamera", "MobileDetect"},
    )


@pytest.fixture
def battery_device_data() -> ImouDeviceData:
    """Return a sample ImouDeviceData with Electric capability."""
    return ImouDeviceData(
        serial="BAT789GHI012",
        name="Garden Camera",
        model="IPC-B26EP",
        firmware="2.840.0000000.28.R",
        status=DeviceStatus.ACTIVE,
        capabilities={"Dormant", "Electric", "closedCamera"},
        battery_level=85,
        battery_power_source="battery",
    )


@pytest.fixture
def mock_webhook_request():
    """Factory fixture returning a mock aiohttp.web.Request with given JSON payload."""

    def _make_request(payload: dict) -> web.Request:
        request = MagicMock(spec=web.Request)
        request.json = AsyncMock(return_value=payload)
        return request

    return _make_request


@pytest.fixture
def mock_imou_api_client(sample_device_data: ImouDeviceData) -> AsyncMock:
    """Return a mock ImouApiClient."""
    client = AsyncMock()
    client.async_validate_credentials = AsyncMock()
    client.async_get_devices = AsyncMock(
        return_value={
            "ABC123DEF456": sample_device_data,
        }
    )
    return client
