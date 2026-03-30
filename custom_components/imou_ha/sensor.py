"""Sensor platform for Imou integration (stub — full implementation in Phase 3 Plan 02)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ImouHaConfigEntry

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ImouHaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Imou sensor entities from a config entry (stub — Plan 02 adds entities)."""
    # Plan 02 will add ImouDeviceStateSensor and ImouBatterySensor here.
