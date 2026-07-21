"""Canonical Live Draft room snapshot — one source for all UI components in a render cycle.

Sidebar, On the Clock banner, timer, board, queue, and recommendations must read the
same pick index, team, revision, and deadline from this snapshot after every commit.
"""

from __future__ import annotations

import time
from typing import Any

CANONICAL_SNAPSHOT_KEY = "_live_draft_canonical_snapshot"
PAINT_SNAPSHOT_KEY = "_live_draft_paint_snapshot"
PAINT_GENERATION_KEY = "_live_draft_paint_generation"
CANONICAL_TRANSITION_LOG_KEY = "_live_draft_pick_transition_log"
ACTION_TIMING_KEY = "_live_draft_action_timing_log"
MAX_TRANSITION_LOG = 40
MAX_ACTION_TIMING = 60


def _revision(room: dict[str, Any] | None) -> int:
    if not isinstance(room, dict):
        return 0
    try:
        meta = room.get("meta") if isinstance(room.get("meta"), dict) else {}
        sync = meta.get("sync") if isinstance(meta.get("sync"), dict) else {}
        return int(sync.get("revision") or room.get("draft_revision") or room.get("revision") or 0)
    except (TypeError, ValueError):
        return 0


def _draft_id(room: dict[str, Any] | None) -> str:
    if not isinstance(room, dict):
        return ""
    return str(
        room.get("draft_room_id") or room.get("room_id") or room.get("draft_id") or ""
    ).strip()


def align_room_pick_index(room: dict[str, Any]) -> tuple[int, int]:
    """Repair index when board length has advanced ahead of current_pick_index."""
    board = list(room.get("draft_board") or [])
    board_len = len(board)
    idx = int(room.get("current_pick_index") or 0)
    if board_len > idx:
        room["current_pick_index"] = board_len
        idx = board_len
    return idx, board_len


def build_canonical_live_draft_snapshot(
    room: dict[str, Any] | None,
    *,
    session: dict[str, Any] | None = None,
    state_source: str = "live_draft_room",
) -> dict[str, Any]:
    """Build the authoritative Solo/Shared display snapshot from the runtime room."""
    room = room if isinstance(room, dict) else {}
    pick_index, board_len = align_room_pick_index(room)
    status = str(room.get("status") or "").strip()
    team = ""
    pick_number = None
    round_number = None
    deadline = None
    timer_remaining: int | None = None
    try:
        from live_draft_timer_logic import (
            live_draft_current_slot,
            live_draft_seconds_remaining,
            live_draft_timer_deadline,
            resolve_live_draft_on_clock_slot,
        )

        slot = resolve_live_draft_on_clock_slot(room) or live_draft_current_slot(room)
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
        if status == "in_progress":
            timer_remaining = int(live_draft_seconds_remaining(room))
        elif status == "paused":
            timer_remaining = int(room.get("paused_remaining_seconds") or 0)
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
    rev = _revision(room)
    draft_id = _draft_id(room)
    deadline_s = f"{float(deadline):.3f}" if deadline is not None else "none"
    snap = {
        "draft_id": draft_id,
        "revision": rev,
        "status": status,
        "current_pick_index": pick_index,
        "current_pick": pick_number if pick_number is not None else (pick_index + 1 if status == "in_progress" else None),
        "round": round_number,
        "team_on_clock": team,
        "on_clock_team": team,
        "timer_deadline": float(deadline) if deadline is not None else None,
        "timer_remaining": timer_remaining,
        "board_size": board_len,
        "drafted_player_ids": drafted_ids,
        "drafted_count": len(drafted_ids),
        "state_source": str(state_source or "live_draft_room"),
        "paint_token": f"{draft_id}|r{rev}|i{pick_index}|b{board_len}|t{team}|d{deadline_s}",
    }
    if isinstance(session, dict):
        session[CANONICAL_SNAPSHOT_KEY] = snap
    return snap


def begin_live_draft_paint(
    session: dict[str, Any],
    room: dict[str, Any] | None,
    *,
    state_source: str = "live_draft_room_page",
) -> dict[str, Any]:
    """Install one immutable snapshot for the current full-page render pass."""
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if isinstance(live, dict):
        try:
            from live_draft_safe_mode import reconcile_live_draft_room

            live = reconcile_live_draft_room(session, live).room
        except ImportError:
            try:
                from live_draft_state import repair_stale_live_draft_progress

                live = repair_stale_live_draft_progress(dict(live))
            except ImportError:
                pass
        try:
            from live_draft_state import LIVE_DRAFT_ROOM_KEY

            session[LIVE_DRAFT_ROOM_KEY] = live
        except ImportError:
            session["live_draft_room"] = live
    gen = int(session.get(PAINT_GENERATION_KEY) or 0) + 1
    snap = build_canonical_live_draft_snapshot(live if isinstance(live, dict) else {}, session=session, state_source=state_source)
    frozen = dict(snap)
    frozen["paint_generation"] = gen
    frozen["snapshot_id"] = gen
    session[PAINT_SNAPSHOT_KEY] = frozen
    session[PAINT_GENERATION_KEY] = gen
    session[CANONICAL_SNAPSHOT_KEY] = frozen
    return frozen


def get_live_draft_paint_snapshot(session: dict[str, Any] | None) -> dict[str, Any]:
    """Return the frozen per-render snapshot when present."""
    session = session if isinstance(session, dict) else {}
    paint = session.get(PAINT_SNAPSHOT_KEY)
    if isinstance(paint, dict) and paint:
        return dict(paint)
    return get_canonical_live_draft_snapshot(session, refresh=True)


