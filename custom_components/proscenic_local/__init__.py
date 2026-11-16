"""Proscenic Local — local control, area cleaning, and coverage map (no cloud)."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.service import async_extract_referenced_entity_ids

from .const import DOMAIN
from .coordinator import ProscenicCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["vacuum", "image", "sensor", "select", "button"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register integration-level services."""
    hass.services.async_register(DOMAIN, "clean_area", _clean_area)
    hass.services.async_register(DOMAIN, "add_area", _add_area)
    hass.services.async_register(DOMAIN, "remove_area", _remove_area)
    hass.services.async_register(DOMAIN, "reload_map", _reload_map)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one device."""
    coordinator = ProscenicCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await hass.async_add_executor_job(coordinator.start_monitor)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Tear down one device."""
    coordinator: ProscenicCoordinator = hass.data[DOMAIN][entry.entry_id]
    await hass.async_add_executor_job(coordinator.stop_monitor)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


def _coordinators(hass: HomeAssistant, call: ServiceCall) -> list[ProscenicCoordinator]:
    """Resolve the coordinators targeted by a service call."""
    entity_ids = async_extract_referenced_entity_ids(hass, call)
    registry = er.async_get(hass)
    coords: dict[str, ProscenicCoordinator] = {}
    for entity_id in entity_ids:
        reg_entry = registry.async_get(entity_id)
        if reg_entry and reg_entry.config_entry_id in hass.data.get(DOMAIN, {}):
            coord = hass.data[DOMAIN][reg_entry.config_entry_id]
            coords[coord.entry.entry_id] = coord
    if not coords:  # no explicit target -> all devices
        coords = {k: v for k, v in hass.data.get(DOMAIN, {}).items()}
    return list(coords.values())


async def _clean_area(hass: HomeAssistant, call: ServiceCall) -> None:
    for coord in _coordinators(hass, call):
        name = call.data.get("name") or coord.selected_area
        if not name:
            raise HomeAssistantError("No area name given and none selected")
        await coord.clean_area(name)


async def _add_area(hass: HomeAssistant, call: ServiceCall) -> None:
    for coord in _coordinators(hass, call):
        await coord.add_area(
            call.data["name"], call.data["x1"], call.data["y1"], call.data["x2"], call.data["y2"]
        )


async def _remove_area(hass: HomeAssistant, call: ServiceCall) -> None:
    for coord in _coordinators(hass, call):
        await coord.remove_area(call.data["name"])


async def _reload_map(hass: HomeAssistant, call: ServiceCall) -> None:
    for coord in _coordinators(hass, call):
        await coord.reload_map()
