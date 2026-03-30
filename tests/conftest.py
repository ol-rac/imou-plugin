"""Shared test fixtures for imou_ha tests."""

import pytest

from custom_components.imou_ha.models import DeviceStatus, ImouDeviceData


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
