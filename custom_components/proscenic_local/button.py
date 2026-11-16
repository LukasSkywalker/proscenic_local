"""Button entities for Proscenic Local."""
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MODE_WALL_FOLLOW
from .coordinator import ProscenicCoordinator
from .entity import ProscenicEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ProscenicCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [ProscenicCleanAreaButton(coordinator), ProscenicMapWallsButton(coordinator)]
    )


class ProscenicCleanAreaButton(ProscenicEntity, ButtonEntity):
    """Press to clean the area selected by the area select entity."""

    def __init__(self, coordinator: ProscenicCoordinator) -> None:
        super().__init__(coordinator, "clean_area")

    async def async_press(self) -> None:
        name = self.coordinator.selected_area
        if not name:
            raise HomeAssistantError("Select an area first (select.<device>_area)")
        await self.coordinator.clean_area(name)


class ProscenicMapWallsButton(ProscenicEntity, ButtonEntity):
    """Press to drive along the walls so the map picks up the room outline."""

    def __init__(self, coordinator: ProscenicCoordinator) -> None:
        super().__init__(coordinator, "map_walls")

    async def async_press(self) -> None:
        await self.coordinator.control(MODE_WALL_FOLLOW)
