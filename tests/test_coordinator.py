"""Tests for ProscenicCoordinator: all device I/O must go through the Monitor's
single reactor thread (never a direct call on the shared tinytuya Device), so the
persistent socket is only ever touched by one thread.
"""
import asyncio
import threading

import pytest

from custom_components.proscenic_local import const, protocol
from custom_components.proscenic_local.coordinator import ProscenicCoordinator
from homeassistant.exceptions import HomeAssistantError


class FakeLoop:
    def __init__(self):
        self.soon = []

    def call_soon_threadsafe(self, fn, *args):
        self.soon.append((fn, args))


class FakeConfigEntries:
    def async_update_entry(self, entry, **kwargs):
        if "options" in kwargs:
            entry.options = kwargs["options"]


class FakeHass:
    def __init__(self):
        self.loop = FakeLoop()
        self.config_entries = FakeConfigEntries()

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class FakeEntry:
    def __init__(self):
        self.data = {
            "device_id": "id123",
            "host": "192.168.1.169",
            "local_key": "0123456789abcdef",
            "protocol_version": "3.3",
            "user_id": "",
        }
        self.options = {}


class FakeDevice:
    id = "id123"

    def __init__(self):
        self.direct = []  # records direct method calls (must stay empty)

    def set_multiple_values(self, *args, **kwargs):
        self.direct.append(("set_multiple_values", args, kwargs))
        return {}

    def set_value(self, *args, **kwargs):
        self.direct.append(("set_value", args, kwargs))
        return {}

    def status(self, *args, **kwargs):
        self.direct.append(("status", args, kwargs))
        return {"dps": {"3": "standby", "5": "standby"}}


class FakeMonitor:
    def __init__(self):
        self.calls = []

    def command(self, device, method, *args, **kwargs):
        self.calls.append((device, method, args, kwargs))


def make_coordinator():
    entry = FakeEntry()
    coord = ProscenicCoordinator(FakeHass(), entry)
    coord._device = FakeDevice()
    coord._monitor = FakeMonitor()
    return coord


def test_control_dispatches_via_monitor_not_direct_device():
    coord = make_coordinator()
    asyncio.run(coord.control("smart"))

    assert coord._device.direct == [], "control() must not call the device directly"
    assert len(coord._monitor.calls) == 1
    device, method, args, kwargs = coord._monitor.calls[0]
    assert device is coord._device
    assert method == "set_multiple_values"
    assert args == ({"3": "smart", "2": True},)


def test_control_standby_uses_switch_go_false():
    coord = make_coordinator()
    asyncio.run(coord.control("standby"))
    assert coord._monitor.calls[0][2] == ({"3": "standby", "2": False},)


def test_return_to_base_writes_mode_only_without_switch_go():
    coord = make_coordinator()
    asyncio.run(coord.return_to_base())
    assert [c[1:3] for c in coord._monitor.calls] == [("set_value", (3, "chargego"))]


def test_pause_and_fan_speed_also_route_through_monitor():
    coord = make_coordinator()
    asyncio.run(coord.pause())
    asyncio.run(coord.set_fan_speed("strong"))

    assert coord._device.direct == []
    methods = [c[1] for c in coord._monitor.calls]
    assert methods == ["set_value", "set_value"]
    assert coord._monitor.calls[0][2] == (2, False)     # DP_SWITCH_GO = pause
    assert coord._monitor.calls[1][2] == (14, "strong")  # DP_SUCTION


def test_update_data_returns_cache_and_queues_status():
    coord = make_coordinator()
    with coord._dps_lock:
        coord._dps_cache.update({"3": "smart", "5": "smart_clean"})

    data = asyncio.run(coord._async_update_data())

    assert data == {"3": "smart", "5": "smart_clean"}
    # a status query was queued through the monitor
    assert "status" in [c[1] for c in coord._monitor.calls]


def test_on_status_updates_cache_and_schedules_ha_push():
    coord = make_coordinator()
    coord._on_status(coord._device, {"dps": {"3": "smart", "5": "smart_clean"}})

    with coord._dps_lock:
        assert coord._dps_cache[3] == "smart"  # string keys normalized to int
        assert coord._dps_cache[5] == "smart_clean"
    # a thread-safe push to the HA loop was scheduled
    assert len(coord.hass.loop.soon) == 1


def test_normalize_dps_converts_string_keys_to_int():
    coord = make_coordinator()
    assert coord._normalize_dps({"3": "standby", "102": "x", "t": 123}) == {
        3: "standby",
        102: "x",
        "t": 123,
    }


def test_on_status_parses_dp102_string_key_and_accumulates():
    coord = make_coordinator()
    raw = protocol.encode_raw({"infoType": 20001, "data": {"pos": [500, 500]}})
    # tinytuya delivers DP keys as strings — this is the real-world shape
    coord._on_status(coord._device, {"dps": {"102": raw}})
    with coord._lock:
        assert (10, 10) in coord._grid


