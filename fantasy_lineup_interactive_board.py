"""Interactive circular face-to-circle Fantasy Lineup board."""

from __future__ import annotations

import html as html_lib
import json
from typing import Any

import pandas as pd

from fantasy_lineup_ui import (
    build_slot_key_labels,
    initials_from_name,
    photo_html_for_player,
)
from fantasy_weekly_lineup import (
    _player_name_col,
    eligible_players_for_slot,
    not_starting_players,
    player_eligible_for_slot,
    position_tokens_from_row,
    roster_player_names,
)

BENCH_ZONE = "__bench__"
FACE_SIZE = 72


def apply_board_drop(
    assignments: dict[str, str],
    slot_keys: list[tuple[str, str]],
    *,
    player: str,
    target: str,
    roster_df: pd.DataFrame,
) -> dict[str, str]:
    """Apply one face-to-circle drop onto canonical assignments."""
    player = str(player or "").strip()
    target = str(target or "").strip()
    valid_names = set(roster_player_names(roster_df))
    if not player or player not in valid_names:
        return dict(assignments)

    new = {key: str((assignments or {}).get(key) or "").strip() for key, _ in slot_keys}
    origin_key = next((key for key, _ in slot_keys if new.get(key) == player), "")

    if target == BENCH_ZONE:
        if origin_key:
            new[origin_key] = ""
        return new

    if target not in new:
        return dict(assignments)

    base_slot = target.split("_", 1)[0]
    name_col = _player_name_col(roster_df)
    lookup = {
        str(row[name_col]).strip(): row
        for _, row in roster_df.iterrows()
        if str(row.get(name_col) or "").strip()
    }
    row = lookup.get(player)
    if row is None or not player_eligible_for_slot(position_tokens_from_row(row), base_slot):
        return dict(assignments)

    displaced = new.get(target, "").strip()
    new[target] = player
    if origin_key and origin_key != target:
        new[origin_key] = ""
    # Displaced starter returns to bench (slot cleared).
    return new


def _face_inner_html(*, player_name: str, row: pd.Series | None, size: int) -> str:
    safe = html_lib.escape(player_name)
    photo_html, has_photo = photo_html_for_player(player_name=player_name, row=row, size=size)
    if has_photo:
        return photo_html.replace('class="fl-player-photo"', 'class="fl-face-img"')
    initials = html_lib.escape(initials_from_name(player_name))
    return (
        f'<div class="fl-face-fallback" aria-label="{safe}">'
        f'<span class="fl-face-fallback-icon" aria-hidden="true">⚾</span>'
        f'<span class="fl-face-initials">{initials}</span></div>'
    )


def build_interactive_board_payload(
    slot_labels: list,
    assignments: dict[str, str],
    roster_df: pd.DataFrame,
) -> dict[str, Any]:
    """JSON-serializable payload for the interactive circular board."""
    name_col = _player_name_col(roster_df)
    lookup = {
        str(row[name_col]).strip(): row
        for _, row in roster_df.iterrows()
        if str(row.get(name_col) or "").strip()
    }
    slot_keys = [(label.key, label.label) for label in slot_labels]
    slot_map = {label.key: str(assignments.get(label.key) or "").strip() for label in slot_labels}

    slots: list[dict[str, Any]] = []
    for label in slot_labels:
        player = slot_map.get(label.key) or ""
        eligible = eligible_players_for_slot(roster_df, label.base_slot)
        slots.append(
            {
                "key": label.key,
                "label": label.label,
                "badge": label.badge,
                "base_slot": label.base_slot,
                "player": player or None,
                "eligible": eligible,
            }
        )

    bench_names = not_starting_players(roster_df, slot_map)
    bench: list[dict[str, Any]] = []
    for name in bench_names:
        row = lookup.get(name)
        bench.append(
            {
                "name": name,
                "positions": "/".join(position_tokens_from_row(row)[:4]) if row is not None else "",
            }
        )

    faces: dict[str, str] = {}
    for name in roster_player_names(roster_df):
        row = lookup.get(name)
        faces[name] = _face_inner_html(player_name=name, row=row, size=FACE_SIZE)

    return {
        "slots": slots,
        "bench": bench,
        "faces": faces,
        "assignments": slot_map,
        "slot_keys": [key for key, _ in slot_keys],
    }


