"""Switch platform for the Imou integration (placeholder for Plan 02-02)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ImouHaConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: ImouHaConfigEntry,  # noqa: ARG001
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Imou switch entities from a config entry (implemented in Plan 02-02)."""
    # Privacy mode switch entity implemented in Plan 02-02.
    async_add_entities([])
