"""Config flow for the Imou integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.webhook import async_generate_id
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api_client import ImouApiClient
from .const import (
    API_BASE_URLS,
    CONF_API_URL,
    CONF_APP_ID,
    CONF_APP_SECRET,
    DEFAULT_API_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    OPT_SCAN_INTERVAL,
    OPT_WEBHOOK_ENABLED,
    REGIONAL_ENDPOINTS,
)
from .exceptions import ImouAuthError, ImouError, ImouLicenseError

_LOGGER = logging.getLogger(__name__)

_REGION_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[
            SelectOptionDict(value=key, label=label)
            for key, label in REGIONAL_ENDPOINTS.items()
        ],
        mode=SelectSelectorMode.DROPDOWN,
    ),
)

_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_APP_ID): str,
        vol.Required(CONF_APP_SECRET): str,
        vol.Required(CONF_API_URL, default=DEFAULT_API_URL): _REGION_SELECTOR,
    },
)


class ImouConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Imou integration.

    Two-step flow (per D-01):
      Step 1 (user): Enter AppId, AppSecret, Region — validates credentials.
      Step 2 (confirm): Show discovered camera count/names — create entry.
    """

    VERSION = 1

    def __init__(self) -> None:
        """Initialise config flow state."""
        self._credentials: dict[str, Any] = {}
        self._discovered_devices: list[dict[str, str]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle step 1: credential entry and validation (per D-01, D-02)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Prevent duplicate entries by AppId (per D-09)
            await self.async_set_unique_id(user_input[CONF_APP_ID])
            self._abort_if_unique_id_configured()

            try:
                client = ImouApiClient(
                    user_input[CONF_APP_ID],
                    user_input[CONF_APP_SECRET],
                    API_BASE_URLS[user_input[CONF_API_URL]],
                )
                await client.async_validate_credentials()
                await self._async_discover_devices(client)
            except ImouAuthError:
                errors["base"] = "invalid_auth"  # per D-02 — inline error, same step
            except ImouLicenseError:
                errors["base"] = "license_limit"  # per D-10/INFR-04
            except ImouError:
                errors["base"] = "cannot_connect"  # per D-10
            except Exception:
                _LOGGER.exception("Unexpected error during config flow step user")
                errors["base"] = "unknown"  # per D-11
            else:
                # Credentials valid — store and advance to confirm step
                self._credentials = {
                    CONF_APP_ID: user_input[CONF_APP_ID],
                    CONF_APP_SECRET: user_input[CONF_APP_SECRET],
                    CONF_API_URL: user_input[CONF_API_URL],
                }
                return await self.async_step_confirm()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _USER_SCHEMA,
                user_input or {},
            ),
            errors=errors,
        )

    async def _async_discover_devices(self, client: ImouApiClient) -> None:
        """Discover devices between steps (per D-03)."""
        devices = await client.async_get_devices()
        self._discovered_devices = [
            {"name": d.name, "serial": d.serial} for d in devices.values()
        ]
        _LOGGER.debug(
            "Discovered %d devices during setup", len(self._discovered_devices),
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle step 2: confirm discovered cameras (per D-01, D-03)."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"Imou ({len(self._discovered_devices)} cameras)",
                data=self._credentials,
            )

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "camera_count": str(len(self._discovered_devices)),
                "camera_names": ", ".join(
                    d["name"] for d in self._discovered_devices
                ),
            },
        )

    @staticmethod
    def async_get_options_flow(_config_entry: Any) -> ImouOptionsFlow:
        """Return the options flow handler."""
        return ImouOptionsFlow()


class ImouOptionsFlow(OptionsFlow):
    """Options flow for the Imou integration.

    Allows reconfiguration of credentials, region, and polling interval.
    Saves options and schedules a full integration reload on completion (per D-07).
    Note: OptionsFlowWithReload was added in HA 2025.4+. For HA 2025.1 we
    schedule the reload explicitly after async_create_entry.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle options form (per D-06, D-07, D-08)."""
        if user_input is not None:
            # Generate and persist webhook_id on first enable (D-04)
            if user_input.get(OPT_WEBHOOK_ENABLED, False):
                new_data = dict(self.config_entry.data)
                if CONF_WEBHOOK_ID not in new_data:
                    new_data[CONF_WEBHOOK_ID] = async_generate_id()
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data=new_data
                    )
            # Schedule reload so the new options take effect immediately (per D-07)
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
            return self.async_create_entry(data=user_input)

        options_schema = vol.Schema(
            {
                vol.Required(CONF_APP_ID): str,
                vol.Required(CONF_APP_SECRET): str,
                vol.Required(CONF_API_URL, default=DEFAULT_API_URL): _REGION_SELECTOR,
                vol.Required(
                    OPT_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL,
                ): vol.All(int, vol.Range(min=MIN_SCAN_INTERVAL)),
                vol.Optional(OPT_WEBHOOK_ENABLED, default=False): BooleanSelector(),
            },
        )

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                options_schema,
                self.config_entry.options or self.config_entry.data,
            ),
        )
