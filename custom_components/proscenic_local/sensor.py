"""Sensors for Proscenic Local."""
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfArea
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CELL_RES_M, DOMAIN, DP_BATTERY
from .coordinator import ProscenicCoordinator
from .entity import ProscenicEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ProscenicCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            ProscenicCoveredAreaSensor(coordinator),
            ProscenicAreasSensor(coordinator),
            ProscenicBatterySensor(coordinator),
        ]
    )


class ProscenicBatterySensor(ProscenicEntity, SensorEntity):
    """Battery level in % (HA 2026.8 dropped battery from vacuum entities)."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ProscenicCoordinator) -> None:
        super().__init__(coordinator, "battery")

    @property
    def native_value(self) -> int | None:
        return self.coordinator.state_dps.get(DP_BATTERY)


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