def invalidate_live_draft_paint(session: dict[str, Any]) -> None:
    session.pop(PAINT_SNAPSHOT_KEY, None)


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
    if not refresh:
        paint = session.get(PAINT_SNAPSHOT_KEY)
        if isinstance(paint, dict) and paint:
            return dict(paint)
    existing = session.get(CANONICAL_SNAPSHOT_KEY)
    if refresh or not isinstance(existing, dict) or not existing:
        live = room
        if not isinstance(live, dict):
            live = session.get("live_draft_room") if isinstance(session.get("live_draft_room"), dict) else {}
        return install_canonical_live_draft_snapshot(session, live, state_source="refresh")
    return dict(existing)


def apply_canonical_to_slot_views(
    session: dict[str, Any],
    room: dict[str, Any] | None = None,
    *,
    refresh: bool = True,
) -> dict[str, Any]:
    """Return the paint snapshot for UI consumers — never rebuild mid-pass."""
    if not refresh:
        paint = session.get(PAINT_SNAPSHOT_KEY)
        if isinstance(paint, dict) and paint:
            return dict(paint)
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if isinstance(live, dict):
        align_room_pick_index(live)
    snap = install_canonical_live_draft_snapshot(
        session, live if isinstance(live, dict) else {}, state_source="ui_paint"
    )
    session[CANONICAL_SNAPSHOT_KEY] = snap
    return dict(snap)


def context_fields_from_snapshot(
    session: dict[str, Any],
    snap: dict[str, Any] | None,
    *,
    room: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map frozen snapshot → draft_action_context pick/team fields."""
    snap = snap if isinstance(snap, dict) else {}
    room = room if isinstance(room, dict) else session.get("live_draft_room")
    your_team = ""
    if isinstance(room, dict):
        cfg = dict(room.get("config") or {})
        your_team = str(cfg.get("user_team") or cfg.get("your_team") or session.get("room_your_team") or "").strip()
    on_clock = str(snap.get("team_on_clock") or snap.get("on_clock_team") or "").strip()
    return {
        "current_pick": snap.get("current_pick"),
        "current_pick_index": snap.get("current_pick_index"),
        "on_clock_team": on_clock,
        "round": snap.get("round"),
        "revision": snap.get("revision"),
        "draft_status": snap.get("status") or "",
        "draft_complete": str(snap.get("status") or "") == "complete",
        "your_team": your_team,
        "is_your_pick": bool(your_team and on_clock and your_team == on_clock),
        "paint_token": snap.get("paint_token"),
        "snapshot_id": snap.get("snapshot_id"),
    }


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


def note_action_timing(session: dict[str, Any], event: str, **fields: Any) -> None:
    """Admin-only action latency trail (click → paint)."""
    row = {"event": str(event or ""), "ts": time.time(), **{k: v for k, v in fields.items() if v is not None}}
    log = list(session.get(ACTION_TIMING_KEY) or [])
    log.append(row)
    session[ACTION_TIMING_KEY] = log[-MAX_ACTION_TIMING:]


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


def pick_commit_confirmed(
    room: dict[str, Any] | None,
    *,
    pick_index_before: int,
    board_size_before: int,
) -> bool:
    """True when the room reflects a committed pick that started at pick_index_before/board_size_before."""
    if not isinstance(room, dict):
        return False
    idx_before = int(pick_index_before)
    board_before = int(board_size_before)
    board_now = len(room.get("draft_board") or [])
    idx_now = int(room.get("current_pick_index") or 0)
    return board_now >= board_before + 1 and idx_now >= idx_before + 1


def idempotency_key_committed(room: dict[str, Any] | None, claim_key: str) -> bool:
    """Parse an auto-pick idempotency key and verify the room actually advanced."""
    if not claim_key or not isinstance(room, dict):
        return False
    try:
        pick_part = claim_key.split("|pick=", 1)[1]
        pick_idx = int(pick_part.split("|", 1)[0])
        board_part = claim_key.split("|board=", 1)[1]
        board_at = int(board_part)
    except (IndexError, ValueError):
        return False
    return pick_commit_confirmed(room, pick_index_before=pick_idx, board_size_before=board_at)


def clear_stale_auto_pick_idempotency(session: dict[str, Any], room: dict[str, Any]) -> None:
    """Drop idempotency tokens that no longer match committed board state."""
    for key_name in ("_live_draft_last_auto_pick_idempotency_key", "_live_draft_in_flight_auto_pick_key"):
        token = str(session.get(key_name) or "")
        if token and not idempotency_key_committed(room, token):
            session.pop(key_name, None)
    room_last = str(room.get("_last_auto_pick_idempotency_key") or "")
    if room_last and not idempotency_key_committed(room, room_last):
        room.pop("_last_auto_pick_idempotency_key", None)


def format_canonical_diag_line(snap: dict[str, Any] | None) -> str:
    snap = snap if isinstance(snap, dict) else {}
    return (
        f"draft={snap.get('draft_id') or '—'} · rev={snap.get('revision')} · "
        f"pick={snap.get('current_pick')} · idx={snap.get('current_pick_index')} · "
        f"team={snap.get('team_on_clock') or '—'} · "
        f"status={snap.get('status') or '—'} · tok={snap.get('paint_token') or snap.get('snapshot_id') or '—'}"
    )


def render_canonical_diag_line(st: Any, session: dict[str, Any], *, label: str = "") -> None:
    """Admin-only one-liner so every component can prove it shares the same snapshot."""
    try:
        from suite_workspace import can_show_developer_tools

        if not can_show_developer_tools(st=st):
            return
    except Exception:
        return
    snap = get_live_draft_paint_snapshot(session)
    prefix = f"{label}: " if label else ""
    st.caption(f"{prefix}{format_canonical_diag_line(snap)}")
