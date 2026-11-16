"""Proscenic Local — local control, area cleaning, and coverage map (no cloud)."""
import logging
from functools import partial
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import ProscenicCoordinator

_LOGGER = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent / "frontend"

PLATFORMS = ["vacuum", "image", "sensor", "select", "button"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register integration-level services and the frontend module."""
    hass.services.async_register(DOMAIN, "clean_area", partial(_clean_area, hass))
    hass.services.async_register(DOMAIN, "add_area", partial(_add_area, hass))
    hass.services.async_register(DOMAIN, "remove_area", partial(_remove_area, hass))
    hass.services.async_register(DOMAIN, "reload_map", partial(_reload_map, hass))
    await hass.http.async_register_static_paths(
        [StaticPathConfig("/proscenic_local/frontend", str(FRONTEND_DIR), cache_headers=False)]
    )
    add_extra_js_url(hass, "/proscenic_local/frontend/proscenic-areas-card.js", es5=False)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one device."""
    coordinator = ProscenicCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await coordinator.async_load_map()
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
    target = getattr(call, "target", None) or {}
    if isinstance(target, dict):
        entity_ids = list(target.get("entity_id", []) or [])
    else:
        entity_ids = []
    if not entity_ids:
        entity_ids = list(call.data.get("entity_id", []) or [])
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
