"""Canonical Live Draft room snapshot — one source for all UI components in a render cycle.

Sidebar, On the Clock banner, timer, board, queue, and recommendations must read the
same pick index, team, revision, and deadline from this snapshot after every commit.
"""

from __future__ import annotations

from typing import Any

CANONICAL_SNAPSHOT_KEY = "_live_draft_canonical_snapshot"
CANONICAL_TRANSITION_LOG_KEY = "_live_draft_pick_transition_log"
MAX_TRANSITION_LOG = 40


def _revision(room: dict[str, Any] | None) -> int:
    if not isinstance(room, dict):
        return 0
    try:
        meta = room.get("meta") if isinstance(room.get("meta"), dict) else {}
        sync = meta.get("sync") if isinstance(meta.get("sync"), dict) else {}
        return int(sync.get("revision") or room.get("revision") or 0)
    except (TypeError, ValueError):
        return 0


def _draft_id(room: dict[str, Any] | None) -> str:
    if not isinstance(room, dict):
        return ""
    return str(
        room.get("draft_room_id") or room.get("room_id") or room.get("draft_id") or ""
    ).strip()


def build_canonical_live_draft_snapshot(
    room: dict[str, Any] | None,
    *,
    session: dict[str, Any] | None = None,
    state_source: str = "live_draft_room",
) -> dict[str, Any]:
    """Build the authoritative Solo/Shared display snapshot from the runtime room."""
    room = room if isinstance(room, dict) else {}
    pick_index = int(room.get("current_pick_index") or 0)
    board = list(room.get("draft_board") or [])
    status = str(room.get("status") or "").strip()
    team = ""
    pick_number = None
    round_number = None
    try:
        from live_draft_timer_logic import live_draft_current_slot, live_draft_timer_deadline

        slot = live_draft_current_slot(room)
        if isinstance(slot, dict):
            team = str(slot.get("Team") or "").strip()
            try:
                pick_number = int(slot.get("Pick"))
            except (TypeError, ValueError):
                pick_number = None
            try:
                round_number = int(slot.get("Round"))
            except (TypeError, ValueError):
                round_number = None
        deadline = live_draft_timer_deadline(room)
    except ImportError:
        deadline = room.get("timer_deadline")
        order = list(room.get("pick_order") or [])
        if 0 <= pick_index < len(order) and isinstance(order[pick_index], dict):
            team = str(order[pick_index].get("Team") or "").strip()
            try:
                pick_number = int(order[pick_index].get("Pick"))
            except (TypeError, ValueError):
                pick_number = None
            try:
                round_number = int(order[pick_index].get("Round"))
            except (TypeError, ValueError):
                round_number = None

    drafted_ids = [
        str(x).strip()
        for x in (room.get("drafted_player_ids") or [])
        if str(x).strip()
    ]
    snap = {
        "draft_id": _draft_id(room),
        "revision": _revision(room),
        "status": status,
        "current_pick_index": pick_index,
        "current_pick": pick_number if pick_number is not None else (pick_index + 1 if status == "in_progress" else None),
        "round": round_number,
        "team_on_clock": team,
        "timer_deadline": float(deadline) if deadline is not None else None,
        "board_size": len(board),
        "drafted_player_ids": drafted_ids,
        "drafted_count": len(drafted_ids),
        "state_source": str(state_source or "live_draft_room"),
    }
    if isinstance(session, dict):
        session[CANONICAL_SNAPSHOT_KEY] = snap
    return snap


def install_canonical_live_draft_snapshot(
    session: dict[str, Any],
    room: dict[str, Any] | None,
    *,
    state_source: str = "live_draft_room",
) -> dict[str, Any]:
    return build_canonical_live_draft_snapshot(room, session=session, state_source=state_source)


def get_canonical_live_draft_snapshot(
    session: dict[str, Any] | None,
    room: dict[str, Any] | None = None,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    session = session if isinstance(session, dict) else {}
    existing = session.get(CANONICAL_SNAPSHOT_KEY)
    if refresh or not isinstance(existing, dict) or not existing:
        live = room
        if not isinstance(live, dict):
            live = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
        return install_canonical_live_draft_snapshot(session, live, state_source="refresh")
    return dict(existing)


def note_pick_transition(
    session: dict[str, Any],
    *,
    event: str,
    draft_id: str = "",
    pick_index: int | None = None,
    revision: int | None = None,
    team_on_clock: str = "",
    player_id: str = "",
    player_name: str = "",
    elapsed_ms: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Instrument timer→commit→paint transitions (admin diagnostics)."""
    import time

    row = {
        "event": str(event or ""),
        "ts": time.time(),
        "draft_id": str(draft_id or ""),
        "pick_index": pick_index,
        "revision": revision,
        "team_on_clock": str(team_on_clock or ""),
        "player_id": str(player_id or ""),
        "player_name": str(player_name or ""),
        "elapsed_ms": elapsed_ms,
    }
    if extra:
        row.update({k: v for k, v in extra.items() if v is not None})
    log = list(session.get(CANONICAL_TRANSITION_LOG_KEY) or [])
    log.append(row)
    session[CANONICAL_TRANSITION_LOG_KEY] = log[-MAX_TRANSITION_LOG:]


def auto_pick_idempotency_key(
    room: dict[str, Any] | None,
    *,
    pick_index: int | None = None,
    board_size: int | None = None,
) -> str:
    """Idempotency key so multiple fragments cannot commit the same auto-pick."""
    room = room if isinstance(room, dict) else {}
    idx = int(pick_index if pick_index is not None else room.get("current_pick_index") or 0)
    rev = _revision(room)
    board = int(board_size if board_size is not None else len(room.get("draft_board") or []))
    return f"{_draft_id(room)}|pick={idx}|rev={rev}|board={board}"


def apply_canonical_to_slot_views(
    session: dict[str, Any],
    room: dict[str, Any] | None = None,
    *,
    refresh: bool = True,
) -> dict[str, Any]:
    """Install (or refresh) the canonical snapshot and return it for UI consumers."""
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if refresh or not isinstance(session.get(CANONICAL_SNAPSHOT_KEY), dict):
        return install_canonical_live_draft_snapshot(
            session, live if isinstance(live, dict) else {}, state_source="ui_paint"
        )
    return get_canonical_live_draft_snapshot(session, live if isinstance(live, dict) else None)


def format_canonical_diag_line(snap: dict[str, Any] | None) -> str:
    snap = snap if isinstance(snap, dict) else {}
    return (
        f"draft={snap.get('draft_id') or '—'} · rev={snap.get('revision')} · "
        f"pick={snap.get('current_pick')} · team={snap.get('team_on_clock') or '—'} · "
        f"status={snap.get('status') or '—'} · src={snap.get('state_source') or '—'}"
    )


def render_canonical_diag_line(st: Any, session: dict[str, Any], *, label: str = "") -> None:
    """Admin-only one-liner so every component can prove it shares the same snapshot."""
    try:
        from suite_workspace import can_show_developer_tools

        if not can_show_developer_tools(st=st):
            return
    except Exception:
        return
    snap = get_canonical_live_draft_snapshot(session)
    prefix = f"{label}: " if label else ""
    st.caption(f"{prefix}{format_canonical_diag_line(snap)}")
