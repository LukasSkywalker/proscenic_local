"""Stub homeassistant modules so protocol unit tests run without a full HA install."""
import sys
import types
from dataclasses import dataclass


def _mkmod(name):
    mod = types.ModuleType(name)
    mod.__path__ = []
    sys.modules[name] = mod
    return mod


ha = _mkmod("homeassistant")
ha.core = _mkmod("homeassistant.core")
ha.config_entries = _mkmod("homeassistant.config_entries")
ha.exceptions = _mkmod("homeassistant.exceptions")
ha.helpers = _mkmod("homeassistant.helpers")
ha.helpers.entity_registry = _mkmod("homeassistant.helpers.entity_registry")
ha.helpers.service = _mkmod("homeassistant.helpers.service")
ha.helpers.update_coordinator = _mkmod("homeassistant.helpers.update_coordinator")
ha.components = _mkmod("homeassistant.components")
ha.components.frontend = _mkmod("homeassistant.components.frontend")
ha.components.http = _mkmod("homeassistant.components.http")

ha.core.HomeAssistant = object
ha.core.ServiceCall = object
ha.config_entries.ConfigEntry = object
ha.exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
ha.helpers.service.async_extract_referenced_entity_ids = lambda *a, **k: []
ha.components.frontend.add_extra_js_url = lambda hass, url, es5=False: None


@dataclass
class StaticPathConfig:
    url_path: str
    path: str
    cache_headers: bool = True


ha.components.http.StaticPathConfig = StaticPathConfig


class DataUpdateCoordinator:
    """Minimal stand-in for the HA coordinator base used by unit tests."""

    def __init__(self, hass, logger, name=None, update_interval=None):
        self.hass = hass
        self.logger = logger
        self.data = None
        self.last_update_success = True

    def async_set_updated_data(self, data):
        self.data = data


ha.helpers.update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
