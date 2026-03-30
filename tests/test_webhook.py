"""Tests for webhook handler and lifecycle — HOOK-01 through HOOK-04."""

from __future__ import annotations

from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.imou_ha.const import CONF_APP_ID, DOMAIN, OPT_WEBHOOK_ENABLED
from custom_components.imou_ha.exceptions import ImouError
from custom_components.imou_ha.models import DeviceStatus, ImouDeviceData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    *,
    app_id: str = "test_app",
    webhook_id: str = "test_webhook_id",
    webhook_enabled: bool = True,
    app_secret: str = "test_secret",
    api_url: str = "api_fk",
) -> MagicMock:
    """Create a minimal mock config entry."""
    entry = MagicMock()
    entry.data = {
        CONF_APP_ID: app_id,
        "app_secret": app_secret,
        "api_url": api_url,
        "webhook_id": webhook_id,
    }
    entry.options = {OPT_WEBHOOK_ENABLED: webhook_enabled}
    entry.title = "Imou Test"
    entry.entry_id = "test_entry_id"
    return entry


def _make_coordinator(devices: dict[str, ImouDeviceData]) -> MagicMock:
    """Create a minimal mock coordinator."""
    coordinator = MagicMock()
    coordinator.data = devices
    coordinator.client = AsyncMock()
    coordinator.async_set_updated_data = MagicMock()
    return coordinator


def _make_device(serial: str = "ABC123DEF456") -> ImouDeviceData:
    """Create a test device."""
    return ImouDeviceData(
        serial=serial,
        name="Test Camera",
        model="IPC-C22EP",
        firmware="2.840.0000000.28.R",
        status=DeviceStatus.ACTIVE,
        capabilities={"Dormant", "closedCamera", "MobileDetect"},
    )


# ---------------------------------------------------------------------------
# HOOK-01: Webhook lifecycle — registration on setup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_registered_on_setup(hass):
    """HOOK-01: Webhook registered with HA and Imou when enabled."""
    from custom_components.imou_ha import async_setup_entry
    from custom_components.imou_ha.budget import ImouBudgetState
    from custom_components.imou_ha.coordinator import ImouCoordinator

    entry = _make_entry(webhook_enabled=True)
    device = _make_device()
    coordinator = _make_coordinator({"ABC123DEF456": device})

    with (
        patch(
            "custom_components.imou_ha.ImouApiClient",
        ) as mock_client_cls,
        patch(
            "custom_components.imou_ha.ImouCoordinator",
        ) as mock_coord_cls,
        patch(
            "homeassistant.components.webhook.async_register"
        ) as mock_register,
        patch(
            "homeassistant.components.webhook.async_generate_url",
            return_value="https://ha.example.com/api/webhook/test_webhook_id",
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            return_value=True,
        ),
    ):
        mock_client_cls.return_value = AsyncMock()
        mock_coord_cls.return_value = coordinator
        coordinator.async_config_entry_first_refresh = AsyncMock()

        await async_setup_entry(hass, entry)

        mock_register.assert_called_once()
        call_kwargs = mock_register.call_args
        assert call_kwargs.kwargs.get("local_only") is False or (
            len(call_kwargs.args) >= 4
        )


