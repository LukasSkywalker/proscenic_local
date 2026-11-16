"""Data coordinator for Proscenic Local: connection, state, path accumulation, areas."""
import io
import logging
import threading
import time
from datetime import timedelta

from PIL import Image, ImageDraw

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import protocol
from .const import (
    CONF_AREAS,
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_MAP_ID,
    CONF_PROTOCOL_VERSION,
    CONF_USER_ID,
    CELL_RES_M,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USER_ID,
    DP_BATTERY,
    DP_ERROR,
    DP_MODE,
    DP_RAW,
    DP_STATUS,
    DP_SUCTION,
    DP_SWITCH_GO,
    DOMAIN,
    MAP_SAVE_DELAY,
    MAX_LINE_GAP_MM,
    MODE_CHARGEGO,
    MODE_SMART,
    MODE_STANDBY,
    RENDER_INTERVAL,
    RENDER_LINE_WIDTH,
    RENDER_MARGIN_PX,
    RENDER_SCALE_PX_PER_MM,
    RENDER_WALL_PX,
    ROBOT_DIAMETER_MM,
)

_LOGGER = logging.getLogger(__name__)

COLOR_UNKNOWN = (205, 209, 217)  # never driven
COLOR_WALL = (60, 64, 75)
COLOR_FLOOR = (248, 249, 252)    # swept by the robot body
COLOR_PATH = (66, 110, 200)
COLOR_ROBOT = (220, 60, 50)


def _stroke(draw, pts, width, fill) -> None:
    """Polyline with a disc on every vertex: round caps/joints, and it plugs the
    1 px seams PIL leaves between wide segments (they let the wall colour through)."""
    if len(pts) > 1:
        draw.line(pts, fill=fill, width=round(width))
    r = width / 2
    for x, y in pts:
        draw.ellipse([x - r, y - r, x + r, y + r], fill=fill)


