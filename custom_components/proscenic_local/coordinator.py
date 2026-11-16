"""Data coordinator for Proscenic Local: connection, state, path accumulation, areas."""
import io
import logging
import threading
import time
from datetime import timedelta

from PIL import Image

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    RENDER_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


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
        self._seen: set[tuple[int, int]] = set()
        self._position: tuple[int, int] | None = None
        self._last_render = 0.0
        self._image: bytes | None = None
        self.selected_area: str | None = None

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

    def _on_status(self, device, result) -> None:
        """Monitor callback (runs on the monitor thread)."""
        dps = result.get("dps") if isinstance(result, dict) else result
        if not isinstance(dps, dict):
            return
        with self._dps_lock:
            self._dps_cache.update(dps)
        raw = dps.get(DP_RAW)
        if isinstance(raw, str) and raw:
            self._handle_raw(raw)
        # Notify HA on its event loop (this callback runs off-loop).
        self.hass.loop.call_soon_threadsafe(
            self.async_set_updated_data, dict(self._dps_cache)
        )

    def _handle_raw(self, raw: str) -> None:
        """Parse a DP 102 base64 JSON message and update the grid/position."""
        try:
            msg = protocol.decode_raw(raw)
        except Exception:
            return
        info_type = msg.get("infoType")
        with self._lock:
            if info_type == protocol.INFO_PATH:
                path_id, points = protocol.parse_path_points(msg)
                protocol.accumulate_path(
                    self._grid, path_id, points, 0.0, 0.0, CELL_RES_M, self._seen
                )
            elif info_type == protocol.INFO_POSITION:
                self._position = protocol.parse_position(msg)

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
                    self._dps_cache.update(status["dps"])
                return dict(status["dps"])
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
        """Write mode + trigger atomically (start/stop/return/spot)."""
        self._command(
            "set_multiple_values", {str(DP_MODE): mode, str(DP_SWITCH_GO): False}
        )

    async def pause(self) -> None:
        """Pause the current job."""
        self._command("set_value", DP_SWITCH_GO, True)

    async def set_fan_speed(self, speed: str) -> None:
        """Set fan speed (DP 14)."""
        self._command("set_value", DP_SUCTION, speed)

    async def clean_area(self, name: str) -> None:
        area = self.get_area(name)
        if area is None:
            raise ValueError(f"no area named {name!r}; known: {[a['name'] for a in self.areas()]}")
        cmd = protocol.build_clean_area_cmd(
            area, self.map_id, self.user_id, int(time.time() * 1000)
        )
        self._command("set_value", DP_RAW, protocol.encode_raw(cmd))

    async def add_area(self, name: str, x1: int, y1: int, x2: int, y2: int) -> None:
        areas = self.areas()
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
            self._seen.clear()
            self._position = None

    # -- rendering --------------------------------------------------------

    def render_map(self) -> bytes | None:
        """Render the coverage grid to a PNG (throttled). Return bytes or None."""
        now = time.time()
        if now - self._last_render < RENDER_INTERVAL:
            return self._image
        self._last_render = now
        with self._lock:
            grid = set(self._grid)
            position = self._position

        if not grid:
            self._image = None
            return None

        cols = [c for c, _ in grid]
        rows = [r for _, r in grid]
        min_c, max_c = min(cols), max(cols)
        min_r, max_r = min(rows), max(rows)
        width = max_c - min_c + 1
        height = max_r - min_r + 1

        img = Image.new("RGB", (width, height), (235, 238, 245))
        px = img.load()
        for c, r in grid:
            px[c - min_c, max_r - r] = (66, 110, 200)  # covered, flipped vertically

        scale = 6
        img = img.resize((width * scale, height * scale), Image.NEAREST)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        self._image = buf.getvalue()
        return self._image
