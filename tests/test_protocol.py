"""Tests for custom_components.proscenic_local.protocol — DP-102 envelope + path/grid helpers."""
import base64
import json

import pytest

from custom_components.proscenic_local import protocol


AREA = {
    "active": "normal", "appModel": "room", "id": 101, "mode": "default",
    "name": "gang", "tag": "101",
    "vertexs": [[-1638, 1028], [1199, 1028], [1199, -1472], [-1638, -1472]],
    "wall": False,
}


def test_build_envelope_shape():
    env = protocol.build_envelope([{"infoType": 21004}], [21004], "u", 123)
    assert env["infoType"] == 30000
    assert env["dInfo"] == {"ts": 123, "userId": "u"}
    assert env["data"]["cmds"] == [{"infoType": 21004}]
    assert env["data"]["fastCmds"] == [21004]


def test_encode_decode_raw_round_trip():
    payload = {"infoType": 21004, "data": {"value": [{"id": 1}]}}
    assert protocol.decode_raw(protocol.encode_raw(payload)) == payload


def test_clean_area_cmd_has_three_commands_in_order():
    cmd = protocol.build_clean_area_cmd(AREA, map_id=5, user_id="u", ts_ms=1)
    types = [c["infoType"] for c in cmd["data"]["cmds"]]
    assert types == [21003, 21023, 21005]
    assert cmd["data"]["fastCmds"] == [21003, 21023, 21005]
    # 21003 carries the area polygon; 21023 carries cleanId + mapId
    assert cmd["data"]["cmds"][0]["data"]["value"] == [AREA]
    assert cmd["data"]["cmds"][1]["data"]["cleanId"] == [-2]
    assert cmd["data"]["cmds"][1]["data"]["mapId"] == 5


def test_area_read_cmd_requests_empty_list():
    cmd = protocol.build_area_read_cmd(user_id="u", ts_ms=1)
    assert cmd["data"]["fastCmds"] == [21004]
    assert cmd["data"]["cmds"][0]["data"]["value"] == []


def test_parse_area_list_extracts_value():
    resp = {
        "infoType": 30000,
        "data": {"cmds": [{"infoType": 21004, "data": {"value": [AREA]}}]},
    }
    assert protocol.parse_area_list(resp) == [AREA]


def test_parse_area_list_empty_when_no_21004():
    assert protocol.parse_area_list({"data": {"cmds": []}}) == []


def test_parse_path_points():
    resp = {"infoType": 21011, "data": {"pathID": 99, "posArray": [[0, 3], [133, -3]]}}
    pid, points = protocol.parse_path_points(resp)
    assert pid == 99
    assert points == [(0, 3), (133, -3)]


def test_parse_position():
    resp = {"infoType": 20001, "data": {"pos": [131, -47], "phi": 833}}
    assert protocol.parse_position(resp) == (131, -47)


def test_mm_to_cell_at_origin():
    assert protocol.mm_to_cell(0, 0, 0.0, 0.0, 0.05) == (0, 0)


def test_mm_to_cell_scales_and_floors():
    # 500 mm = 0.5 m = 10 cells at 5 cm
    assert protocol.mm_to_cell(500, 500, 0.0, 0.0, 0.05) == (10, 10)
    assert protocol.mm_to_cell(-500, -500, 0.0, 0.0, 0.05) == (-10, -10)


def test_accumulate_path_marks_cells_and_dedups():
    grid = set()
    seen = set()
    pts = [(0, 0), (500, 0)]
    protocol.accumulate_path(grid, 7, pts, 0.0, 0.0, 0.05, seen)
    assert (0, 0) in grid
    assert (10, 0) in grid
    # re-accumulating the same path id + points is a no-op
    before = len(grid)
    protocol.accumulate_path(grid, 7, pts, 0.0, 0.0, 0.05, seen)
    assert len(grid) == before


def test_distance_mm():
    assert protocol.distance_mm((0, 0), (300, 400)) == 500  # 3-4-5 triangle


def test_line_cells_horizontal():
    assert protocol.line_cells((0, 0), (3, 0)) == [(0, 0), (1, 0), (2, 0), (3, 0)]


def test_line_cells_diagonal():
    assert protocol.line_cells((0, 0), (2, 2)) == [(0, 0), (1, 1), (2, 2)]


def test_line_cells_single_point():
    assert protocol.line_cells((5, 5), (5, 5)) == [(5, 5)]


def test_smooth_path_returns_input_when_short():
    assert protocol.smooth_path([(0, 0)]) == [(0, 0)]
    assert protocol.smooth_path([(0, 0), (10, 0)]) == [(0, 0), (10, 0)]


def test_smooth_path_interpolates_more_points_and_keeps_endpoints():
    pts = [(0, 0), (10, 10), (20, 0)]
    out = protocol.smooth_path(pts, samples_per_segment=4)
    assert len(out) > len(pts)
    assert out[0] == (0, 0)
    assert out[-1] == (20, 0)
