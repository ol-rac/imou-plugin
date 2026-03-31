"""Tests for camera platform and API client streaming/privacy methods (02-01)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.imou_ha.exceptions import ImouDeviceSleepingError, ImouError
from custom_components.imou_ha.models import DeviceStatus, ImouDeviceData

# ---------------------------------------------------------------------------
# API Client tests — streaming and privacy methods
# ---------------------------------------------------------------------------


class TestAsyncGetStreamUrl:
    """Tests for ImouApiClient.async_get_stream_url."""

    @pytest.fixture
    def api_client(self):
        """Return ImouApiClient with mocked device manager."""
        from custom_components.imou_ha.api_client import ImouApiClient

        client = ImouApiClient("app_id", "secret", "openapi-fk.easy4ip.com")
        device_manager = AsyncMock()
        client._device_manager = device_manager
        return client, device_manager

    async def test_stream_url_returns_hd_sd_tuple(self, api_client):
        """async_get_stream_url returns (hd_url, sd_url) when API succeeds."""
        client, device_manager = api_client
        device_manager.async_get_stream_url.return_value = {
            "streams": [
                {"hls": "https://hls.example.com/hd.m3u8"},
                {"hls": "https://hls.example.com/sd.m3u8"},
            ],
        }

        hd, sd = await client.async_get_stream_url("ABC123")

        assert hd == "https://hls.example.com/hd.m3u8"
        assert sd == "https://hls.example.com/sd.m3u8"
        device_manager.async_get_stream_url.assert_called_once_with("ABC123", "0")

    async def test_stream_url_single_stream_sd_none(self, api_client):
        """async_get_stream_url returns (hd_url, None) when only one stream."""
        client, device_manager = api_client
        device_manager.async_get_stream_url.return_value = {
            "streams": [
                {"hls": "https://hls.example.com/hd.m3u8"},
            ],
        }

        hd, sd = await client.async_get_stream_url("ABC123")

        assert hd == "https://hls.example.com/hd.m3u8"
        assert sd is None

    async def test_stream_url_lv1002_fallback_to_create(self, api_client):
        """async_get_stream_url handles LV1002 by calling create_stream_url fallback."""
        from pyimouapi.exceptions import RequestFailedException

        client, device_manager = api_client
        device_manager.async_get_stream_url.side_effect = RequestFailedException(
            "LV1002:Live not exist",
        )
        device_manager.async_create_stream_url.return_value = {
            "streams": [
                {"hls": "https://hls.example.com/hd.m3u8"},
                {"hls": "https://hls.example.com/sd.m3u8"},
            ],
        }

        hd, sd = await client.async_get_stream_url("ABC123")

        assert hd == "https://hls.example.com/hd.m3u8"
        device_manager.async_create_stream_url.assert_called_once_with("ABC123", "0", stream_id=0)

    async def test_stream_url_lv1001_on_create_falls_back_to_get(self, api_client):
        """async_get_stream_url handles LV1001 during create by retrying get."""
        from pyimouapi.exceptions import RequestFailedException

        client, device_manager = api_client
        device_manager.async_get_stream_url.side_effect = [
            RequestFailedException("LV1002:Live not exist"),
            {"streams": [{"hls": "https://hls.example.com/hd.m3u8"}]},
        ]
        device_manager.async_create_stream_url.side_effect = RequestFailedException(
            "LV1001:Live already exist",
        )

        hd, sd = await client.async_get_stream_url("ABC123")

        assert hd == "https://hls.example.com/hd.m3u8"
        assert device_manager.async_get_stream_url.call_count == 2

    async def test_stream_url_raises_sleeping_error(self, api_client):
        """async_get_stream_url raises ImouDeviceSleepingError when device sleeping."""
        from pyimouapi.exceptions import RequestFailedException

        client, device_manager = api_client
        device_manager.async_get_stream_url.side_effect = RequestFailedException(
            "DV1030:Device is sleeping",
        )

        with pytest.raises(ImouDeviceSleepingError):
            await client.async_get_stream_url("ABC123")

    async def test_stream_url_raises_imou_error_for_other_errors(self, api_client):
        """async_get_stream_url raises ImouError for unrecognized errors."""
        from pyimouapi.exceptions import RequestFailedException

        client, device_manager = api_client
        device_manager.async_get_stream_url.side_effect = RequestFailedException(
            "GEN9999:Unknown error",
        )

        with pytest.raises(ImouError):
            await client.async_get_stream_url("ABC123")


class TestAsyncGetPrivacyMode:
    """Tests for ImouApiClient.async_get_privacy_mode."""

    @pytest.fixture
    def api_client(self):
        """Return ImouApiClient with mocked device manager."""
        from custom_components.imou_ha.api_client import ImouApiClient

        client = ImouApiClient("app_id", "secret", "openapi-fk.easy4ip.com")
        device_manager = AsyncMock()
        client._device_manager = device_manager
        return client, device_manager

    async def test_privacy_mode_returns_true_when_enabled(self, api_client):
        """async_get_privacy_mode returns True when API responds enable=True."""
        client, device_manager = api_client
        device_manager.async_get_device_status.return_value = {"enable": True}

        result = await client.async_get_privacy_mode("ABC123")

        assert result is True
        device_manager.async_get_device_status.assert_called_once_with(
            "ABC123", "0", "closeCamera",
        )

    async def test_privacy_mode_returns_false_when_disabled(self, api_client):
        """async_get_privacy_mode returns False when API responds enable=False."""
        client, device_manager = api_client
        device_manager.async_get_device_status.return_value = {"enable": False}

        result = await client.async_get_privacy_mode("ABC123")

        assert result is False

    async def test_privacy_mode_returns_false_when_missing(self, api_client):
        """async_get_privacy_mode returns False when enable key missing."""
        client, device_manager = api_client
        device_manager.async_get_device_status.return_value = {}

        result = await client.async_get_privacy_mode("ABC123")

        assert result is False


class TestAsyncSetPrivacyMode:
    """Tests for ImouApiClient.async_set_privacy_mode."""

    @pytest.fixture
    def api_client(self):
        """Return ImouApiClient with mocked device manager."""
        from custom_components.imou_ha.api_client import ImouApiClient

        client = ImouApiClient("app_id", "secret", "openapi-fk.easy4ip.com")
        device_manager = AsyncMock()
        client._device_manager = device_manager
        return client, device_manager

    async def test_set_privacy_mode_enabled_calls_correct_params(self, api_client):
        """async_set_privacy_mode calls device_manager with correct params when enabling."""
        client, device_manager = api_client
        device_manager.async_set_device_status.return_value = {}

        await client.async_set_privacy_mode("ABC123", True)

        device_manager.async_set_device_status.assert_called_once_with(
            "ABC123", "0", "closeCamera", True,
        )

    async def test_set_privacy_mode_disabled_calls_correct_params(self, api_client):
        """async_set_privacy_mode calls device_manager with correct params when disabling."""
        client, device_manager = api_client
        device_manager.async_set_device_status.return_value = {}

        await client.async_set_privacy_mode("ABC123", False)

        device_manager.async_set_device_status.assert_called_once_with(
            "ABC123", "0", "closeCamera", False,
        )

    async def test_set_privacy_mode_raises_sleeping_error(self, api_client):
        """async_set_privacy_mode raises ImouDeviceSleepingError for sleeping device."""
        from pyimouapi.exceptions import RequestFailedException

        client, device_manager = api_client
        device_manager.async_set_device_status.side_effect = RequestFailedException(
            "DV1030:Device is sleeping",
        )

        with pytest.raises(ImouDeviceSleepingError):
            await client.async_set_privacy_mode("ABC123", True)


# ---------------------------------------------------------------------------
# Coordinator tests — privacy polling
# ---------------------------------------------------------------------------


class TestCoordinatorPrivacyPolling:
    """Tests for coordinator privacy polling in _async_poll_device."""

    @pytest.fixture
    def make_coordinator(self, hass, sample_device_data):
        """Create a coordinator with mock client."""
        from custom_components.imou_ha.coordinator import ImouCoordinator

        client = AsyncMock()
        client.async_get_device_online_status = AsyncMock(
            return_value=DeviceStatus.ACTIVE,
        )
        client.async_get_privacy_mode = AsyncMock(return_value=True)
        # sample_device_data has MobileDetect so alarm status will also be polled
        client.async_get_alarm_status = AsyncMock(return_value=(False, False))
        coordinator = ImouCoordinator(hass, client, scan_interval=60)
        coordinator.data = {"ABC123DEF456": sample_device_data}
        return coordinator, client

    async def test_privacy_polled_for_closedcamera_device(
        self, make_coordinator, sample_device_data,
    ):
        """coordinator _async_poll_device polls privacy_enabled for CloseCamera devices."""
        coordinator, client = make_coordinator
        # sample_device_data has "CloseCamera" capability
        assert "CloseCamera" in sample_device_data.capabilities

        await coordinator._async_poll_device("ABC123DEF456", sample_device_data)

        client.async_get_privacy_mode.assert_called_once_with("ABC123DEF456")
        assert sample_device_data.privacy_enabled is True

    async def test_privacy_skipped_for_device_without_capability(self, hass):
        """coordinator _async_poll_device skips privacy polling without CloseCamera."""
        from custom_components.imou_ha.coordinator import ImouCoordinator

        # Create device without CloseCamera capability
        device = ImouDeviceData(
            serial="XYZ789",
            name="No Privacy Camera",
            model="IPC-A10",
            firmware="1.0",
            status=DeviceStatus.ACTIVE,
            capabilities={"Dormant"},  # no CloseCamera, no MobileDetect
        )

        client = AsyncMock()
        client.async_get_device_online_status = AsyncMock(
            return_value=DeviceStatus.ACTIVE,
        )
        client.async_get_privacy_mode = AsyncMock(return_value=True)
        coordinator = ImouCoordinator(hass, client, scan_interval=60)
        coordinator.data = {"XYZ789": device}

        await coordinator._async_poll_device("XYZ789", device)

        client.async_get_privacy_mode.assert_not_called()
        assert device.privacy_enabled is None  # unchanged


# ---------------------------------------------------------------------------
# ImouCamera entity tests (Task 2)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_coordinator(hass, sample_device_data):
    """Return a mock coordinator with one device."""

    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.data = {"ABC123DEF456": sample_device_data}
    coordinator.client = AsyncMock()
    coordinator.client.async_get_stream_url = AsyncMock(
        return_value=(
            "https://hls.example.com/hd.m3u8",
            "https://hls.example.com/sd.m3u8",
        ),
    )
    return coordinator


class TestImouCamera:
    """Tests for ImouCamera entity."""

    @pytest.fixture
    def camera(self, mock_coordinator):
        """Return an ImouCamera instance."""
        from custom_components.imou_ha.camera import ImouCamera

        return ImouCamera(mock_coordinator, "ABC123DEF456")

    async def test_stream_source_returns_hls_url(self, camera, mock_coordinator):
        """ImouCamera.stream_source() returns HD HLS URL from API."""
        url = await camera.stream_source()
        assert url == "https://hls.example.com/hd.m3u8"

    async def test_stream_source_cached_within_ttl(self, camera, mock_coordinator):
        """ImouCamera.stream_source() returns cached URL within TTL (no second API call)."""
        await camera.stream_source()
        await camera.stream_source()

        mock_coordinator.client.async_get_stream_url.assert_called_once()

    async def test_stream_source_fetches_fresh_after_ttl(self, camera, mock_coordinator):
        """ImouCamera.stream_source() fetches fresh URL after TTL expires."""

        await camera.stream_source()

        # Simulate TTL expiry by backdating the cache timestamp
        import time

        cached_url, _ts = camera._stream_url_cache["hd"]
        camera._stream_url_cache["hd"] = (cached_url, time.monotonic() - 301)  # past TTL (300s)

        await camera.stream_source()

        assert mock_coordinator.client.async_get_stream_url.call_count == 2

    async def test_stream_source_returns_none_on_error(self, camera, mock_coordinator):
        """ImouCamera.stream_source() returns None when API raises error (NFR1)."""
        mock_coordinator.client.async_get_stream_url.side_effect = ImouError("API error")

        url = await camera.stream_source()

        assert url is None

    async def test_extra_state_attributes_contains_sd_stream_url(
        self, camera, mock_coordinator,
    ):
        """ImouCamera.extra_state_attributes contains sd_stream_url key (STRM-02)."""
        # Populate cache first
        await camera.stream_source()

        attrs = camera.extra_state_attributes

        assert "sd_stream_url" in attrs
        assert attrs["sd_stream_url"] == "https://hls.example.com/sd.m3u8"

    async def test_async_camera_image_returns_none(self, camera):
        """ImouCamera.async_camera_image() returns None."""
        result = await camera.async_camera_image()
        assert result is None

    def test_supported_features_includes_stream(self, camera):
        """ImouCamera has CameraEntityFeature.STREAM in supported_features."""
        from homeassistant.components.camera import CameraEntityFeature

        assert camera.supported_features == CameraEntityFeature.STREAM

    async def test_async_setup_entry_creates_one_camera_per_device(
        self, hass, mock_coordinator,
    ):
        """async_setup_entry creates exactly one ImouCamera per device (D-06)."""

        from custom_components.imou_ha.camera import async_setup_entry

        entry = MagicMock()
        entry.runtime_data = mock_coordinator
        added_entities = []

        async_add_entities = MagicMock(side_effect=lambda entities: added_entities.extend(entities))

        await async_setup_entry(hass, entry, async_add_entities)

        assert len(added_entities) == 1
        from custom_components.imou_ha.camera import ImouCamera
        assert isinstance(added_entities[0], ImouCamera)
