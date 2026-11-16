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
    """Convert mm map coordinates to grid cell (col, row), floored.

    Uses integer arithmetic (cell size in mm) so exact boundaries don't get
    turned into 5.999… by float rounding (e.g. 300 mm / 0.05 m = 6 cells).
    """
    cell_mm = round(res_m * 1000.0)
    col = (round(x_mm) - round(x_min_m * 1000.0)) // cell_mm
    row = (round(y_mm) - round(y_min_m * 1000.0)) // cell_mm
    return col, row


def distance_mm(pos_a, pos_b):
    """Euclidean distance (mm) between two (x_mm, y_mm) points."""
    return math.hypot(pos_a[0] - pos_b[0], pos_a[1] - pos_b[1])


def line_cells(cell_a, cell_b):
    """Return every grid cell on the line between two cells (Bresenham)."""
    x0, y0 = cell_a
    x1, y1 = cell_b
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    cells = []
    x, y = x0, y0
    while True:
        cells.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy
    return cells


def accumulate_path(grid, path_id, points, x_min_m, y_min_m, res_m, seen):
    """Mark path points into a coverage grid, deduping by (path_id, index)."""
    for i, (x, y) in enumerate(points):
        key = (path_id, i)
        if key in seen:
            continue
        seen.add(key)
        grid.add(mm_to_cell(x, y, x_min_m, y_min_m, res_m))
