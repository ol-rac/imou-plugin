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
    device_ability: str = "Dormant,CloseCamera,MobileDetect",
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
        ), pytest.raises(ImouAuthError):
            await client.async_validate_credentials()

    async def test_connect_failed_raises_imou_error(self) -> None:
        from pyimouapi.exceptions import ConnectFailedException

        client = _make_client()
        with patch.object(
            client._client,
            "async_get_token",
            side_effect=ConnectFailedException("network down"),
        ), pytest.raises(ImouError):
            await client.async_validate_credentials()

    async def test_connect_failed_not_raises_imou_auth_error(self) -> None:
        """ConnectFailedException must not be wrapped as ImouAuthError."""
        from pyimouapi.exceptions import ConnectFailedException

        client = _make_client()
        with patch.object(
            client._client,
            "async_get_token",
            side_effect=ConnectFailedException("network down"),
        ), pytest.raises(ImouError) as exc_info:
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
            "custom_components.imou_ha.api_client.ImouDeviceManager",
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
            "custom_components.imou_ha.api_client.ImouDeviceManager",
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
        mock_device = _make_mock_device(device_ability="Dormant,CloseCamera")
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager",
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(return_value=[mock_device])
            result = await client.async_get_devices()

        assert "Dormant" in result[DEVICE_SERIAL].capabilities

    async def test_status_1_maps_to_active(self) -> None:
        client = _make_client()
        mock_device = _make_mock_device(device_status="1")
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager",
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(return_value=[mock_device])
            result = await client.async_get_devices()

        assert result[DEVICE_SERIAL].status == DeviceStatus.ACTIVE

    async def test_status_4_maps_to_sleeping(self) -> None:
        client = _make_client()
        mock_device = _make_mock_device(device_status="4", device_ability="")
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager",
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
            "custom_components.imou_ha.api_client.ImouDeviceManager",
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(return_value=[mock_device])
            result = await client.async_get_devices()

        assert result[DEVICE_SERIAL].status == DeviceStatus.SLEEPING

    async def test_capabilities_parsed_from_comma_string(self) -> None:
        client = _make_client()
        mock_device = _make_mock_device(device_ability="Dormant,CloseCamera,MobileDetect")
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager",
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(return_value=[mock_device])
            result = await client.async_get_devices()

        caps = result[DEVICE_SERIAL].capabilities
        assert "Dormant" in caps
        assert "CloseCamera" in caps
        assert "MobileDetect" in caps

    async def test_capabilities_parsed_from_list(self) -> None:
        client = _make_client()
        mock_device = _make_mock_device(device_ability=["Dormant", "CloseCamera"])
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager",
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(return_value=[mock_device])
            result = await client.async_get_devices()

        assert "Dormant" in result[DEVICE_SERIAL].capabilities

    async def test_fl1001_raises_imou_license_error(self) -> None:
        from pyimouapi.exceptions import RequestFailedException

        client = _make_client()
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager",
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(
                side_effect=RequestFailedException("FL1001:license limit reached"),
            )
            with pytest.raises(ImouLicenseError):
                await client.async_get_devices()

    async def test_op1011_raises_imou_rate_limit_error(self) -> None:
        from pyimouapi.exceptions import RequestFailedException

        client = _make_client()
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager",
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(
                side_effect=RequestFailedException("OP1011:rate limit exceeded"),
            )
            with pytest.raises(ImouRateLimitError):
                await client.async_get_devices()

    async def test_dv1007_raises_imou_device_offline_error(self) -> None:
        from pyimouapi.exceptions import RequestFailedException

        client = _make_client()
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager",
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(
                side_effect=RequestFailedException("DV1007:device offline"),
            )
            with pytest.raises(ImouDeviceOfflineError):
                await client.async_get_devices()

    async def test_dv1030_raises_imou_device_sleeping_error(self) -> None:
        from pyimouapi.exceptions import RequestFailedException

        client = _make_client()
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager",
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(
                side_effect=RequestFailedException("DV1030:device sleeping"),
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
                "custom_components.imou_ha.api_client.ImouDeviceManager",
            ) as MockManager:
                MockManager.return_value.async_get_devices = AsyncMock(side_effect=exc)
                with pytest.raises(ImouError):
                    await client.async_get_devices()

    async def test_debug_logged_on_api_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """Debug logging must occur on API errors (INFR-03)."""
        from pyimouapi.exceptions import ConnectFailedException

        client = _make_client()
        with patch(
            "custom_components.imou_ha.api_client.ImouDeviceManager",
        ) as MockManager:
            MockManager.return_value.async_get_devices = AsyncMock(
                side_effect=ConnectFailedException("network down"),
            )
            with caplog.at_level(logging.DEBUG, logger="custom_components.imou_ha.api_client"):
                with pytest.raises(ImouError):
                    await client.async_get_devices()

        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debug_records) >= 1


# ---------------------------------------------------------------------------
# async_get_alarm_status
# ---------------------------------------------------------------------------


