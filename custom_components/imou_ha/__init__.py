"""Imou integration for Home Assistant."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .api_client import ImouApiClient
from .budget import BUDGET_STORAGE_KEY, ImouBudgetState

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
from .const import (
    API_BASE_URLS,
    CONF_API_URL,
    CONF_APP_ID,
    CONF_APP_SECRET,
    DEFAULT_SCAN_INTERVAL,
    OPT_SCAN_INTERVAL,
    PLATFORMS,
)
from .coordinator import ImouCoordinator, ImouHaConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ImouHaConfigEntry) -> bool:
    """Set up Imou from a config entry."""
    app_id = entry.data[CONF_APP_ID]
    app_secret = entry.data[CONF_APP_SECRET]
    api_url = API_BASE_URLS[entry.data[CONF_API_URL]]
    scan_interval = entry.options.get(
        OPT_SCAN_INTERVAL,
        entry.data.get(OPT_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )

    # Construct ONE shared budget state instance — passed to both client and coordinator
    stored_budget = entry.data.get(BUDGET_STORAGE_KEY, {})
    budget_state = ImouBudgetState.from_dict(stored_budget)

    client = ImouApiClient(app_id, app_secret, api_url, budget_state=budget_state)
    coordinator = ImouCoordinator(hass, client, entry, budget_state, scan_interval)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ImouHaConfigEntry) -> bool:
    """Unload an Imou config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
