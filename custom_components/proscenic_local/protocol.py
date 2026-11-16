"""Pure protocol helpers for the Proscenic M8 Pro (Tuya "sd" family).

DP 102 (`rawData`) carries base64-encoded JSON with an `infoType`. Commands are
`30000` envelopes. See docs/dp_reference.md for the full protocol.
"""
import base64
import json
import math

INFO_TYPE = 30000
INFO_POSITION = 20001   # live position (pos/phi)
INFO_PATH = 21011       # cleaning path (posArray)
CMD_SET_AREA = 21003       # areas to clean (value = polygon list)
CMD_AREA_LIST = 21004      # area list read
CMD_START = 21005          # start job (mode=reAppointClean)
CMD_CLEAN = 21023          # clean command (cleanId)


def build_envelope(cmds, fastcmds, user_id="", ts_ms=0):
    """Build a DP-102 30000 command envelope."""
    return {
        "infoType": INFO_TYPE,
        "dInfo": {"ts": ts_ms, "userId": user_id},
        "data": {"cmds": cmds, "fastCmds": fastcmds},
    }


def encode_raw(payload):
    """base64-encode a JSON payload for writing to DP 102."""
    return base64.b64encode(json.dumps(payload).encode()).decode()


def decode_raw(value):
    """base64-decode a DP 102 value into a dict."""
    return json.loads(base64.b64decode(value).decode())


def build_clean_area_cmd(area, map_id, user_id="", ts_ms=0):
    """Build the 21003 + 21023 + 21005 clean-area command."""
    cmds = [
        {"infoType": CMD_SET_AREA, "data": {"value": [area]}},
        {"infoType": CMD_CLEAN, "data": {"cleanId": [-2], "mapId": map_id}},
        {"infoType": CMD_START, "data": {"mode": "reAppointClean"}},
    ]
    return build_envelope(cmds, [CMD_SET_AREA, CMD_CLEAN, CMD_START], user_id, ts_ms)


def build_area_read_cmd(user_id="", ts_ms=0):
    """Build the 21004 area-list request."""
    cmds = [
        {"infoType": CMD_AREA_LIST, "data": {"autoAreaValue": [], "mapId": -1, "value": []}}
    ]
    return build_envelope(cmds, [CMD_AREA_LIST], user_id, ts_ms)


def build_area_write_cmd(areas, user_id="", ts_ms=0):
    """Build the 21003 area-list write (persist the full list)."""
    cmds = [{"infoType": CMD_SET_AREA, "data": {"value": areas}}]
    return build_envelope(cmds, [CMD_SET_AREA], user_id, ts_ms)


def parse_area_list(response):
    """Extract the area list from a 21004 response envelope."""
    for cmd in response.get("data", {}).get("cmds", []):
        if cmd.get("infoType") == CMD_AREA_LIST:
            return cmd.get("data", {}).get("value", [])
    return []


def parse_path_points(response):
    """Return (pathID, [(x_mm, y_mm), ...]) from a 21011 path message."""
    data = response.get("data", {})
    return data.get("pathID"), [tuple(p) for p in data.get("posArray", [])]


def parse_position(response):
    """Return (x_mm, y_mm) from a 20001 position message."""
    pos = response.get("data", {}).get("pos", [0, 0])
    return tuple(pos)


def mm_to_cell(x_mm, y_mm, x_min_m, y_min_m, res_m):
    """Convert mm map coordinates to grid cell (col, row), floored."""
    col = math.floor((x_mm / 1000.0 - x_min_m) / res_m)
    row = math.floor((y_mm / 1000.0 - y_min_m) / res_m)
    return col, row


def accumulate_path(grid, path_id, points, x_min_m, y_min_m, res_m, seen):
    """Mark path points into a coverage grid, deduping by (path_id, index)."""
    for i, (x, y) in enumerate(points):
        key = (path_id, i)
        if key in seen:
            continue
        seen.add(key)
        grid.add(mm_to_cell(x, y, x_min_m, y_min_m, res_m))
