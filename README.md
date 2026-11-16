# Proscenic Local

A [Home Assistant](https://www.home-assistant.io/) integration for **Proscenic** robot vacuums (and compatible
Tuya "sd"-family LDS vacuums) that gives full local control, area cleaning, and a coverage map — **with no
cloud**.

Everything talks to the robot directly over the local Tuya protocol (TCP 6668) using the device's local key.
Once you have the key, no internet and no vendor app are needed.

## Features

- **Control** — start (whole-home auto), stop, pause, return-to-base, spot clean, and fan speed.
- **Area cleaning** — define rectangular areas in YAML and clean a named area, fully locally.
- **Coverage map** — renders where the robot has driven, built from its live path (no cloud floor plan).
- **Sensors** — covered area (m²) and area count.

## Install

**HACS:** add this repository as a custom repository (category *Integration*), then install "Proscenic Local".

**Manual:** copy `custom_components/proscenic_local/` into your Home Assistant `custom_components/` folder
and restart.

## Configure

Settings → Devices & services → Add integration → **Proscenic Local**:

| Field | Value |
|---|---|
| Host / IP address | the robot's IP (give it a DHCP reservation) |
| Device ID | the robot's Tuya device id (gwId) |
| Local key | the 16-char local key (see below) |
| Protocol version | `3.3` |
| User ID | optional; leave empty for local use |

### Getting the local key

The local key is generated when the robot is paired. It is **not** the Wi-Fi password. Common ways to obtain
it:

- a Tuya IoT developer project linked to the app account (`get_localkey.py` / the tinytuya wizard), or
- extracting it from the vendor app's storage on a rooted Android.

Re-pairing the robot rotates the key — pull it again after any re-pair.

## Entities

| Entity | Purpose |
|---|---|
| `vacuum.<name>` | control (start / stop / pause / return / spot / fan) |
| `image.<name>_coverage_map` | the coverage map |
| `sensor.<name>_covered_area` | covered area in m² |
| `sensor.<name>_areas` | number of defined areas |
| `select.<name>_area` | pick an area |
| `button.<name>_clean_area` | clean the selected area |

## Areas (YAML)

Areas are rectangles in **millimetres**. Define them with the `proscenic_local.add_area` service:

```yaml
service: proscenic_local.add_area
data:
  name: kitchen
  x1: 0
  y1: 0
  x2: 2000
  y2: 2000
```

Then clean one with:

```yaml
service: proscenic_local.clean_area
data:
  name: kitchen
```

Or pick an area in the `select.<name>_area` entity and press `button.<name>_clean_area`.

## Notes / limitations

- The coverage map is "where the robot has driven", not the cloud floor plan (walls). It builds up over runs.
- After a full re-map, update the `map_id` option if an area clean silently does nothing.
- One device per config entry; add the integration again for a second robot.
