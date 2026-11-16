"""Constants for the Proscenic Local integration (Proscenic M8 Pro / Tuya "sd" family)."""

DOMAIN = "proscenic_local"

CONF_HOST = "host"
CONF_DEVICE_ID = "device_id"
CONF_LOCAL_KEY = "local_key"
CONF_PROTOCOL_VERSION = "protocol_version"
CONF_AREAS = "areas"
CONF_MAP_ID = "map_id"

# Data points
DP_POWER = 1
DP_SWITCH_GO = 2   # command trigger (bool; write with DP_MODE atomically)
DP_MODE = 3        # mode (string enum)
DP_STATUS = 5      # status (string)
DP_BATTERY = 6     # residual_electricity (percent)
DP_SEEK = 13       # locate
DP_SUCTION = 14    # fan speed (string)
DP_RAW = 102       # rawData (base64 JSON with infoType)
DP_ERROR = 110

# Mode values (DP 3)
MODE_STANDBY = "standby"
MODE_RANDOM = "random"
MODE_SMART = "smart"
MODE_WALL_FOLLOW = "wall_follow"
MODE_MOP = "mop"
MODE_SPIRAL = "spiral"
MODE_CHARGEGO = "chargego"

# Status values (DP 5)
STATUS_STANDBY = "standby"
STATUS_SMART_CLEAN = "smart_clean"
STATUS_SPOT_CLEAN = "spot_clean"
STATUS_MOP_CLEAN = "mop_clean"
STATUS_CLEANING = "cleaning"
STATUS_PAUSED = "paused"
STATUS_RETURNING = "goto_charge"
STATUS_CHARGING = "charging"
STATUS_CHARGED = "charge_done"
STATUS_SLEEP = "sleep"

# Fan speeds (DP 14)
FAN_STRONG = "strong"
FAN_NORMAL = "normal"
FAN_GENTLE = "gentle"

# Timing / geometry
DEFAULT_SCAN_INTERVAL = 30   # seconds
RENDER_INTERVAL = 2.0        # seconds between map re-renders
CELL_RES_M = 0.05            # 5 cm coverage cell

# Optional config (set in the config flow). Empty works for local commands.
CONF_USER_ID = "user_id"

# Device defaults (the M8 Pro; MAP_ID changes after a full re-map)
DEFAULT_USER_ID = ""
DEFAULT_MAP_ID = 1794831825
