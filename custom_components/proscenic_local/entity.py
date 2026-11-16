"""Base entity for Proscenic Local."""
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ProscenicCoordinator


class ProscenicEntity(CoordinatorEntity):
    """Common base: holds the coordinator and device info."""

    def __init__(self, coordinator: ProscenicCoordinator, name: str) -> None:
        super().__init__(coordinator)
        self.coordinator: ProscenicCoordinator = coordinator
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.device_id}_{name}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_id)},
            "name": "Proscenic M8 Pro",
            "manufacturer": "Proscenic",
        }
