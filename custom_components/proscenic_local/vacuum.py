"""Vacuum control entity for Proscenic Local."""
from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumEntityFeature,
)
from homeassistant.components.vacuum.const import VacuumActivity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    DP_STATUS,
    DP_SUCTION,
    FAN_GENTLE,
    FAN_NORMAL,
    FAN_STRONG,
    MODE_SMART,
    MODE_SPIRAL,
    MODE_STANDBY,
    STATUS_CHARGED,
    STATUS_CHARGING,
    STATUS_CLEANING,
    STATUS_MOP_CLEAN,
    STATUS_PAUSED,
    STATUS_RETURNING,
    STATUS_SMART_CLEAN,
    STATUS_SPOT_CLEAN,
    STATUS_STANDBY,
)
from .coordinator import ProscenicCoordinator
from .entity import ProscenicEntity

_FAN_MAP = {FAN_STRONG: "High", FAN_NORMAL: "Medium", FAN_GENTLE: "Low"}
_FAN_REV = {v: k for k, v in _FAN_MAP.items()}

_CLEANING = {
    STATUS_SMART_CLEAN, STATUS_SPOT_CLEAN, STATUS_MOP_CLEAN, STATUS_CLEANING,
}
_DOCKED = {STATUS_CHARGING, STATUS_CHARGED}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ProscenicCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ProscenicVacuum(coordinator)])


class ProscenicVacuum(ProscenicEntity, StateVacuumEntity):
    """The robot vacuum, controlled over the local protocol."""

    _attr_supported_features = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.CLEAN_SPOT
        | VacuumEntityFeature.FAN_SPEED
        | VacuumEntityFeature.STATE
        | VacuumEntityFeature.STATUS
    )

    def __init__(self, coordinator: ProscenicCoordinator) -> None:
        super().__init__(coordinator, "vacuum")
        self._attr_translation_key = "vacuum"

    @property
    def activity(self) -> VacuumActivity:
        status = self.coordinator.state_dps.get(DP_STATUS)
        if status in _CLEANING:
            return VacuumActivity.CLEANING
        if status == STATUS_PAUSED:
            return VacuumActivity.PAUSED
        if status == STATUS_RETURNING:
            return VacuumActivity.RETURNING
        if status in _DOCKED:
            return VacuumActivity.DOCKED
        return VacuumActivity.IDLE

    @property
    def fan_speed(self) -> str | None:
        return _FAN_MAP.get(self.coordinator.state_dps.get(DP_SUCTION))

    @property
    def fan_speed_list(self) -> list[str]:
        return list(_FAN_MAP.values())

    async def async_start(self) -> None:
        await self.coordinator.control(MODE_SMART)

    async def async_stop(self) -> None:
        await self.coordinator.control(MODE_STANDBY)

    async def async_pause(self) -> None:
        await self.coordinator.pause()

    async def async_return_to_base(self) -> None:
        await self.coordinator.return_to_base()

    async def async_clean_spot(self) -> None:
        await self.coordinator.control(MODE_SPIRAL)

    async def async_set_fan_speed(self, fan_speed: str) -> None:
        if fan_speed in _FAN_REV:
            await self.coordinator.set_fan_speed(_FAN_REV[fan_speed])