class TestAlarmStatus:
    async def test_default_scan_interval_is_300(self) -> None:
        """DEFAULT_SCAN_INTERVAL must be 300 per D-09."""
        from custom_components.imou_ha.const import DEFAULT_SCAN_INTERVAL

        assert DEFAULT_SCAN_INTERVAL == 300

    async def test_capability_human_detect_constant(self) -> None:
        """CAPABILITY_HUMAN_DETECT must be 'HeaderDetect'."""
        from custom_components.imou_ha.const import CAPABILITY_HUMAN_DETECT

        assert CAPABILITY_HUMAN_DETECT == "HeaderDetect"

    async def test_capability_human_detect_ai_constant(self) -> None:
        """CAPABILITY_HUMAN_DETECT_AI must be 'AiHuman'."""
        from custom_components.imou_ha.const import CAPABILITY_HUMAN_DETECT_AI

        assert CAPABILITY_HUMAN_DETECT_AI == "AiHuman"

    async def test_capability_human_detect_smd_constant(self) -> None:
        """CAPABILITY_HUMAN_DETECT_SMD must be 'SMDH'."""
        from custom_components.imou_ha.const import CAPABILITY_HUMAN_DETECT_SMD

        assert CAPABILITY_HUMAN_DETECT_SMD == "SMDH"

    async def test_motion_only_alarm_type_1(self) -> None:
        """alarm with type=1 only -> (True, False)."""
        client = _make_client()
        client._client.async_request_api = AsyncMock(
            return_value={"alarms": [{"type": 1, "event": "MobileDetect"}]},
        )
        result = await client.async_get_alarm_status(
            "DEV123", "2026-03-30 10:00:00", "2026-03-30 10:05:00",
        )
        assert result == (True, False)

    async def test_human_only_alarm_type_0(self) -> None:
        """alarm with type=0 only -> (False, True)."""
        client = _make_client()
        client._client.async_request_api = AsyncMock(
            return_value={"alarms": [{"type": 0, "event": "HumanDetect"}]},
        )
        result = await client.async_get_alarm_status(
            "DEV123", "2026-03-30 10:00:00", "2026-03-30 10:05:00",
        )
        assert result == (False, True)

    async def test_both_motion_and_human_alarms(self) -> None:
        """alarms with type=1 and type=0 -> (True, True)."""
        client = _make_client()
        client._client.async_request_api = AsyncMock(
            return_value={
                "alarms": [
                    {"type": 1, "event": "MobileDetect"},
                    {"type": 0, "event": "HumanDetect"},
                ],
            },
        )
        result = await client.async_get_alarm_status(
            "DEV123", "2026-03-30 10:00:00", "2026-03-30 10:05:00",
        )
        assert result == (True, True)

    async def test_empty_alarms_returns_false_false(self) -> None:
        """empty alarms array -> (False, False)."""
        client = _make_client()
        client._client.async_request_api = AsyncMock(
            return_value={"alarms": []},
        )
        result = await client.async_get_alarm_status(
            "DEV123", "2026-03-30 10:00:00", "2026-03-30 10:05:00",
        )
        assert result == (False, False)

    async def test_accessory_human_body_type_4(self) -> None:
        """alarm with type=4 (accessory human body) -> (False, True)."""
        client = _make_client()
        client._client.async_request_api = AsyncMock(
            return_value={"alarms": [{"type": 4, "event": "AccessoryHumanBody"}]},
        )
        result = await client.async_get_alarm_status(
            "DEV123", "2026-03-30 10:00:00", "2026-03-30 10:05:00",
        )
        assert result == (False, True)

    async def test_dv1030_raises_sleeping_error(self) -> None:
        """RequestFailedException with DV1030 raises ImouDeviceSleepingError."""
        from pyimouapi.exceptions import RequestFailedException

        client = _make_client()
        client._client.async_request_api = AsyncMock(
            side_effect=RequestFailedException("DV1030:Device is sleeping"),
        )
        with pytest.raises(ImouDeviceSleepingError):
            await client.async_get_alarm_status(
                "DEV123", "2026-03-30 10:00:00", "2026-03-30 10:05:00",
            )

    async def test_dv1007_raises_offline_error(self) -> None:
        """RequestFailedException with DV1007 raises ImouDeviceOfflineError."""
        from pyimouapi.exceptions import RequestFailedException

        client = _make_client()
        client._client.async_request_api = AsyncMock(
            side_effect=RequestFailedException("DV1007:device offline"),
        )
        with pytest.raises(ImouDeviceOfflineError):
            await client.async_get_alarm_status(
                "DEV123", "2026-03-30 10:00:00", "2026-03-30 10:05:00",
            )

    async def test_calls_get_alarm_message_endpoint(self) -> None:
        """async_get_alarm_status calls /openapi/getAlarmMessage with correct params."""
        client = _make_client()
        client._client.async_request_api = AsyncMock(return_value={"alarms": []})
        await client.async_get_alarm_status("DEV123", "2026-03-30 10:00:00", "2026-03-30 10:05:00")

        client._client.async_request_api.assert_awaited_once()
        call_args = client._client.async_request_api.call_args
        assert call_args[0][0] == "/openapi/getAlarmMessage"
        params = call_args[0][1]
        assert params["deviceId"] == "DEV123"
        assert params["channelId"] == "0"
        assert params["beginTime"] == "2026-03-30 10:00:00"
        assert params["endTime"] == "2026-03-30 10:05:00"
        assert params["count"] == 30


