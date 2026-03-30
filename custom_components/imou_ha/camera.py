"""Camera platform for the Imou integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.entity_platform import AddEntitiesCallback

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .coordinator import ImouHaConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ImouHaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Imou camera entities from a config entry."""
    async_add_entities([])
