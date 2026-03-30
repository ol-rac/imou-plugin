"""Imou integration for Home Assistant."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.helpers.network import NoURLAvailableError

from .api_client import ImouApiClient
from .exceptions import ImouError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
from .const import (
    API_BASE_URLS,
    CONF_API_URL,
    CONF_APP_ID,
    CONF_APP_SECRET,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    OPT_SCAN_INTERVAL,
    OPT_WEBHOOK_ENABLED,
    PLATFORMS,
)
from .coordinator import ImouCoordinator, ImouHaConfigEntry

_LOGGER = logging.getLogger(__name__)


def _make_webhook_handler(entry: ImouHaConfigEntry):
    """Create a webhook handler bound to the given config entry."""

    async def _async_handle_webhook(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response | None:
        """Process an incoming Imou push event (HOOK-02)."""
        try:
            payload = await request.json()
        except ValueError:
            _LOGGER.debug("Imou webhook: non-JSON payload received")
            return web.Response(status=HTTPStatus.BAD_REQUEST)

        _LOGGER.debug("Imou webhook payload: %s", payload)

        # HOOK-04 / D-15: AppId validation (best-effort per Pitfall 6)
        received_app_id = payload.get("appId")
        if received_app_id and received_app_id != entry.data[CONF_APP_ID]:
            _LOGGER.warning(
                "Imou webhook: AppId mismatch (received=%s), rejecting",
                received_app_id,
            )
            return web.Response(status=HTTPStatus.UNAUTHORIZED)

        # HOOK-03 / D-16: Route to device by serial
        device_serial = payload.get("did")
        if not device_serial:
            _LOGGER.debug("Imou webhook: no device ID (did) in payload, ignoring")
            return None

        coordinator: ImouCoordinator = entry.runtime_data
        device = coordinator.data.get(device_serial)
        if device is None:
            _LOGGER.debug("Imou webhook: unknown device %s, ignoring", device_serial)
            return None

        # HOOK-02: Event type processing (D-05, D-06, D-07, D-08)
        msg_type = payload.get("msgType", "")
        if msg_type in ("videoMotion", "MobileDetect", "AlarmMD"):
            device.motion_detected = True
            coordinator.async_set_updated_data(coordinator.data)
        elif msg_type in ("human", "HeaderDetect", "AiHuman"):
            device.human_detected = True
            coordinator.async_set_updated_data(coordinator.data)
        elif msg_type == "deviceStatus":
            _LOGGER.debug(
                "Imou webhook: deviceStatus event for %s: %s", device_serial, payload
            )
        else:
            _LOGGER.debug(
                "Imou webhook: unrecognized msgType '%s' for %s",
                msg_type,
                device_serial,
            )

        return None

    return _async_handle_webhook


async def async_setup_entry(hass: HomeAssistant, entry: ImouHaConfigEntry) -> bool:
    """Set up Imou from a config entry."""
    app_id = entry.data[CONF_APP_ID]
    app_secret = entry.data[CONF_APP_SECRET]
    api_url = API_BASE_URLS[entry.data[CONF_API_URL]]
    scan_interval = entry.options.get(
        OPT_SCAN_INTERVAL,
        entry.data.get(OPT_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )

    client = ImouApiClient(app_id, app_secret, api_url)
    coordinator = ImouCoordinator(hass, client, scan_interval)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Webhook registration (HOOK-01, D-02, D-04, D-14)
    if entry.options.get(OPT_WEBHOOK_ENABLED, False):
        wh_id = entry.data.get(CONF_WEBHOOK_ID)
        if wh_id:
            try:
                webhook_url = webhook.async_generate_url(hass, wh_id)
            except NoURLAvailableError:
                _LOGGER.warning(
                    "Cannot register Imou webhook: HA external URL not configured"
                )
                webhook_url = None

            if webhook_url:
                webhook.async_register(
                    hass,
                    DOMAIN,
                    entry.title,
                    wh_id,
                    _make_webhook_handler(entry),
                    local_only=False,
                )
                try:
                    await coordinator.client.async_set_message_callback(
                        webhook_url, enable=True
                    )
                except ImouError as err:
                    _LOGGER.warning(
                        "Imou webhook registration failed, using polling only: %s", err
                    )
                    webhook.async_unregister(hass, wh_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ImouHaConfigEntry) -> bool:
    """Unload an Imou config entry."""
    # Deregister webhook (D-03)
    webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    if webhook_id:
        webhook.async_unregister(hass, webhook_id)
        if entry.options.get(OPT_WEBHOOK_ENABLED, False):
            try:
                await entry.runtime_data.client.async_set_message_callback(
                    "", enable=False
                )
            except ImouError:
                pass  # Best effort deregistration

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