# ---------------------------------------------------------------------------
# async_set_message_callback / async_get_message_callback
# ---------------------------------------------------------------------------


class TestMessageCallback:
    async def test_set_message_callback_enable_true(self) -> None:
        """async_set_message_callback with enable=True calls setMessageCallback with correct params."""
        client = _make_client()
        client._client.async_request_api = AsyncMock(return_value={})
        await client.async_set_message_callback(
            "https://example.com/api/webhook/abc", enable=True,
        )

        client._client.async_request_api.assert_awaited_once()
        call_args = client._client.async_request_api.call_args
        assert call_args[0][0] == "/openapi/setMessageCallback"
        params = call_args[0][1]
        assert params["callbackFlag"] == "alarm,deviceStatus"
        assert params["callbackUrl"] == "https://example.com/api/webhook/abc"
        assert params["status"] == "on"

    async def test_set_message_callback_enable_false(self) -> None:
        """async_set_message_callback with enable=False calls setMessageCallback with status=off."""
        client = _make_client()
        client._client.async_request_api = AsyncMock(return_value={})
        await client.async_set_message_callback(
            "https://example.com/api/webhook/abc", enable=False,
        )

        client._client.async_request_api.assert_awaited_once()
        call_args = client._client.async_request_api.call_args
        assert call_args[0][0] == "/openapi/setMessageCallback"
        params = call_args[0][1]
        assert params["status"] == "off"
        assert "callbackFlag" not in params
        assert "callbackUrl" not in params

    async def test_set_message_callback_translates_request_failed_exception(self) -> None:
        """RequestFailedException is translated to ImouError subtypes."""
        from pyimouapi.exceptions import RequestFailedException

        client = _make_client()
        client._client.async_request_api = AsyncMock(
            side_effect=RequestFailedException("DV1030:device sleeping"),
        )
        with pytest.raises(ImouDeviceSleepingError):
            await client.async_set_message_callback(
                "https://example.com/api/webhook/abc", enable=True,
            )

    async def test_set_message_callback_translates_imou_exception(self) -> None:
        """ImouException (non-RequestFailed) is translated to ImouError."""
        from pyimouapi.exceptions import ImouException

        client = _make_client()
        client._client.async_request_api = AsyncMock(
            side_effect=ImouException("generic error"),
        )
        with pytest.raises(ImouError):
            await client.async_set_message_callback(
                "https://example.com/api/webhook/abc", enable=True,
            )

    async def test_get_message_callback_calls_correct_endpoint(self) -> None:
        """async_get_message_callback calls /openapi/getMessageCallback with empty params."""
        client = _make_client()
        client._client.async_request_api = AsyncMock(
            return_value={"callbackUrl": "https://example.com/api/webhook/abc", "status": "on"},
        )
        result = await client.async_get_message_callback()

        client._client.async_request_api.assert_awaited_once()
        call_args = client._client.async_request_api.call_args
        assert call_args[0][0] == "/openapi/getMessageCallback"
        assert call_args[0][1] == {}
        assert result["status"] == "on"

    async def test_get_message_callback_translates_request_failed_exception(self) -> None:
        """RequestFailedException is translated to ImouError subtypes."""
        from pyimouapi.exceptions import RequestFailedException

        client = _make_client()
        client._client.async_request_api = AsyncMock(
            side_effect=RequestFailedException("OP1011:rate limit"),
        )
        with pytest.raises(ImouRateLimitError):
            await client.async_get_message_callback()


# ---------------------------------------------------------------------------
# Wake-up method tests (D-01, D-02)
# ---------------------------------------------------------------------------


def test_wake_up_device_method_removed() -> None:
    """Confirm async_wake_up_device is removed from ImouApiClient (D-02)."""
    assert not hasattr(ImouApiClient, "async_wake_up_device")


class TestAsyncWakeUpViaDormant:
    async def test_wake_up_via_dormant_calls_correct_api(self) -> None:
        """async_wake_up_via_dormant calls setDeviceCameraStatus with closeDormant params (D-01)."""
        client = _make_client()
        client._client.async_request_api = AsyncMock(return_value={})

        await client.async_wake_up_via_dormant("ABC123DEF456")

        client._client.async_request_api.assert_awaited_once()
        call_args = client._client.async_request_api.call_args
        assert call_args[0][0] == "/openapi/setDeviceCameraStatus"
        params = call_args[0][1]
        assert params["deviceId"] == "ABC123DEF456"
        assert params["channelId"] == "0"
        assert params["enableType"] == "closeDormant"
        assert params["enable"] is True