def _board_height(payload: dict[str, Any]) -> int:
    slot_count = len(payload.get("slots") or [])
    bench_count = len(payload.get("bench") or [])
    slot_rows = max(1, (slot_count + 3) // 4)
    bench_rows = max(1, (bench_count + 5) // 6)
    return 120 + slot_rows * 130 + 80 + bench_rows * 110 + 40


def render_interactive_lineup_board(
    st: Any,
    *,
    payload: dict[str, Any],
    component_key: str,
) -> Any:
    """Render the editable circular board; returns drop payload from prior interaction."""
    del component_key  # html component has no key param in this Streamlit build
    try:
        import streamlit.components.v1 as components
    except ImportError:
        st.warning("Interactive lineup board is unavailable in this environment.")
        return None

    payload_json = json.dumps(payload, ensure_ascii=False)
    payload_json = payload_json.replace("</", "<\\/")
    height = _board_height(payload)

    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 8px 4px 12px;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  color: #0f172a; background: transparent;
  -webkit-tap-highlight-color: transparent;
}}
.fl-board-title {{
  font-size: 1.05rem; font-weight: 800; margin: 4px 0 12px;
}}
.fl-circle-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(88px, 1fr));
  gap: 14px 10px;
  margin-bottom: 18px;
}}
.fl-circle-slot {{
  display: flex; flex-direction: column; align-items: center;
  text-align: center; min-width: 0;
}}
.fl-slot-label {{
  font-size: 0.72rem; font-weight: 800; letter-spacing: 0.04em;
  color: #0b3d6e; margin-bottom: 6px;
}}
.fl-circle-drop {{
  width: {FACE_SIZE}px; height: {FACE_SIZE}px;
  border-radius: 50%;
  border: 2px dashed #94a3b8;
  background: #f8fafc;
  display: flex; align-items: center; justify-content: center;
  position: relative;
  transition: border-color 0.12s, box-shadow 0.12s, transform 0.12s, background 0.12s;
}}
.fl-circle-drop.filled {{
  border-style: solid;
  border-color: rgba(11, 61, 110, 0.35);
  background: #fff;
}}
.fl-circle-drop.eligible {{
  border-color: #38bdf8;
  background: #e0f2fe;
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.25);
}}
.fl-circle-drop.hover-target {{
  border-color: #0b3d6e;
  background: #dbeafe;
  box-shadow: 0 0 0 4px rgba(11, 61, 110, 0.35);
  transform: scale(1.06);
}}
.fl-circle-drop.ineligible {{
  opacity: 0.35;
}}
.fl-face {{
  width: {FACE_SIZE}px; height: {FACE_SIZE}px;
  border-radius: 50%;
  cursor: grab;
  touch-action: pan-y;
  position: relative;
  flex-shrink: 0;
  transition: transform 0.12s, box-shadow 0.12s;
}}
.fl-face.dragging {{
  cursor: grabbing;
  transform: scale(1.12);
  box-shadow: 0 10px 24px rgba(11, 61, 110, 0.35);
  z-index: 50;
}}
.fl-face-img, .fl-face-fallback {{
  width: 100%; height: 100%;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid rgba(11, 61, 110, 0.25);
  display: flex; align-items: center; justify-content: center;
  background: #edf2f7;
  overflow: hidden;
}}
.fl-face-fallback-icon {{ font-size: 1.1rem; opacity: 0.5; position: absolute; }}
.fl-face-initials {{ font-size: 0.82rem; font-weight: 800; z-index: 1; }}
.fl-slot-player-name {{
  font-size: 0.68rem; font-weight: 700; color: #334155;
  margin-top: 5px; max-width: 92px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.fl-bench-zone {{
  border: 2px dashed #cbd5e1;
  border-radius: 16px;
  padding: 12px;
  background: #fafbfc;
  transition: border-color 0.12s, background 0.12s, box-shadow 0.12s;
}}
.fl-bench-zone.eligible {{
  border-color: #38bdf8;
  background: #eff6ff;
  box-shadow: inset 0 0 0 2px rgba(56, 189, 248, 0.2);
}}
.fl-bench-zone.hover-target {{
  border-color: #0b3d6e;
  background: #dbeafe;
}}
.fl-bench-faces {{
  display: flex; flex-wrap: wrap; gap: 12px;
  justify-content: center; padding: 6px 0;
}}
.fl-bench-face-wrap {{
  display: flex; flex-direction: column; align-items: center; min-width: 72px;
}}
.fl-bench-name {{
  font-size: 0.66rem; font-weight: 700; color: #475569;
  margin-top: 4px; max-width: 80px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.fl-drag-ghost {{
  position: fixed; pointer-events: none; z-index: 9999;
  width: {FACE_SIZE}px; height: {FACE_SIZE}px;
  border-radius: 50%;
  transform: translate(-50%, -50%) scale(1.12);
  box-shadow: 0 12px 28px rgba(11, 61, 110, 0.4);
  opacity: 0.95;
}}
body.fl-drag-active {{
  overflow: hidden;
  touch-action: none;
}}
@media (max-width: 480px) {{
  .fl-circle-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px 6px; }}
}}
</style>
</head>
<body>
<div id="fl-board-root"></div>
<script>
(function() {{
  const PAYLOAD = {payload_json};
  const HOLD_MS = 280;
  const MOVE_TOL = 8;
  const BENCH = "{BENCH_ZONE}";

  const root = document.getElementById("fl-board-root");
  const faces = PAYLOAD.faces || {{}};
  let assignments = Object.assign({{}}, PAYLOAD.assignments || {{}});
  let drag = null;
  let ghost = null;

  function faceHtml(name) {{
    return faces[name] || '<div class="fl-face-fallback"><span class="fl-face-initials">?</span></div>';
  }}

  function slotEl(key) {{
    return document.querySelector('.fl-circle-drop[data-slot-key="' + key + '"]');
  }}

  function benchEl() {{
    return document.querySelector('.fl-bench-zone');
  }}

  function eligibleFor(slotKey, player) {{
    const slot = (PAYLOAD.slots || []).find(s => s.key === slotKey);
    if (!slot) return false;
    return (slot.eligible || []).includes(player);
  }}

  function render() {{
    let html = '<div class="fl-board-title">Starting Lineup</div><div class="fl-circle-grid">';
    (PAYLOAD.slots || []).forEach(slot => {{
      const player = assignments[slot.key] || "";
      const filled = !!player;
      html += '<div class="fl-circle-slot">';
      html += '<div class="fl-slot-label">' + slot.label + '</div>';
      html += '<div class="fl-circle-drop' + (filled ? ' filled' : '') + '" data-slot-key="' + slot.key + '" data-base-slot="' + slot.base_slot + '">';
      if (filled) {{
        html += '<div class="fl-face" data-player="' + player + '" data-origin="' + slot.key + '">' + faceHtml(player) + '</div>';
      }}
      html += '</div>';
      if (filled) {{
        html += '<div class="fl-slot-player-name">' + player + '</div>';
      }}
      html += '</div>';
    }});
    html += '</div><div class="fl-board-title">Bench</div>';
    html += '<div class="fl-bench-zone" data-zone="bench"><div class="fl-bench-faces">';
    (PAYLOAD.bench || []).forEach(p => {{
      html += '<div class="fl-bench-face-wrap">';
      html += '<div class="fl-face" data-player="' + p.name + '" data-origin="bench">' + faceHtml(p.name) + '</div>';
      html += '<div class="fl-bench-name">' + p.name + '</div></div>';
    }});
    html += '</div></div>';
    root.innerHTML = html;
    bindFaces();
  }}

  function sendDrop(player, target) {{
    const out = Object.assign({{}}, assignments);
    const origin = Object.keys(out).find(k => out[k] === player) || "";
    if (target === BENCH) {{
      if (origin) out[origin] = "";
    }} else if (target && Object.prototype.hasOwnProperty.call(out, target)) {{
      out[target] = player;
      if (origin && origin !== target) out[origin] = "";
    }}
    assignments = out;
    render();
    window.parent.postMessage({{
      type: "streamlit:setComponentValue",
      value: JSON.stringify({{ player: player, target: target, assignments: out }})
    }}, "*");
  }}

  function clearHighlights() {{
    document.querySelectorAll(".eligible,.hover-target,.ineligible").forEach(el => {{
      el.classList.remove("eligible", "hover-target", "ineligible");
    }});
  }}

  function highlightAt(x, y, player) {{
    clearHighlights();
    const el = document.elementFromPoint(x, y);
    if (!el) return null;
    const drop = el.closest(".fl-circle-drop");
    const bench = el.closest(".fl-bench-zone");
    if (drop) {{
      const key = drop.dataset.slotKey;
      if (eligibleFor(key, player)) {{
        drop.classList.add("eligible", "hover-target");
        return key;
      }}
      drop.classList.add("ineligible");
      return null;
    }}
    if (bench) {{
      bench.classList.add("eligible", "hover-target");
      return BENCH;
    }}
    return null;
  }}

  function startDrag(face, player, origin, x, y) {{
    drag = {{ face, player, origin, x, y, active: true }};
    face.classList.add("dragging");
    document.body.classList.add("fl-drag-active");
    ghost = document.createElement("div");
    ghost.className = "fl-drag-ghost";
    ghost.innerHTML = face.innerHTML;
    ghost.style.left = x + "px";
    ghost.style.top = y + "px";
    document.body.appendChild(ghost);
    document.querySelectorAll(".fl-circle-drop").forEach(drop => {{
      if (eligibleFor(drop.dataset.slotKey, player)) drop.classList.add("eligible");
      else drop.classList.add("ineligible");
    }});
    benchEl()?.classList.add("eligible");
  }}

  function endDrag(x, y) {{
    if (!drag) return;
    const target = highlightAt(x, y, drag.player);
    const player = drag.player;
    drag.face.classList.remove("dragging");
    if (ghost) ghost.remove();
    ghost = null;
    clearHighlights();
    document.body.classList.remove("fl-drag-active");
    if (target && (target === BENCH || eligibleFor(target, player))) {{
      sendDrop(player, target);
    }}
    drag = null;
  }}

  function bindFaces() {{
    document.querySelectorAll(".fl-face").forEach(face => {{
      const player = face.dataset.player;
      const origin = face.dataset.origin || "bench";
      let holdTimer = null;
      let startX = 0, startY = 0;
      let tracking = false;

      function onDown(e) {{
        if (e.button !== undefined && e.button !== 0) return;
        tracking = true;
        startX = e.clientX;
        startY = e.clientY;
        holdTimer = setTimeout(() => {{
          if (tracking) startDrag(face, player, origin, startX, startY);
        }}, HOLD_MS);
      }}
      function onMove(e) {{
        if (!tracking) return;
        const dx = e.clientX - startX;
        const dy = e.clientY - startY;
        if (!drag && Math.hypot(dx, dy) > MOVE_TOL) {{
          clearTimeout(holdTimer);
          tracking = false;
          return;
        }}
        if (drag && drag.active) {{
          e.preventDefault();
          if (ghost) {{
            ghost.style.left = e.clientX + "px";
            ghost.style.top = e.clientY + "px";
          }}
          highlightAt(e.clientX, e.clientY, player);
        }}
      }}
      function onUp(e) {{
        clearTimeout(holdTimer);
        if (drag && drag.active) {{
          e.preventDefault();
          endDrag(e.clientX, e.clientY);
        }}
        tracking = false;
      }}
      face.addEventListener("pointerdown", onDown);
      face.addEventListener("pointermove", onMove);
      face.addEventListener("pointerup", onUp);
      face.addEventListener("pointercancel", onUp);
    }});
  }}

  render();
}})();
</script>
</body>
</html>
"""
    return components.html(html, height=height, scrolling=False)


def parse_board_drop_result(result: Any) -> dict[str, Any] | None:
    """Parse component return value from a face drop."""
    if result is None:
        return None
    if isinstance(result, dict):
        return result
    if isinstance(result, str) and result.strip():
        try:
            parsed = json.loads(result)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None