def test_handle_raw_position_adds_coverage_cell():
    coord = make_coordinator()
    # live position streamed by this device (infoType 20001), base64 JSON
    raw = protocol.encode_raw({"infoType": 20001, "data": {"pos": [500, 500], "phi": 0}})
    coord._handle_raw(raw)
    with coord._lock:
        assert (10, 10) in coord._grid  # 500 mm = 0.5 m = 10 cells @ 5 cm


def test_handle_raw_position_draws_line_between_points():
    coord = make_coordinator()
    coord._handle_raw(protocol.encode_raw({"infoType": 20001, "data": {"pos": [100, 0]}}))
    coord._handle_raw(protocol.encode_raw({"infoType": 20001, "data": {"pos": [300, 0]}}))
    with coord._lock:
        for c in range(2, 7):  # 100..300 mm = cols 2..6 (4 cells)
            assert (c, 0) in coord._grid


def test_handle_raw_position_no_line_across_large_jump():
    coord = make_coordinator()
    coord._handle_raw(protocol.encode_raw({"infoType": 20001, "data": {"pos": [100, 0]}}))
    coord._handle_raw(protocol.encode_raw({"infoType": 20001, "data": {"pos": [100000, 0]}}))
    with coord._lock:
        assert (2, 0) in coord._grid      # 100 mm = col 2
        assert (2000, 0) in coord._grid   # 100 m = 2000 cells
        assert (1000, 0) not in coord._grid  # no line across the jump


def test_handle_raw_position_ignores_origin_sentinel():
    coord = make_coordinator()
    coord._handle_raw(protocol.encode_raw({"infoType": 20001, "data": {"pos": [500, 500]}}))
    coord._handle_raw(protocol.encode_raw({"infoType": 20001, "data": {"pos": [0, 0]}}))
    coord._handle_raw(protocol.encode_raw({"infoType": 20001, "data": {"pos": [600, 500]}}))
    with coord._lock:
        # the transient (0,0) sample neither moves the position nor adds the origin
        assert coord._position == (600, 500)
        assert (0, 0) not in coord._grid
        assert (10, 10) in coord._grid   # 500 mm -> col/row 10
        assert (12, 10) in coord._grid   # 600 mm -> col 12


def test_handle_raw_path_accumulates_cells():
    coord = make_coordinator()
    raw = protocol.encode_raw(
        {"infoType": 21011, "data": {"pathID": 1, "posArray": [[0, 0], [1000, 0]]}}
    )
    coord._handle_raw(raw)
    with coord._lock:
        assert (0, 0) in coord._grid
        assert (20, 0) in coord._grid  # 1000 mm = 1 m = 20 cells


def test_render_map_produces_png_after_positions():
    coord = make_coordinator()
    for x in range(6):
        coord._handle_raw(
            protocol.encode_raw({"infoType": 20001, "data": {"pos": [x * 100, 0]}})
        )
    png = coord.render_map()
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic


def test_render_map_bounds_none_before_any_path():
    coord = make_coordinator()
    assert coord.map_bounds is None


def test_render_map_exposes_map_bounds():
    coord = make_coordinator()
    for x, y in [(1000, 2000), (3000, 4000)]:
        coord._handle_raw(
            protocol.encode_raw({"infoType": 20001, "data": {"pos": [x, y]}})
        )
    coord.render_map()
    b = coord.map_bounds
    assert b is not None
    assert (b["min_x"], b["max_x"]) == (1000, 3000)
    assert (b["min_y"], b["max_y"]) == (2000, 4000)
    assert b["scale"] == const.RENDER_SCALE_PX_PER_MM
    assert b["margin"] == const.RENDER_MARGIN_PX


def test_map_bounds_is_live_without_render():
    coord = make_coordinator()
    for x, y in [(1000, 2000), (3000, 4000)]:
        coord._handle_raw(
            protocol.encode_raw({"infoType": 20001, "data": {"pos": [x, y]}})
        )
    # bounds are available from the path snapshot without any render_map() call
    b = coord.map_bounds
    assert b is not None
    assert (b["min_x"], b["max_x"]) == (1000, 3000)
    assert (b["min_y"], b["max_y"]) == (2000, 4000)


def test_add_area_normalizes_coordinates():
    coord = make_coordinator()
    asyncio.run(coord.add_area("kitchen", 2000, 1000, 1000, 2000))
    a = coord.areas()[0]
    assert a["name"] == "kitchen"
    assert a["vertexs"] == [[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]


def test_add_area_rounds_float_coordinates():
    coord = make_coordinator()
    asyncio.run(coord.add_area("hall", -1234.6, 10.4, 99.5, -0.2))
    v = coord.areas()[0]["vertexs"]
    assert v == [[-1235, 0], [100, 0], [100, 10], [-1235, 10]]
    assert all(type(c) is int for p in v for c in p)


def test_add_area_rejects_duplicate_name():
    coord = make_coordinator()
    asyncio.run(coord.add_area("kitchen", 0, 0, 1000, 1000))
    with pytest.raises(HomeAssistantError):
        asyncio.run(coord.add_area("kitchen", 2000, 2000, 3000, 3000))
