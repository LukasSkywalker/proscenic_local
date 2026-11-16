/*
 * Proscenic Local — areas card
 *
 * A Lovelace custom card that shows the coverage map as a background and lets
 * the user draw rectangular cleaning areas on top of it.
 *
 * Config:
 *   type: custom:proscenic-areas-card
 *   entity: image.<name>_coverage_map
 *
 * The image entity exposes (via extra_state_attributes):
 *   - entity_picture: URL of the rendered map PNG
 *   - map_bounds: { min_x, max_x, min_y, max_y, scale, margin } (mm -> px)
 *   - areas: [ { name, vertexs: [[x1,y1],[x2,y1],[x2,y2],[x1,y2]], ... }, ... ]
 *
 * Interaction:
 *   - type a name, then drag a rectangle on the map to add it (auto-added on
 *     release when a name is present)
 *   - drag first, then type a name and click "Add" to commit
 *   - click (no drag) on an existing rectangle to delete it
 */

// Pure coordinate transforms. The renderer (coordinator.render_map) uses
//   px = margin + (x_mm - min_x) * scale
//   py = margin + (max_y - y_mm) * scale   (Y flipped so +Y is up)
// These are the exact inverses / forwards.
function mmToPx(x, y, b) {
  return [b.margin + (x - b.min_x) * b.scale, b.margin + (b.max_y - y) * b.scale];
}

function pxToMm(px, py, b) {
  return [b.min_x + (px - b.margin) / b.scale, b.max_y - (py - b.margin) / b.scale];
}

// Bounding box (mm) of a polygon's vertices.
function areaBounds(vertexs) {
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const p of vertexs) {
    const x = p[0];
    const y = p[1];
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  }
  return { minX, maxX, minY, maxY };
}

// Map the robot's DP 5 status string to a short human label.
const STATUS_LABELS = {
  charging: "Charging",
  charged: "Charged",
  cleaning: "Cleaning",
  smart_clean: "Cleaning",
  spot_clean: "Cleaning",
  mop_clean: "Cleaning",
  paused: "Paused",
  goto_charge: "Returning",
  standby: "Idle",
  sleep: "Idle",
};

function humanizeStatus(status, batteryLevel) {
  const label = STATUS_LABELS[status] || "Idle";
  if (batteryLevel === null || batteryLevel === undefined) {
    return label;
  }
  return `${label} · ${batteryLevel}%`;
}

const CLICK_THRESHOLD_PX = 5;

class ProscenicAreasCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) {
      throw new Error("You need to define an entity");
    }
    this._config = config;
    if (this._built) this._render();
  }

  set hass(h) {
    this._hass = h;
    if (this._built) this._render();
  }

  get hass() {
    return this._hass;
  }

  getCardSize() {
    return 5;
  }

  connectedCallback() {
    if (!this._built) {
      this._build();
      this._built = true;
    }
    this._render();
  }

  disconnectedCallback() {
    this._detachPointer();
  }

  _build() {
    this._card = document.createElement("ha-card");
    this._card.style.padding = "16px";

    // Robot status line (charging / battery), shown above the header.
    this._robotStatus = document.createElement("div");
    this._robotStatus.style.fontWeight = "500";
    this._robotStatus.style.marginBottom = "12px";
    this._robotStatus.style.display = "none";

    // Header: name input + Add button + status
    const header = document.createElement("div");
    header.style.display = "flex";
    header.style.gap = "8px";
    header.style.alignItems = "center";
    header.style.marginBottom = "12px";

    this._nameInput = document.createElement("input");
    this._nameInput.type = "text";
    this._nameInput.placeholder = "Area name";
    this._nameInput.style.flex = "1";
    this._nameInput.style.padding = "6px 8px";

    this._addBtn = document.createElement("button");
    this._addBtn.textContent = "Add";
    this._addBtn.style.cursor = "pointer";
    this._addBtn.addEventListener("click", () => this._addPending());

    this._status = document.createElement("span");
    this._status.style.fontSize = "0.85em";
    this._status.style.opacity = "0.8";

    header.appendChild(this._nameInput);
    header.appendChild(this._addBtn);
    header.appendChild(this._status);

    // Map wrapper
    this._wrapper = document.createElement("div");
    this._wrapper.style.position = "relative";
    this._wrapper.style.width = "100%";
    this._wrapper.style.lineHeight = "0";
    this._wrapper.style.borderRadius = "4px";
    this._wrapper.style.overflow = "hidden";

    this._img = document.createElement("img");
    this._img.style.width = "100%";
    this._img.style.display = "block";
    this._img.draggable = false;
    this._img.addEventListener("load", () => this._onImageLoad());

    this._canvas = document.createElement("canvas");
    this._canvas.style.position = "absolute";
    this._canvas.style.top = "0";
    this._canvas.style.left = "0";
    this._canvas.style.width = "100%";
    this._canvas.style.height = "100%";
    this._canvas.style.cursor = "crosshair";

    this._wrapper.appendChild(this._img);
    this._wrapper.appendChild(this._canvas);

    // Placeholder
    this._placeholder = document.createElement("div");
    this._placeholder.textContent = "No map yet — the robot has not reported a path.";
    this._placeholder.style.padding = "16px";
    this._placeholder.style.opacity = "0.7";
    this._placeholder.style.display = "none";

    this._card.appendChild(this._robotStatus);
    this._card.appendChild(header);
    this._card.appendChild(this._wrapper);
    this._card.appendChild(this._placeholder);
    this.appendChild(this._card);

    this._attachPointer();
  }

  _attachPointer() {
    this._onPointerDown = (e) => this._handlePointerDown(e);
    this._onPointerMove = (e) => this._handlePointerMove(e);
    this._onPointerUp = (e) => this._handlePointerUp(e);
    this._canvas.addEventListener("pointerdown", this._onPointerDown);
    this._canvas.addEventListener("pointermove", this._onPointerMove);
    this._canvas.addEventListener("pointerup", this._onPointerUp);
  }

  _detachPointer() {
    if (!this._canvas) return;
    this._canvas.removeEventListener("pointerdown", this._onPointerDown);
    this._canvas.removeEventListener("pointermove", this._onPointerMove);
    this._canvas.removeEventListener("pointerup", this._onPointerUp);
  }

  _render() {
    const state = this._hass && this._hass.states[this._config.entity];
    const attrs = state ? state.attributes : {};
    const url = attrs.entity_picture;
    const bounds = attrs.map_bounds;

    this._bounds = bounds;
    this._areas = Array.isArray(attrs.areas) ? attrs.areas : [];

    const status = attrs.status;
    const battery = attrs.battery_level;
    if (status !== undefined || battery !== undefined) {
      this._robotStatus.textContent = humanizeStatus(status, battery);
      this._robotStatus.style.display = "";
    } else {
      this._robotStatus.style.display = "none";
    }

    if (!url || !bounds) {
      this._wrapper.style.display = "none";
      this._placeholder.style.display = "block";
      return;
    }

    this._wrapper.style.display = "block";
    this._placeholder.style.display = "none";
    if (this._currentUrl !== url) {
      this._currentUrl = url;
      this._img.src = url;
    }
    this._draw();
  }

  _onImageLoad() {
    this._canvas.width = this._img.naturalWidth;
    this._canvas.height = this._img.naturalHeight;
    this._draw();
  }

  _draw() {
    if (!this._canvas.width || !this._bounds) return;
    const ctx = this._canvas.getContext("2d");
    ctx.clearRect(0, 0, this._canvas.width, this._canvas.height);

    for (const area of this._areas) {
      const vs = area.vertexs;
      if (!Array.isArray(vs) || vs.length < 2) continue;
      const b = areaBounds(vs);
      const [x1, y1] = mmToPx(b.minX, b.minY, this._bounds);
      const [x2, y2] = mmToPx(b.maxX, b.maxY, this._bounds);
      const px = Math.min(x1, x2);
      const py = Math.min(y1, y2);
      const w = Math.abs(x2 - x1);
      const h = Math.abs(y2 - y1);

      ctx.fillStyle = "rgba(66, 110, 200, 0.22)";
      ctx.fillRect(px, py, w, h);
      ctx.strokeStyle = "rgba(66, 110, 200, 0.9)";
      ctx.lineWidth = 2;
      ctx.strokeRect(px, py, w, h);

      if (area.name) {
        ctx.fillStyle = "rgba(30, 60, 130, 0.95)";
        ctx.font = "12px sans-serif";
        ctx.fillText(area.name, px + 4, py + 16);
      }
    }

    if (this._pending) {
      const b = this._pending;
      const [x1, y1] = mmToPx(b.x1, b.y1, this._bounds);
      const [x2, y2] = mmToPx(b.x2, b.y2, this._bounds);
      const px = Math.min(x1, x2);
      const py = Math.min(y1, y2);
      const w = Math.abs(x2 - x1);
      const h = Math.abs(y2 - y1);
      ctx.strokeStyle = "rgba(220, 60, 50, 0.9)";
      ctx.setLineDash([6, 4]);
      ctx.lineWidth = 2;
      ctx.strokeRect(px, py, w, h);
      ctx.setLineDash([]);
    }
  }

  _clientToNatural(e) {
    const rect = this._canvas.getBoundingClientRect();
    return [
      (e.clientX - rect.left) * (this._img.naturalWidth / rect.width),
      (e.clientY - rect.top) * (this._img.naturalHeight / rect.height),
    ];
  }

  _handlePointerDown(e) {
    if (!this._bounds) return;
    try {
      this._canvas.setPointerCapture(e.pointerId);
    } catch (_) {
      /* ignore */
    }
    const [nx, ny] = this._clientToNatural(e);
    this._drag = {
      startX: nx,
      startY: ny,
      curX: nx,
      curY: ny,
      startClientX: e.clientX,
      startClientY: e.clientY,
      curClientX: e.clientX,
      curClientY: e.clientY,
    };
  }

  _handlePointerMove(e) {
    if (!this._drag || !this._bounds) return;
    const [nx, ny] = this._clientToNatural(e);
    this._drag.curX = nx;
    this._drag.curY = ny;
    this._drag.curClientX = e.clientX;
    this._drag.curClientY = e.clientY;
    const [x1, y1] = pxToMm(this._drag.startX, this._drag.startY, this._bounds);
    const [x2, y2] = pxToMm(nx, ny, this._bounds);
    this._pending = { x1, y1, x2, y2 };
    this._draw();
  }

  _handlePointerUp(e) {
    if (!this._drag || !this._bounds) return;
    const drag = this._drag;
    this._drag = null;

    const dist = Math.hypot(
      drag.curClientX - drag.startClientX,
      drag.curClientY - drag.startClientY
    );
    const [x1, y1] = pxToMm(drag.startX, drag.startY, this._bounds);
    const [x2, y2] = pxToMm(drag.curX, drag.curY, this._bounds);

    if (dist < CLICK_THRESHOLD_PX) {
      // A click: try to delete the area under the cursor.
      this._pending = null;
      this._draw();
      this._hitTestDelete([x1, y1]);
      return;
    }

    // A drag: keep the rectangle as pending; auto-add if a name is present.
    this._pending = {
      x1: Math.min(x1, x2),
      y1: Math.min(y1, y2),
      x2: Math.max(x1, x2),
      y2: Math.max(y1, y2),
    };
    this._draw();

    const name = (this._nameInput.value || "").trim();
    if (name) {
      this._addPending();
    } else {
      this._setStatus("Type a name, then click Add");
    }
  }

  _addPending() {
    const name = (this._nameInput.value || "").trim();
    if (!this._pending) {
      this._setStatus("Draw a rectangle first");
      return;
    }
    if (!name) {
      this._setStatus("Type a name first");
      return;
    }
    const { x1, y1, x2, y2 } = this._pending;
    this._pending = null;
    this._draw();
    this._hass
      .callService(
        "proscenic_local",
        "add_area",
        { name, x1, y1, x2, y2 },
        { entity_id: [this._config.entity] }
      )
      .then(() => this._setStatus(`Added "${name}"`))
      .catch((err) => this._setStatus(`Error: ${err && err.message ? err.message : err}`));
  }

  _hitTestDelete(point) {
    const [xMm, yMm] = point;
    for (let i = this._areas.length - 1; i >= 0; i--) {
      const area = this._areas[i];
      const vs = area.vertexs;
      if (!Array.isArray(vs) || vs.length < 2) continue;
      const b = areaBounds(vs);
      if (xMm >= b.minX && xMm <= b.maxX && yMm >= b.minY && yMm <= b.maxY) {
        this._hass
          .callService(
            "proscenic_local",
            "remove_area",
            { name: area.name },
            { entity_id: [this._config.entity] }
          )
          .then(() => this._setStatus(`Removed "${area.name}"`))
          .catch((err) => this._setStatus(`Error: ${err && err.message ? err.message : err}`));
        return;
      }
    }
  }

  _setStatus(text) {
    this._status.textContent = text;
  }
}

if (!customElements.get("proscenic-areas-card")) {
  customElements.define("proscenic-areas-card", ProscenicAreasCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "proscenic-areas-card",
  name: "Proscenic Areas",
  description: "Draw cleaning areas on the coverage map",
});
