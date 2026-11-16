"""Sensors for Proscenic Local."""
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfArea
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CELL_RES_M, DOMAIN
from .coordinator import ProscenicCoordinator
from .entity import ProscenicEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ProscenicCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [ProscenicCoveredAreaSensor(coordinator), ProscenicAreasSensor(coordinator)]
    )


class ProscenicCoveredAreaSensor(ProscenicEntity, SensorEntity):
    """Total area covered, in m²."""

    _attr_native_unit_of_measurement = UnitOfArea.SQUARE_METERS
    _attr_device_class = SensorDeviceClass.AREA

    def __init__(self, coordinator: ProscenicCoordinator) -> None:
        super().__init__(coordinator, "covered_area")

    @property
    def native_value(self) -> float:
        return round(self.coordinator.covered_cells * CELL_RES_M * CELL_RES_M, 2)


class ProscenicAreasSensor(ProscenicEntity, SensorEntity):
    """Number of defined areas."""

    def __init__(self, coordinator: ProscenicCoordinator) -> None:
        super().__init__(coordinator, "areas")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.areas())