class ProscenicCoordinator(DataUpdateCoordinator):
    """Fetch robot state, accumulate the coverage path, and manage areas."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.entry = entry
        self.device_id = entry.data[CONF_DEVICE_ID]
        self.host = entry.data[CONF_HOST]
        self.local_key = entry.data[CONF_LOCAL_KEY]
        self.version = float(entry.data[CONF_PROTOCOL_VERSION])
        self.map_id = entry.options.get(CONF_MAP_ID, 1794831825)
        self.user_id = entry.data.get(CONF_USER_ID, DEFAULT_USER_ID)

        self._device = None
        self._monitor = None
        self._lock = threading.Lock()
        self._dps_lock = threading.Lock()
        self._dps_cache: dict = {}
        self._grid: set[tuple[int, int]] = set()
        self._path: list[list[tuple[float, float]]] = []
        self._seen: set[tuple[int, int]] = set()
        self._position: tuple[int, int] | None = None
        self._last_render = 0.0
        self._image: bytes | None = None
        self.selected_area: str | None = None
        # Lives in /config/.storage, so it survives restarts and HACS updates.
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.map")

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    # -- lifecycle ---------------------------------------------------------

    def _ensure_device(self):
        """Create the tinytuya device (blocking; call in executor)."""
        if self._device is None:
            import tinytuya

            self._device = tinytuya.Device(
                self.device_id, self.host, self.local_key, version=self.version
            )
            self._device.set_socketTimeout(6)
        return self._device

    def start_monitor(self) -> None:
        """Start the tinytuya Monitor on a daemon thread to catch DP pushes.

        The Monitor owns a single persistent socket to the robot. All further
        status queries and control writes are queued through this Monitor so the
        socket is only ever touched by the Monitor's reactor thread.
        """
        import tinytuya

        device = self._ensure_device()
        self._monitor = tinytuya.Monitor(
            on_status=self._on_status, auto_reconnect=True
        )
        self._monitor.add(device)
        self._monitor.start()
        # Prime the state cache: the response arrives as a DP push via _on_status.
        self._monitor.command(device, "status")

    def stop_monitor(self) -> None:
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None

    @staticmethod
    def _normalize_dps(dps: dict) -> dict:
        """tinytuya returns string DP keys; convert numeric ones to int.

        E.g. ``{"3": "standby", "102": "..."}`` -> ``{3: "standby", 102: "..."}``
        so the rest of the code can read with the integer DP constants.
        """
        out: dict = {}
        for key, value in dps.items():
            try:
                out[int(key)] = value
            except (ValueError, TypeError):
                out[key] = value
        return out

    def _on_status(self, device, result) -> None:
        """Monitor callback (runs on the monitor thread)."""
        dps = result.get("dps") if isinstance(result, dict) else result
        if not isinstance(dps, dict):
            return
        dps = self._normalize_dps(dps)
        with self._dps_lock:
            self._dps_cache.update(dps)
        raw = dps.get(DP_RAW)
        if isinstance(raw, str) and raw:
            if self._handle_raw(raw):
                self.hass.loop.call_soon_threadsafe(self._schedule_map_save)
        # Notify HA on its event loop (this callback runs off-loop).
        self.hass.loop.call_soon_threadsafe(
            self.async_set_updated_data, dict(self._dps_cache)
        )

    def _handle_raw(self, raw: str) -> bool:
        """Parse a DP 102 base64 JSON message; return True if the map changed."""
        try:
            msg = protocol.decode_raw(raw)
        except Exception:
            return False
        info_type = msg.get("infoType")
        elec = msg.get("data", {}).get("elec")
        if info_type == protocol.INFO_POSITION and elec is not None:
            # The robot never sends DP 6; battery % rides along in 20001 samples.
            with self._dps_lock:
                self._dps_cache[DP_BATTERY] = elec
        with self._lock:
            if info_type == protocol.INFO_PATH:
                path_id, points = protocol.parse_path_points(msg)
                protocol.accumulate_path(
                    self._grid, path_id, points, 0.0, 0.0, CELL_RES_M, self._seen
                )
            elif info_type == protocol.INFO_POSITION:
                pos = protocol.parse_position(msg)
                # The robot emits a transient (0,0) "no fix" sample; skip it so we
                # don't draw a star-shaped line out to the map origin and back.
                if len(pos) >= 2 and pos[0] == 0 and pos[1] == 0:
                    return False
                if len(pos) >= 2:
                    cell = protocol.mm_to_cell(pos[0], pos[1], 0.0, 0.0, CELL_RES_M)
                    prev = self._position
                    continuous = (
                        prev is not None
                        and len(prev) >= 2
                        and protocol.distance_mm(prev, pos) <= MAX_LINE_GAP_MM
                    )
                    # coverage grid (for the covered_area sensor)
                    if continuous:
                        prev_cell = protocol.mm_to_cell(
                            prev[0], prev[1], 0.0, 0.0, CELL_RES_M
                        )
                        self._grid.update(protocol.line_cells(prev_cell, cell))
                    else:
                        self._grid.add(cell)
                    # smooth path (for rendering)
                    if continuous and self._path:
                        self._path[-1].append(pos)
                    else:
                        self._path.append([pos])
                    self._position = pos
                    return True
                self._position = pos
        return info_type == protocol.INFO_PATH

    # -- persistence ------------------------------------------------------

    async def async_load_map(self) -> None:
        """Restore the coverage path saved before the last restart."""
        data = await self._store.async_load()
        if not data:
            return
        with self._lock:
            self._path = [[tuple(p) for p in seg] for seg in data["path"]]
            self._grid = {tuple(c) for c in data["grid"]}

    def _map_data(self) -> dict:
        with self._lock:
            return {"path": [list(seg) for seg in self._path], "grid": list(self._grid)}

    def _schedule_map_save(self) -> None:
        """Debounced write (event loop only); HA flushes pending writes on shutdown."""
        self._store.async_delay_save(self._map_data, MAP_SAVE_DELAY)

    # -- coordinator data -------------------------------------------------

    async def _async_update_data(self) -> dict:
        """Return the latest DPs.

        Before the Monitor owns the socket we do a direct blocking poll (safe:
        no persistent socket exists yet). Once the Monitor is running, queue a
        status query through it — the response comes back as a DP push and the
        cached DPs are returned here.
        """
        if self._monitor is None:
            def _poll():
                return self._ensure_device().status()

            status = await self.hass.async_add_executor_job(_poll)
            if isinstance(status, dict) and "dps" in status:
                with self._dps_lock:
                    self._dps_cache.update(self._normalize_dps(status["dps"]))
                return dict(self._dps_cache)
            return {}

        self._monitor.command(self._device, "status")
        with self._dps_lock:
            return dict(self._dps_cache)

    @property
    def state_dps(self) -> dict:
        return self.data or {}

    @property
    def covered_cells(self) -> int:
        with self._lock:
            return len(self._grid)

    @property
    def position(self) -> tuple[int, int] | None:
        with self._lock:
            return self._position

    @staticmethod
    def _bounds_from_points(points) -> dict | None:
        """Compute the mm bounding box + render transform for a point list."""
        if len(points) < 2:
            return None
        return {
            "min_x": min(p[0] for p in points),
            "max_x": max(p[0] for p in points),
            "min_y": min(p[1] for p in points),
            "max_y": max(p[1] for p in points),
            "scale": RENDER_SCALE_PX_PER_MM,
            "margin": RENDER_MARGIN_PX,
        }

    @property
    def map_bounds(self) -> dict | None:
        """Current mm↔px bounds, derived live from the accumulated path."""
        with self._lock:
            points = [p for seg in self._path for p in seg]
        return self._bounds_from_points(points)

    # -- areas ------------------------------------------------------------

    def areas(self) -> list[dict]:
        return list(self.entry.options.get(CONF_AREAS, []))

    def get_area(self, name: str) -> dict | None:
        return next((a for a in self.areas() if a["name"] == name), None)

    def _command(self, method: str, *args) -> None:
        """Dispatch a device method through the Monitor (single socket, one thread).

        If the Monitor has not started yet, fall back to calling the device
        directly (safe: no persistent socket exists yet).
        """
        if self._monitor is not None:
            self._monitor.command(self._device, method, *args)
        else:
            getattr(self._ensure_device(), method)(*args)

    async def control(self, mode: str) -> None:
        """Start a job in `mode`, or stop with `standby`.

        DP 2 (`switch_go`) True means *smart clean*, False means stop in place.
        Sent next to any other mode it wins within seconds (verified live:
        chargego and wall_follow both flipped), so only smart/standby write it;
        every other mode is DP 3 alone, which starts that mode by itself.
        """
        if mode in (MODE_SMART, MODE_STANDBY):
            self._command(
                "set_multiple_values",
                {str(DP_MODE): mode, str(DP_SWITCH_GO): mode == MODE_SMART},
            )
        else:
            self._command("set_value", DP_MODE, mode)

    async def return_to_base(self) -> None:
        """Dock: DP 3 = chargego alone (see control)."""
        await self.control(MODE_CHARGEGO)

    async def pause(self) -> None:
        """Pause the current job (switch_go = False)."""
        self._command("set_value", DP_SWITCH_GO, False)

    async def set_fan_speed(self, speed: str) -> None:
        """Set fan speed (DP 14)."""
        self._command("set_value", DP_SUCTION, speed)

    async def clean_area(self, name: str) -> None:
        area = self.get_area(name)
        if area is None:
            raise HomeAssistantError(
                f"no area named {name!r}; known: {[a['name'] for a in self.areas()]}"
            )
        cmd = protocol.build_clean_area_cmd(
            area, self.map_id, self.user_id, int(time.time() * 1000)
        )
        self._command("set_value", DP_RAW, protocol.encode_raw(cmd))

    async def add_area(self, name: str, x1: int, y1: int, x2: int, y2: int) -> None:
        areas = self.areas()
        if any(a["name"] == name for a in areas):
            raise HomeAssistantError(f"area named {name!r} already exists")
        # The card sends float mm; the robot expects integer vertices.
        x1, x2 = sorted((round(x1), round(x2)))
        y1, y2 = sorted((round(y1), round(y2)))
        new_id = max([a["id"] for a in areas], default=100) + 1
        areas.append(
            {
                "active": "normal",
                "appModel": "room",
                "id": new_id,
                "mode": "default",
                "name": name,
                "tag": str(new_id),
                "vertexs": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                "wall": False,
            }
        )
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, CONF_AREAS: areas}
        )

    async def remove_area(self, name: str) -> None:
        areas = [a for a in self.areas() if a["name"] != name]
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, CONF_AREAS: areas}
        )

    async def reload_map(self) -> None:
        with self._lock:
            self._grid.clear()
            self._path.clear()
            self._seen.clear()
            self._position = None
        self._schedule_map_save()

    # -- rendering --------------------------------------------------------

    def render_map(self) -> bytes | None:
        """Render walls, swept floor and the smooth path (throttled)."""
        now = time.time()
        if now - self._last_render < RENDER_INTERVAL:
            return self._image
        self._last_render = now
        with self._lock:
            path = [list(seg) for seg in self._path]
            position = self._position

        points = [p for seg in path for p in seg]
        bounds = self._bounds_from_points(points)
        if bounds is None:
            self._image = None
            return None

        min_x = bounds["min_x"]
        max_x = bounds["max_x"]
        min_y = bounds["min_y"]
        max_y = bounds["max_y"]

        scale = RENDER_SCALE_PX_PER_MM
        margin = RENDER_MARGIN_PX
        width = max(int((max_x - min_x) * scale) + 2 * margin, 1)
        height = max(int((max_y - min_y) * scale) + 2 * margin, 1)

        def to_px(x_mm: float, y_mm: float) -> tuple[float, float]:
            px = margin + (x_mm - min_x) * scale
            py = margin + (max_y - y_mm) * scale  # flip Y so +Y is up
            return px, py

        img = Image.new("RGB", (width, height), COLOR_UNKNOWN)
        draw = ImageDraw.Draw(img)
        segs = [[to_px(x, y) for x, y in seg] for seg in path if seg]

        # Walls = outline of everything the robot body swept over: stroke the
        # footprint fat in wall colour, then at true width in floor colour; a
        # RENDER_WALL_PX rim survives only where the robot never got further.
        foot = ROBOT_DIAMETER_MM * scale
        for w, fill in ((foot + 2 * RENDER_WALL_PX, COLOR_WALL), (foot, COLOR_FLOOR)):
            for pts in segs:
                _stroke(draw, pts, w, fill)

        for seg in path:
            if seg:
                pts = [to_px(x, y) for x, y in protocol.smooth_path(seg)]
                _stroke(draw, pts, RENDER_LINE_WIDTH, COLOR_PATH)

        # mark the current position
        if position is not None and len(position) >= 2:
            mx, my = to_px(position[0], position[1])
            draw.ellipse([mx - 4, my - 4, mx + 4, my + 4], fill=COLOR_ROBOT)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        self._image = buf.getvalue()
        return self._image
