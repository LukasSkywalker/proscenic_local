"""Coverage map image entity for Proscenic Local."""
from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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

    async def async_image(self) -> bytes | None:
        """Return the rendered coverage map (or None before any path)."""
        return await self.hass.async_add_executor_job(self.coordinator.render_map)