@pytest.mark.asyncio
async def test_webhook_not_registered_when_disabled(hass):
    """HOOK-01: No webhook registered when OPT_WEBHOOK_ENABLED is False."""
    from custom_components.imou_ha import async_setup_entry

    entry = _make_entry(webhook_enabled=False)
    device = _make_device()
    coordinator = _make_coordinator({"ABC123DEF456": device})

    with (
        patch("custom_components.imou_ha.ImouApiClient") as mock_client_cls,
        patch("custom_components.imou_ha.ImouCoordinator") as mock_coord_cls,
        patch(
            "homeassistant.components.webhook.async_register"
        ) as mock_register,
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            return_value=True,
        ),
    ):
        mock_client_cls.return_value = AsyncMock()
        mock_coord_cls.return_value = coordinator
        coordinator.async_config_entry_first_refresh = AsyncMock()

        result = await async_setup_entry(hass, entry)

        assert result is True
        mock_register.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_registration_failure_continues(hass):
    """HOOK-01 / D-14: Webhook Imou registration failure doesn't block setup."""
    from custom_components.imou_ha import async_setup_entry

    entry = _make_entry(webhook_enabled=True)
    device = _make_device()
    coordinator = _make_coordinator({"ABC123DEF456": device})
    coordinator.client.async_set_message_callback = AsyncMock(
        side_effect=ImouError("Registration failed")
    )

    with (
        patch("custom_components.imou_ha.ImouApiClient") as mock_client_cls,
        patch("custom_components.imou_ha.ImouCoordinator") as mock_coord_cls,
        patch(
            "homeassistant.components.webhook.async_register"
        ) as mock_register,
        patch(
            "homeassistant.components.webhook.async_unregister"
        ) as mock_unregister,
        patch(
            "homeassistant.components.webhook.async_generate_url",
            return_value="https://ha.example.com/api/webhook/test_webhook_id",
        ),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            return_value=True,
        ),
    ):
        mock_client_cls.return_value = coordinator.client
        mock_coord_cls.return_value = coordinator
        coordinator.async_config_entry_first_refresh = AsyncMock()

        result = await async_setup_entry(hass, entry)

        assert result is True
        # HA webhook was registered then unregistered after Imou API failure
        mock_unregister.assert_called_once_with(hass, "test_webhook_id")


# ---------------------------------------------------------------------------
# HOOK-02: Event processing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_motion_event_updates_state(mock_webhook_request):
    """HOOK-02 / D-05: videoMotion payload sets motion_detected=True."""
    from custom_components.imou_ha import _make_webhook_handler

    device = _make_device()
    entry = _make_entry()
    coordinator = _make_coordinator({"ABC123DEF456": device})
    entry.runtime_data = coordinator

    handler = _make_webhook_handler(entry)
    request = mock_webhook_request(
        {"appId": "test_app", "did": "ABC123DEF456", "msgType": "videoMotion"}
    )

    result = await handler(MagicMock(), "test_webhook_id", request)

    assert device.motion_detected is True
    coordinator.async_set_updated_data.assert_called_once()
    assert result is None


@pytest.mark.asyncio
async def test_human_event_updates_state(mock_webhook_request):
    """HOOK-02 / D-06: human payload sets human_detected=True."""
    from custom_components.imou_ha import _make_webhook_handler

    device = _make_device()
    entry = _make_entry()
    coordinator = _make_coordinator({"ABC123DEF456": device})
    entry.runtime_data = coordinator

    handler = _make_webhook_handler(entry)
    request = mock_webhook_request(
        {"appId": "test_app", "did": "ABC123DEF456", "msgType": "human"}
    )

    result = await handler(MagicMock(), "test_webhook_id", request)

    assert device.human_detected is True
    coordinator.async_set_updated_data.assert_called_once()
    assert result is None


@pytest.mark.asyncio
async def test_unknown_msgtype_ignored(mock_webhook_request):
    """HOOK-02 / D-08: Unknown msgType silently ignored, returns None."""
    from custom_components.imou_ha import _make_webhook_handler

    device = _make_device()
    entry = _make_entry()
    coordinator = _make_coordinator({"ABC123DEF456": device})
    entry.runtime_data = coordinator

    handler = _make_webhook_handler(entry)
    request = mock_webhook_request(
        {"appId": "test_app", "did": "ABC123DEF456", "msgType": "unknownType"}
    )

    result = await handler(MagicMock(), "test_webhook_id", request)

    assert device.motion_detected is False
    assert device.human_detected is False
    assert result is None


# ---------------------------------------------------------------------------
# HOOK-03: Device routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_device_routing_by_did(mock_webhook_request):
    """HOOK-03 / D-16: Event routed only to the device matching did."""
    from custom_components.imou_ha import _make_webhook_handler

    dev_a = _make_device("DEV_A")
    dev_b = _make_device("DEV_B")
    entry = _make_entry()
    coordinator = _make_coordinator({"DEV_A": dev_a, "DEV_B": dev_b})
    entry.runtime_data = coordinator

    handler = _make_webhook_handler(entry)
    request = mock_webhook_request(
        {"appId": "test_app", "did": "DEV_B", "msgType": "videoMotion"}
    )

    await handler(MagicMock(), "test_webhook_id", request)

    assert dev_b.motion_detected is True
    assert dev_a.motion_detected is False


