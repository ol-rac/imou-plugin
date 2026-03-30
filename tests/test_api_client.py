"""Tests for the ImouApiClient — sole pyimouapi boundary."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.imou_ha.api_client import ImouApiClient
from custom_components.imou_ha.exceptions import (
    ImouAuthError,
    ImouDeviceOfflineError,
    ImouDeviceSleepingError,
    ImouError,
    ImouLicenseError,
    ImouRateLimitError,
)
from custom_components.imou_ha.models import DeviceStatus, ImouDeviceData

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEVICE_SERIAL = "ABC123DEF456"


def _make_mock_device(
    device_id: str = DEVICE_SERIAL,
    device_name: str = "Front Door",
    device_model: str = "IPC-C22EP",
    device_version: str = "2.840.0000000.28.R",
    device_status: str = "1",
    device_ability: str = "Dormant,closedCamera,MobileDetect",
) -> MagicMock:
    """Build a mock ImouDevice with the given properties."""
    dev = MagicMock()
    dev.device_id = device_id
    dev.device_name = device_name
    dev.device_model = device_model
    dev.device_version = device_version
    dev.device_status = device_status
    dev.device_ability = device_ability
    return dev


def _make_client() -> ImouApiClient:
    """Instantiate ImouApiClient without hitting the network."""
    return ImouApiClient("app123", "secret456", "openapi-fk.easy4ip.com")


# ---------------------------------------------------------------------------
# async_validate_credentials
# ---------------------------------------------------------------------------


class TestAsyncValidateCredentials:
    async def test_calls_async_get_token(self) -> None:
        client = _make_client()
        with patch.object(client._client, "async_get_token", new_callable=AsyncMock) as mock_token:
            await client.async_validate_credentials()
        mock_token.assert_awaited_once()

    async def test_invalid_app_id_raises_imou_auth_error(self) -> None:
        from pyimouapi.exceptions import InvalidAppIdOrSecretException

        client = _make_client()
        with patch.object(
            client._client,
            "async_get_token",
            side_effect=InvalidAppIdOrSecretException("bad credentials"),
        ):
            with pytest.raises(ImouAuthError):
                await client.async_validate_credentials()

    async def test_connect_failed_raises_imou_error(self) -> None:
        from pyimouapi.exceptions import ConnectFailedException

        client = _make_client()
        with patch.object(
            client._client,
            "async_get_token",
            side_effect=ConnectFailedException("network down"),
        ):
            with pytest.raises(ImouError):
                await client.async_validate_credentials()

    async def test_connect_failed_not_raises_imou_auth_error(self) -> None:
        """ConnectFailedException must not be wrapped as ImouAuthError."""
        from pyimouapi.exceptions import ConnectFailedException

        client = _make_client()
        with patch.object(
            client._client,
            "async_get_token",
            side_effect=ConnectFailedException("network down"),
        ):
            with pytest.raises(ImouError) as exc_info:
                await client.async_validate_credentials()
        assert not isinstance(exc_info.value, ImouAuthError)

    async def test_debug_logged_on_auth_error(self, caplog: pytest.LogCaptureFixture) -> None:
        from pyimouapi.exceptions import InvalidAppIdOrSecretException

        client = _make_client()
        with patch.object(
            client._client,
            "async_get_token",
            side_effect=InvalidAppIdOrSecretException("bad credentials"),
        ):
            with caplog.at_level(logging.DEBUG, logger="custom_components.imou_ha.api_client"):
                with pytest.raises(ImouAuthError):
                    await client.async_validate_credentials()
        assert any("debug" not in r.levelname.lower() or r.levelname.lower() == "debug"
                   for r in caplog.records if "imou_ha.api_client" in r.name or True)
        # Verify debug messages were logged
        debug_messages = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_messages) >= 1


# ---------------------------------------------------------------------------
# async_get_devices
# ---------------------------------------------------------------------------


class TestAsyncGetDevices:
    async def test_returns_dict_keyed_by_serial(self) -> None:
        client = _make_client()
        mock_device = _make_mock_device()
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager"
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(return_value=[mock_device])
            result = await client.async_get_devices()

        assert isinstance(result, dict)
        assert DEVICE_SERIAL in result
        assert isinstance(result[DEVICE_SERIAL], ImouDeviceData)

    async def test_device_has_correct_fields(self) -> None:
        client = _make_client()
        mock_device = _make_mock_device()
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager"
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(return_value=[mock_device])
            result = await client.async_get_devices()

        device = result[DEVICE_SERIAL]
        assert device.serial == DEVICE_SERIAL
        assert device.name == "Front Door"
        assert device.model == "IPC-C22EP"
        assert device.firmware == "2.840.0000000.28.R"

    async def test_dormant_in_abilities_sets_dormant_capability(self) -> None:
        """Device with 'Dormant' in abilities must have it in capabilities set."""
        client = _make_client()
        mock_device = _make_mock_device(device_ability="Dormant,closedCamera")
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager"
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(return_value=[mock_device])
            result = await client.async_get_devices()

        assert "Dormant" in result[DEVICE_SERIAL].capabilities

    async def test_status_1_maps_to_active(self) -> None:
        client = _make_client()
        mock_device = _make_mock_device(device_status="1")
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager"
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(return_value=[mock_device])
            result = await client.async_get_devices()

        assert result[DEVICE_SERIAL].status == DeviceStatus.ACTIVE

    async def test_status_4_maps_to_sleeping(self) -> None:
        client = _make_client()
        mock_device = _make_mock_device(device_status="4", device_ability="")
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager"
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(return_value=[mock_device])
            result = await client.async_get_devices()

        assert result[DEVICE_SERIAL].status == DeviceStatus.SLEEPING

    async def test_dormant_capability_maps_to_sleeping(self) -> None:
        """Device with Dormant in capabilities but status != 4 is still sleeping."""
        client = _make_client()
        # device_status "0" (offline) but has Dormant capability -> sleeping
        mock_device = _make_mock_device(device_status="0", device_ability="Dormant")
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager"
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(return_value=[mock_device])
            result = await client.async_get_devices()

        assert result[DEVICE_SERIAL].status == DeviceStatus.SLEEPING

    async def test_capabilities_parsed_from_comma_string(self) -> None:
        client = _make_client()
        mock_device = _make_mock_device(device_ability="Dormant,closedCamera,MobileDetect")
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager"
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(return_value=[mock_device])
            result = await client.async_get_devices()

        caps = result[DEVICE_SERIAL].capabilities
        assert "Dormant" in caps
        assert "closedCamera" in caps
        assert "MobileDetect" in caps

    async def test_capabilities_parsed_from_list(self) -> None:
        client = _make_client()
        mock_device = _make_mock_device(device_ability=["Dormant", "closedCamera"])
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager"
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(return_value=[mock_device])
            result = await client.async_get_devices()

        assert "Dormant" in result[DEVICE_SERIAL].capabilities

    async def test_fl1001_raises_imou_license_error(self) -> None:
        from pyimouapi.exceptions import RequestFailedException

        client = _make_client()
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager"
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(
                side_effect=RequestFailedException("FL1001:license limit reached")
            )
            with pytest.raises(ImouLicenseError):
                await client.async_get_devices()

    async def test_op1011_raises_imou_rate_limit_error(self) -> None:
        from pyimouapi.exceptions import RequestFailedException

        client = _make_client()
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager"
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(
                side_effect=RequestFailedException("OP1011:rate limit exceeded")
            )
            with pytest.raises(ImouRateLimitError):
                await client.async_get_devices()

    async def test_dv1007_raises_imou_device_offline_error(self) -> None:
        from pyimouapi.exceptions import RequestFailedException

        client = _make_client()
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager"
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(
                side_effect=RequestFailedException("DV1007:device offline")
            )
            with pytest.raises(ImouDeviceOfflineError):
                await client.async_get_devices()

    async def test_dv1030_raises_imou_device_sleeping_error(self) -> None:
        from pyimouapi.exceptions import RequestFailedException

        client = _make_client()
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager"
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(
                side_effect=RequestFailedException("DV1030:device sleeping")
            )
            with pytest.raises(ImouDeviceSleepingError):
                await client.async_get_devices()

    async def test_no_pyimouapi_exceptions_escape(self) -> None:
        """Only ImouError subtypes must propagate — no raw pyimouapi exceptions."""
        from pyimouapi.exceptions import ConnectFailedException, RequestFailedException

        client = _make_client()
        for exc in [
            ConnectFailedException("conn fail"),
            RequestFailedException("UNKNOWN:err"),
        ]:
            with patch(
                "custom_components.imou_ha.api_client.ImouDeviceManager"
            ) as MockManager:
                MockManager.return_value.async_get_devices = AsyncMock(side_effect=exc)
                with pytest.raises(ImouError):
                    await client.async_get_devices()

    async def test_debug_logged_on_api_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """Debug logging must occur on API errors (INFR-03)."""
        from pyimouapi.exceptions import ConnectFailedException

        client = _make_client()
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager"
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(
                side_effect=ConnectFailedException("network down")
            )
            with caplog.at_level(logging.DEBUG, logger="custom_components.imou_ha.api_client"):
                with pytest.raises(ImouError):
                    await client.async_get_devices()

        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) >= 1
