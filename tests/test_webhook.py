"""Tests for the Imou webhook handler and lifecycle (HOOK-01 through HOOK-04)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from custom_components.imou_ha.const import (
    CONF_APP_ID,
    CONF_API_URL,
    CONF_APP_SECRET,
    DEFAULT_API_URL,
    DOMAIN,
    OPT_WEBHOOK_ENABLED,
)
from custom_components.imou_ha.coordinator import ImouCoordinator
from custom_components.imou_ha.exceptions import ImouError
from custom_components.imou_ha.models import DeviceStatus, ImouDeviceData

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

MOCK_WEBHOOK_ID = "test_webhook_id_abc123"
MOCK_APP_ID = "test_app_id"
MOCK_APP_SECRET = "test_app_secret"

MOCK_ENTRY_DATA = {
    CONF_APP_ID: MOCK_APP_ID,
    CONF_APP_SECRET: MOCK_APP_SECRET,
    CONF_API_URL: DEFAULT_API_URL,
    "webhook_id": MOCK_WEBHOOK_ID,
}

SAMPLE_DEVICE = ImouDeviceData(
    serial="ABC123DEF456",
    name="Front Door Camera",
    model="IPC-C22EP",
    firmware="2.840.0",
    status=DeviceStatus.ACTIVE,
    capabilities={"Dormant", "closedCamera", "MobileDetect"},
)


def _create_mock_entry(hass, options=None, data=None):
    """Create a MockConfigEntry with webhook data."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry_data = dict(MOCK_ENTRY_DATA)
    if data:
        entry_data.update(data)

    entry_options = {OPT_WEBHOOK_ENABLED: True}
    if options is not None:
        entry_options = options

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Imou (1 cameras)",
        data=entry_data,
        options=entry_options,
        version=1,
    )
    entry.add_to_hass(hass)
    return entry


def _make_coordinator_with_devices(hass, devices: dict) -> ImouCoordinator:
    """Create an ImouCoordinator mock with pre-loaded device data."""
    mock_client = AsyncMock()
    mock_client.async_set_message_callback = AsyncMock()
    coordinator = MagicMock(spec=ImouCoordinator)
    coordinator.client = mock_client
    coordinator.data = devices
    coordinator.async_set_updated_data = MagicMock()
    return coordinator


