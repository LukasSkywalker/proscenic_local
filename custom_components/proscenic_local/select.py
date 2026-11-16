"""Area picker (select) entity for Proscenic Local."""
from homeassistant.components.select import SelectEntity
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
    async_add_entities([ProscenicAreaSelect(coordinator)])


class ProscenicAreaSelect(ProscenicEntity, SelectEntity):
    """Select which area to clean (picked up by the clean_area button)."""

    _attr_current_option = None

    def __init__(self, coordinator: ProscenicCoordinator) -> None:
        super().__init__(coordinator, "area")

    @property
    def options(self) -> list[str]:
        return [a["name"] for a in self.coordinator.areas()]

    async def async_select_option(self, option: str) -> None:
        self.coordinator.selected_area = option
        self._attr_current_option = option
        self.async_write_ha_state()
