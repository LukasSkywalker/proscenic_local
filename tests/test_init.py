"""Smoke tests for integration setup: service + frontend module registration."""
import asyncio

from homeassistant.components.http import StaticPathConfig

import custom_components.proscenic_local as mod


class FakeServices:
    def __init__(self):
        self.registered = []

    def async_register(self, domain, name, handler):
        self.registered.append((domain, name))


class FakeHttp:
    def __init__(self):
        self.paths = []

    async def async_register_static_paths(self, configs):
        self.paths.extend(configs)


class FakeHass:
    def __init__(self):
        self.services = FakeServices()
        self.http = FakeHttp()


def test_async_setup_registers_services_and_static_path():
    hass = FakeHass()
    result = asyncio.run(mod.async_setup(hass, {}))

    assert result is True
    # all four integration services are registered
    names = {name for _, name in hass.services.registered}
    assert names == {"clean_area", "add_area", "remove_area", "reload_map"}
    # the card module is served with caching disabled (frontend static path)
    assert len(hass.http.paths) == 1
    cfg = hass.http.paths[0]
    assert isinstance(cfg, StaticPathConfig)
    assert cfg.url_path == "/proscenic_local/frontend"
    assert cfg.cache_headers is False