@pytest.mark.asyncio
async def test_unknown_device_ignored(mock_webhook_request):
    """HOOK-03: Unknown device serial silently ignored, returns None."""
    from custom_components.imou_ha import _make_webhook_handler

    device = _make_device()
    entry = _make_entry()
    coordinator = _make_coordinator({"ABC123DEF456": device})
    entry.runtime_data = coordinator

    handler = _make_webhook_handler(entry)
    request = mock_webhook_request(
        {"appId": "test_app", "did": "UNKNOWN_SERIAL", "msgType": "videoMotion"}
    )

    result = await handler(MagicMock(), "test_webhook_id", request)

    assert result is None
    coordinator.async_set_updated_data.assert_not_called()


# ---------------------------------------------------------------------------
# HOOK-04: Payload validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_appid_mismatch_returns_401(mock_webhook_request):
    """HOOK-04 / D-15: Mismatched appId returns HTTP 401."""
    from aiohttp import web

    from custom_components.imou_ha import _make_webhook_handler

    device = _make_device()
    entry = _make_entry(app_id="test_app")
    coordinator = _make_coordinator({"ABC123DEF456": device})
    entry.runtime_data = coordinator

    handler = _make_webhook_handler(entry)
    request = mock_webhook_request(
        {"appId": "wrong_app_id", "did": "ABC123DEF456", "msgType": "videoMotion"}
    )

    response = await handler(MagicMock(), "test_webhook_id", request)

    assert isinstance(response, web.Response)
    assert response.status == HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_missing_appid_not_rejected(mock_webhook_request):
    """HOOK-04 / Pitfall 6: Missing appId field processed normally (best-effort)."""
    from custom_components.imou_ha import _make_webhook_handler

    device = _make_device()
    entry = _make_entry()
    coordinator = _make_coordinator({"ABC123DEF456": device})
    entry.runtime_data = coordinator

    handler = _make_webhook_handler(entry)
    request = mock_webhook_request(
        {"did": "ABC123DEF456", "msgType": "videoMotion"}
    )

    result = await handler(MagicMock(), "test_webhook_id", request)

    # Missing appId should NOT return 401
    assert not (hasattr(result, "status") and result.status == HTTPStatus.UNAUTHORIZED)
    assert device.motion_detected is True


# ---------------------------------------------------------------------------
# Lifecycle: unload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_unregistered_on_unload(hass):
    """D-03: Webhook deregistered and Imou callback disabled on entry unload."""
    from custom_components.imou_ha import async_unload_entry

    entry = _make_entry(webhook_enabled=True)
    coordinator = _make_coordinator({"ABC123DEF456": _make_device()})
    coordinator.client.async_set_message_callback = AsyncMock()
    entry.runtime_data = coordinator

    with (
        patch(
            "homeassistant.components.webhook.async_unregister"
        ) as mock_unregister,
        patch(
            "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
            return_value=True,
        ),
    ):
        result = await async_unload_entry(hass, entry)

        assert result is True
        mock_unregister.assert_called_once_with(hass, "test_webhook_id")
        coordinator.client.async_set_message_callback.assert_called_once_with(
            "", enable=False
        )


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_json_payload_returns_400(mock_webhook_request):
    """D-08: Non-JSON payload returns HTTP 400."""
    from aiohttp import web

    from custom_components.imou_ha import _make_webhook_handler

    device = _make_device()
    entry = _make_entry()
    coordinator = _make_coordinator({"ABC123DEF456": device})
    entry.runtime_data = coordinator

    handler = _make_webhook_handler(entry)

    # Override request.json to raise ValueError
    request = MagicMock()
    request.json = AsyncMock(side_effect=ValueError("Not valid JSON"))

    response = await handler(MagicMock(), "test_webhook_id", request)

    assert isinstance(response, web.Response)
    assert response.status == HTTPStatus.BAD_REQUEST
