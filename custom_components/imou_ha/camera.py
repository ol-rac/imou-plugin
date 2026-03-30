"""Camera platform for the Imou integration (STRM-01, STRM-02)."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.components.camera import Camera, CameraEntityFeature

from .const import STREAM_URL_CACHE_TTL
from .entity import ImouEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ImouCoordinator, ImouHaConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: ImouHaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Imou camera entities from a config entry (D-06: all devices get camera)."""
    coordinator: ImouCoordinator = entry.runtime_data
    async_add_entities([ImouCamera(coordinator, serial) for serial in coordinator.data])


class ImouCamera(ImouEntity, Camera):
    """Imou camera entity providing HLS live stream (STRM-01, STRM-02).

    HD stream is the default stream_source (D-04).
    SD stream URL exposed as extra_state_attribute sd_stream_url (D-05).
    Stream URL cached with TTL to conserve API calls (D-02).
    """

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_has_entity_name = True
    _attr_translation_key = "camera"

    def __init__(self, coordinator: ImouCoordinator, device_serial: str) -> None:
        """Initialise camera entity. Calls both parent __init__ methods (MRO fix)."""
        ImouEntity.__init__(self, coordinator, device_serial, "camera")
        Camera.__init__(self)
        self._stream_url_cache: dict[str, tuple[str, float]] = {}

    async def stream_source(self) -> str | None:
        """Return HLS stream URL, fetching fresh if cache expired (D-01, D-02)."""
        cached = self._stream_url_cache.get("hd")
        if cached and (time.monotonic() - cached[1]) < STREAM_URL_CACHE_TTL:
            return cached[0]
        try:
            hd_url, sd_url = await self.coordinator.client.async_get_stream_url(
                self._device_serial,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Failed to get stream URL for %s", self._device_serial)
            return None
        now = time.monotonic()
        if hd_url:
            self._stream_url_cache["hd"] = (hd_url, now)
        if sd_url:
            self._stream_url_cache["sd"] = (sd_url, now)
        return hd_url

    async def async_camera_image(
        self,
        width: int | None = None,  # noqa: ARG002
        height: int | None = None,  # noqa: ARG002
    ) -> bytes | None:
        """Return None -- Imou does not provide MJPEG snapshots via pyimouapi."""
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes including sd_stream_url (D-05, STRM-02)."""
        attrs = super().extra_state_attributes
        cached_sd = self._stream_url_cache.get("sd")
        attrs["sd_stream_url"] = cached_sd[0] if cached_sd else None
        return attrs
