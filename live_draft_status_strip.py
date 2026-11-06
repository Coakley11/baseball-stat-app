"""Draft status strip for the Live Draft Room, the same in Solo and Shared drafts.

One glance shows who is on the clock, who picks next, when the viewer picks next, and the most recent
selections. It reads only the room (``pick_order``, ``current_pick_index``, ``draft_board``) and the
viewer's team as the page already resolved it (Shared: from the viewer's seat; Solo: the user team);
it never writes the room, so Shared Draft authority, synchronization and persistence are untouched.
"""

from __future__ import annotations

import html
from typing import Any

RECENT_PICKS = 5

_CSS = """
<style>
.ldr-strip { display:flex; flex-wrap:wrap; gap:.5rem; margin:.25rem 0 .75rem 0; }
.ldr-strip .ldr-cell { flex:1 1 9.5rem; min-width:9.5rem; border:1px solid #cbd5e1; border-radius:.6rem;
  padding:.45rem .65rem; background:#f8fafc; }
.ldr-strip .ldr-cell.now { border-color:#1e3a8a; background:#eff6ff; }
.ldr-strip .ldr-cell.you { border-color:#15803d; background:#f0fdf4; box-shadow:0 0 0 2px rgba(21,128,61,.18); }
.ldr-strip .ldr-k { font-size:.72rem; letter-spacing:.04em; text-transform:uppercase; color:#475569; }
.ldr-strip .ldr-v { font-weight:700; font-size:1rem; color:#0f172a; line-height:1.25; }
.ldr-strip .ldr-s { font-size:.78rem; color:#475569; }
.ldr-recent { display:flex; flex-wrap:wrap; gap:.35rem; margin:-.25rem 0 .75rem 0; align-items:center; }
.ldr-recent .ldr-k { font-size:.72rem; letter-spacing:.04em; text-transform:uppercase; color:#475569; margin-right:.15rem; }
.ldr-chip { border:1px solid #e2e8f0; border-radius:999px; padding:.15rem .55rem; font-size:.78rem; background:#fff; color:#0f172a; }
.ldr-chip.mine { border-color:#86efac; background:#f0fdf4; }
.ldr-chip b { color:#1e3a8a; }
@media (max-width: 640px) { .ldr-strip .ldr-cell { flex:1 1 45%; min-width:0; } }
</style>
"""


def _slot(order: list[Any], index: int) -> dict[str, Any]:
    if 0 <= index < len(order) and isinstance(order[index], dict):
        return order[index]
    return {}


def _player_name(row: dict[str, Any]) -> str:
    for key in ("fullName", "Player", "player_name", "Name", "name"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return "—"


def draft_status(room: dict[str, Any] | None, *, viewer_team: str = "") -> dict[str, Any]:
    """Who is on the clock, who is next, the viewer's next pick, and the latest picks. Pure."""
    room = room if isinstance(room, dict) else {}
    order = room.get("pick_order") if isinstance(room.get("pick_order"), list) else []
    board = [r for r in (room.get("draft_board") or []) if isinstance(r, dict)]
    try:
        index = int(room.get("current_pick_index") or 0)
    except (TypeError, ValueError):
        index = 0
    index = max(index, len(board)) if order and index < len(board) else index
    total = len(order)
    now, nxt = _slot(order, index), _slot(order, index + 1)
    viewer = str(viewer_team or "").strip()
    viewer_next = None
    if viewer:
        for i in range(index, total):
            if str(_slot(order, i).get("Team") or "") == viewer:
                viewer_next = i
                break
    recent = []
    for row in board[-RECENT_PICKS:][::-1]:
        recent.append({
            "pick": row.get("Pick"),
            "round": row.get("Round"),
            "team": str(row.get("Fantasy Team") or row.get("Team") or ""),
            "player": _player_name(row),
            "position": str(row.get("Primary Position") or row.get("Pos") or ""),
        })
    return {
        "complete": bool(total) and index >= total,
        "total": total,
        "current_pick": now.get("Pick") or (index + 1 if index < total else None),
        "round": now.get("Round"),
        "on_clock": str(now.get("Team") or ""),
        "up_next": str(nxt.get("Team") or ""),
        "up_next_pick": nxt.get("Pick"),
        "viewer_team": viewer,
        "viewer_on_clock": bool(viewer) and str(now.get("Team") or "") == viewer,
        "viewer_next_pick": _slot(order, viewer_next).get("Pick") if viewer_next is not None else None,
        "picks_until_viewer": (viewer_next - index) if viewer_next is not None else None,
        "recent": recent,
    }


def strip_html(status: dict[str, Any]) -> str:
    e = lambda v: html.escape(str(v if v is not None else ""))  # noqa: E731
    if status.get("complete"):
        return ""
    cells = []
    now_cls = "ldr-cell now you" if status.get("viewer_on_clock") else "ldr-cell now"
    cells.append(
        f'<div class="{now_cls}" role="status" aria-live="polite"><div class="ldr-k">On the clock</div>'
        f'<div class="ldr-v">{e(status.get("on_clock") or "—")}</div>'
        f'<div class="ldr-s">Pick {e(status.get("current_pick") or "—")} of {e(status.get("total") or "—")}'
        f' · Round {e(status.get("round") or "—")}</div></div>'
    )
    cells.append(
        f'<div class="ldr-cell"><div class="ldr-k">Up next</div>'
        f'<div class="ldr-v">{e(status.get("up_next") or "—")}</div>'
        f'<div class="ldr-s">{"Pick " + e(status.get("up_next_pick")) if status.get("up_next_pick") else "Last pick"}</div></div>'
    )
    if status.get("viewer_team"):
        if status.get("viewer_on_clock"):
            value, sub = "You're on the clock", e(status.get("viewer_team"))
        elif status.get("viewer_next_pick") is not None:
            away = int(status.get("picks_until_viewer") or 0)
            value = f"Pick {e(status.get('viewer_next_pick'))}"
            sub = f"{away} pick{'s' if away != 1 else ''} away · {e(status.get('viewer_team'))}"
        else:
            value, sub = "No picks left", e(status.get("viewer_team"))
        cls = "ldr-cell you" if status.get("viewer_on_clock") else "ldr-cell"
        cells.append(f'<div class="{cls}"><div class="ldr-k">Your next pick</div>'
                     f'<div class="ldr-v">{value}</div><div class="ldr-s">{sub}</div></div>')
    out = '<div class="ldr-strip">' + "".join(cells) + "</div>"
    recent = status.get("recent") or []
    if recent:
        chips = []
        for r in recent:
            mine = " mine" if status.get("viewer_team") and r.get("team") == status.get("viewer_team") else ""
            pos = f" {e(r.get('position'))}" if r.get("position") else ""
            chips.append(f'<span class="ldr-chip{mine}"><b>#{e(r.get("pick"))}</b> {e(r.get("player"))}{pos}'
                         f' · {e(r.get("team"))}</span>')
        out += '<div class="ldr-recent"><span class="ldr-k">Recent picks</span>' + "".join(chips) + "</div>"
    return out


def render_draft_status_strip(st: Any, room: dict[str, Any] | None, *, viewer_team: str = "") -> bool:
    """Paint the strip; False when there is nothing to show (no pick order, or the draft is over)."""
    status = draft_status(room, viewer_team=viewer_team)
    if not status.get("total") or status.get("complete"):
        return False
    st.markdown(_CSS + strip_html(status), unsafe_allow_html=True)
    return True
