"""Coverage map image entity for Proscenic Local."""
import collections
from datetime import datetime, timezone

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ProscenicCoordinator
from .entity import ProscenicEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ProscenicCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ProscenicMapImage(coordinator)])


class ProscenicMapImage(ProscenicEntity, ImageEntity):
    """The coverage map, rendered from the accumulated path."""

    _attr_content_type = "image/png"

    def __init__(self, coordinator: ProscenicCoordinator) -> None:
        super().__init__(coordinator, "coverage_map")
        # ImageEntity.__init__ requires `hass` (set only after the entity is added),
        # so its `access_tokens` deque is not initialised by the MRO chain. Do it here.
        self.access_tokens: collections.deque = collections.deque(maxlen=2)
        self.access_tokens.append("local")

    async def async_image(self) -> bytes | None:
        """Return the rendered coverage map (or None before any path)."""
        return await self.hass.async_add_executor_job(self.coordinator.render_map)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Rotate the access token + timestamp so the frontend re-fetches the map."""
        self.async_update_token()
        self._attr_image_last_updated = datetime.now(timezone.utc)
        super()._handle_coordinator_update()