# ---------------------------------------------------------------------------
# HOOK-01: Webhook registration lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_registered_on_setup(hass):
    """HOOK-01: webhook.async_register is called with correct args when enabled."""
    entry = _create_mock_entry(hass, options={OPT_WEBHOOK_ENABLED: True})

    mock_client = AsyncMock()
    mock_coordinator = MagicMock(spec=ImouCoordinator)
    mock_coordinator.client = mock_client
    mock_coordinator.data = {"ABC123DEF456": SAMPLE_DEVICE}

    with (
        patch("custom_components.imou_ha.ImouApiClient", return_value=mock_client),
        patch.object(
            ImouCoordinator,
            "async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch.object(ImouCoordinator, "_async_setup", new_callable=AsyncMock),
        patch(
            "custom_components.imou_ha.webhook.async_register"
        ) as mock_register,
        patch(
            "custom_components.imou_ha.webhook.async_generate_url",
            return_value="https://ha.example.com/api/webhook/" + MOCK_WEBHOOK_ID,
        ),
        patch.object(
            ImouCoordinator,
            "client",
            new_callable=lambda: property(lambda self: mock_client),
            create=True,
        ),
    ):
        result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    mock_register.assert_called_once()
    call_kwargs = mock_register.call_args
    assert call_kwargs.args[1] == DOMAIN  # domain
    assert call_kwargs.args[3] == MOCK_WEBHOOK_ID  # webhook_id
    assert call_kwargs.kwargs.get("local_only") is False


@pytest.mark.asyncio
async def test_webhook_not_registered_when_disabled(hass):
    """HOOK-01: webhook.async_register is NOT called when OPT_WEBHOOK_ENABLED is False."""
    entry = _create_mock_entry(hass, options={OPT_WEBHOOK_ENABLED: False})

    with (
        patch("custom_components.imou_ha.ImouApiClient", return_value=AsyncMock()),
        patch.object(
            ImouCoordinator,
            "async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch.object(ImouCoordinator, "_async_setup", new_callable=AsyncMock),
        patch(
            "custom_components.imou_ha.webhook.async_register"
        ) as mock_register,
    ):
        result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    mock_register.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_registration_failure_continues(hass):
    """HOOK-01 / D-14: If Imou callback registration fails, setup still returns True.

    HA webhook is registered first then unregistered on Imou-side failure.
    """
    entry = _create_mock_entry(hass, options={OPT_WEBHOOK_ENABLED: True})

    mock_client = AsyncMock()
    mock_client.async_set_message_callback = AsyncMock(
        side_effect=ImouError("Imou callback failed")
    )

    with (
        patch("custom_components.imou_ha.ImouApiClient", return_value=mock_client),
        patch.object(
            ImouCoordinator,
            "async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch.object(ImouCoordinator, "_async_setup", new_callable=AsyncMock),
        patch(
            "custom_components.imou_ha.webhook.async_register"
        ),
        patch(
            "custom_components.imou_ha.webhook.async_unregister"
        ) as mock_unregister,
        patch(
            "custom_components.imou_ha.webhook.async_generate_url",
            return_value="https://ha.example.com/api/webhook/" + MOCK_WEBHOOK_ID,
        ),
    ):
        result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    mock_unregister.assert_called_once_with(hass, MOCK_WEBHOOK_ID)


# ---------------------------------------------------------------------------
# HOOK-01: Webhook unregistration on unload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_unregistered_on_unload(hass):
    """D-03: webhook.async_unregister is called and Imou callback disabled on unload."""
    entry = _create_mock_entry(hass, options={OPT_WEBHOOK_ENABLED: True})

    mock_client = AsyncMock()
    mock_client.async_set_message_callback = AsyncMock()

    with (
        patch("custom_components.imou_ha.ImouApiClient", return_value=mock_client),
        patch.object(
            ImouCoordinator,
            "async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch.object(ImouCoordinator, "_async_setup", new_callable=AsyncMock),
        patch("custom_components.imou_ha.webhook.async_register"),
        patch(
            "custom_components.imou_ha.webhook.async_unregister"
        ) as mock_unregister,
        patch(
            "custom_components.imou_ha.webhook.async_generate_url",
            return_value="https://ha.example.com/api/webhook/" + MOCK_WEBHOOK_ID,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert result is True
    mock_unregister.assert_called_with(hass, MOCK_WEBHOOK_ID)
    # async_set_message_callback called with enable=False on unload
    mock_client.async_set_message_callback.assert_awaited_with("", enable=False)


# ---------------------------------------------------------------------------
# HOOK-02: Event processing tests (handler called directly)
# ---------------------------------------------------------------------------


async def _call_handler(hass, entry, payload, coordinator):
    """Helper: call _make_webhook_handler(entry) directly with a mock request."""
    from custom_components.imou_ha import _make_webhook_handler

    entry.runtime_data = coordinator
    handler = _make_webhook_handler(entry)

    mock_request = MagicMock(spec=web.Request)
    mock_request.json = AsyncMock(return_value=payload)

    return await handler(hass, MOCK_WEBHOOK_ID, mock_request)


@pytest.mark.asyncio
async def test_motion_event_updates_state(hass):
    """HOOK-02 / D-05: videoMotion payload sets motion_detected=True on the device."""
    entry = _create_mock_entry(hass)
    device = ImouDeviceData(
        serial="ABC123DEF456",
        name="Front Door Camera",
        model="IPC-C22EP",
        firmware="2.840.0",
        status=DeviceStatus.ACTIVE,
        capabilities={"MobileDetect"},
    )
    coordinator = _make_coordinator_with_devices(hass, {"ABC123DEF456": device})

    await _call_handler(
        hass,
        entry,
        {"appId": MOCK_APP_ID, "did": "ABC123DEF456", "msgType": "videoMotion"},
        coordinator,
    )

    assert device.motion_detected is True


@pytest.mark.asyncio
async def test_human_event_updates_state(hass):
    """HOOK-02 / D-06: human payload sets human_detected=True on the device."""
    entry = _create_mock_entry(hass)
    device = ImouDeviceData(
        serial="ABC123DEF456",
        name="Front Door Camera",
        model="IPC-C22EP",
        firmware="2.840.0",
        status=DeviceStatus.ACTIVE,
        capabilities={"HeaderDetect"},
    )
    coordinator = _make_coordinator_with_devices(hass, {"ABC123DEF456": device})

    await _call_handler(
        hass,
        entry,
        {"appId": MOCK_APP_ID, "did": "ABC123DEF456", "msgType": "human"},
        coordinator,
    )

    assert device.human_detected is True


@pytest.mark.asyncio
async def test_unknown_msgtype_ignored(hass):
    """HOOK-02 / D-08: Unknown msgType leaves device state unchanged and returns None."""
    entry = _create_mock_entry(hass)
    device = ImouDeviceData(
        serial="ABC123DEF456",
        name="Front Door Camera",
        model="IPC-C22EP",
        firmware="2.840.0",
        status=DeviceStatus.ACTIVE,
        capabilities=set(),
    )
    coordinator = _make_coordinator_with_devices(hass, {"ABC123DEF456": device})

    response = await _call_handler(
        hass,
        entry,
        {"appId": MOCK_APP_ID, "did": "ABC123DEF456", "msgType": "unknownType"},
        coordinator,
    )

    assert device.motion_detected is False
    assert device.human_detected is False
    assert response is None


# ---------------------------------------------------------------------------
# HOOK-03: Device routing by did
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_device_routing_by_did(hass):
    """HOOK-03 / D-16: Only the device matching 'did' is updated."""
    entry = _create_mock_entry(hass)
    device_a = ImouDeviceData(
        serial="DEV_A",
        name="Camera A",
        model="IPC-C22EP",
        firmware="2.840.0",
        status=DeviceStatus.ACTIVE,
        capabilities=set(),
    )
    device_b = ImouDeviceData(
        serial="DEV_B",
        name="Camera B",
        model="IPC-C22EP",
        firmware="2.840.0",
        status=DeviceStatus.ACTIVE,
        capabilities=set(),
    )
    coordinator = _make_coordinator_with_devices(
        hass, {"DEV_A": device_a, "DEV_B": device_b}
    )

    await _call_handler(
        hass,
        entry,
        {"appId": MOCK_APP_ID, "did": "DEV_B", "msgType": "videoMotion"},
        coordinator,
    )

    assert device_b.motion_detected is True
    assert device_a.motion_detected is False


@pytest.mark.asyncio
async def test_unknown_device_ignored(hass):
    """HOOK-03: Unknown device serial is silently ignored, returns None (HTTP 200)."""
    entry = _create_mock_entry(hass)
    device = ImouDeviceData(
        serial="ABC123DEF456",
        name="Front Door Camera",
        model="IPC-C22EP",
        firmware="2.840.0",
        status=DeviceStatus.ACTIVE,
        capabilities=set(),
    )
    coordinator = _make_coordinator_with_devices(hass, {"ABC123DEF456": device})

    response = await _call_handler(
        hass,
        entry,
        {"appId": MOCK_APP_ID, "did": "UNKNOWN_SERIAL", "msgType": "videoMotion"},
        coordinator,
    )

    assert response is None


# ---------------------------------------------------------------------------
# HOOK-04: Payload validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_appid_mismatch_returns_401(hass):
    """HOOK-04 / D-15: Mismatched appId in payload returns HTTP 401."""
    entry = _create_mock_entry(hass)
    device = ImouDeviceData(
        serial="ABC123DEF456",
        name="Front Door Camera",
        model="IPC-C22EP",
        firmware="2.840.0",
        status=DeviceStatus.ACTIVE,
        capabilities=set(),
    )
    coordinator = _make_coordinator_with_devices(hass, {"ABC123DEF456": device})

    response = await _call_handler(
        hass,
        entry,
        {"appId": "wrong_app_id", "did": "ABC123DEF456", "msgType": "videoMotion"},
        coordinator,
    )

    assert response is not None
    assert response.status == 401


@pytest.mark.asyncio
async def test_missing_appid_not_rejected(hass):
    """HOOK-04 / Pitfall 6: Missing appId field does NOT return 401.

    Best-effort validation — if appId absent, process the event normally.
    """
    entry = _create_mock_entry(hass)
    device = ImouDeviceData(
        serial="ABC123DEF456",
        name="Front Door Camera",
        model="IPC-C22EP",
        firmware="2.840.0",
        status=DeviceStatus.ACTIVE,
        capabilities=set(),
    )
    coordinator = _make_coordinator_with_devices(hass, {"ABC123DEF456": device})

    response = await _call_handler(
        hass,
        entry,
        # No appId field
        {"did": "ABC123DEF456", "msgType": "videoMotion"},
        coordinator,
    )

    # Must NOT be a 401
    assert response is None or (hasattr(response, "status") and response.status != 401)
    assert device.motion_detected is True


@pytest.mark.asyncio
async def test_non_json_payload_returns_400(hass, mock_webhook_request):
    """D-08: Non-JSON payload (request.json raises ValueError) returns HTTP 400."""
    from custom_components.imou_ha import _make_webhook_handler

    entry = _create_mock_entry(hass)
    device = ImouDeviceData(
        serial="ABC123DEF456",
        name="Front Door Camera",
        model="IPC-C22EP",
        firmware="2.840.0",
        status=DeviceStatus.ACTIVE,
        capabilities=set(),
    )
    coordinator = _make_coordinator_with_devices(hass, {"ABC123DEF456": device})
    entry.runtime_data = coordinator
    handler = _make_webhook_handler(entry)

    bad_request = MagicMock(spec=web.Request)
    bad_request.json = AsyncMock(side_effect=ValueError("not valid json"))

    response = await handler(hass, MOCK_WEBHOOK_ID, bad_request)

    assert response is not None
    assert response.status == 400
