"""Multiplayer live draft sync diagnostics — visible on all devices in dev mode."""

from __future__ import annotations

import time
from typing import Any

from live_draft_timer_logic import live_draft_current_slot, live_draft_seconds_remaining

LIVE_DRAFT_MP_DIAG_KEY = "_live_draft_mp_diag"

_MP_DIAG_FIELDS = (
    "device_role",
    "team_assignment",
    "room_code",
    "room_id",
    "local_revision",
    "remote_revision",
    "last_seen_remote_revision",
    "last_poll_started_at",
    "last_poll_finished_at",
    "last_poll_result",
    "poll_skipped_reason",
    "remote_room_status",
    "remote_current_pick_index",
    "local_current_pick_index",
    "remote_on_clock_team",
    "local_on_clock_team",
    "remote_pick_count",
    "local_pick_count",
    "last_remote_pick_player",
    "last_remote_pick_team",
    "last_remote_pick_id",
    "remote_revision_applied",
    "rerun_requested_after_apply",
    "rerun_blocked_reason",
    "last_apply_error",
    "last_poll_ts",
    "last_successful_shared_read_ts",
    "timer_deadline",
    "seconds_remaining",
    "computed_remaining",
    "timer_fragment_active",
    "timer_last_tick_ts",
    "timer_tick_count",
    "host_auto_pick_eligible",
    "last_auto_pick_attempt",
    "current_pick_index",
    "on_clock_team",
    "is_host",
    "auto_pick_allowed",
    "last_pick_source",
    "last_shared_write_ok",
    "remote_update_applied",
    "multiplayer_active",
)


def _on_clock_team(room: dict[str, Any] | None) -> str:
    if not isinstance(room, dict):
        return ""
    slot = live_draft_current_slot(room)
    return str(slot.get("Team") or "") if isinstance(slot, dict) else ""


def _pick_count(room: dict[str, Any] | None) -> int:
    if not isinstance(room, dict):
        return 0
    board = room.get("draft_board") or []
    return len(board) if isinstance(board, list) else 0


def _last_pick_info(blob: dict[str, Any] | None) -> tuple[str, str, str]:
    if not isinstance(blob, dict):
        return "", "", ""
    board = blob.get("draft_board") or []
    if not isinstance(board, list) or not board:
        return "", "", ""
    last = board[-1]
    if not isinstance(last, dict):
        return "", "", ""
    player = str(last.get("fullName") or last.get("Player") or "")
    team = str(last.get("Fantasy Team") or last.get("Team") or "")
    pid = str(last.get("playerID") or "")
    return player, team, pid


def record_poll_sync_trace(session: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """Record one poll/apply attempt with receiver-side detail."""
    diag = dict(session.get(LIVE_DRAFT_MP_DIAG_KEY) or {})
    for key, val in fields.items():
        if val is not None:
            diag[key] = val
    if fields.get("remote_revision") is not None:
        diag["last_seen_remote_revision"] = fields["remote_revision"]
    session[LIVE_DRAFT_MP_DIAG_KEY] = diag
    return diag


def record_multiplayer_sync_diagnostics(
    session: dict[str, Any],
    *,
    room: dict[str, Any] | None = None,
    local_revision: int | None = None,
    remote_revision: int | None = None,
    poll_applied: bool | None = None,
    last_shared_write_ok: bool | None = None,
    last_pick_source: str | None = None,
) -> dict[str, Any]:
    diag = dict(session.get(LIVE_DRAFT_MP_DIAG_KEY) or {})
    if local_revision is not None:
        diag["local_revision"] = local_revision
    if remote_revision is not None:
        diag["remote_revision"] = remote_revision
        diag["last_seen_remote_revision"] = remote_revision
    if poll_applied is not None:
        diag["remote_update_applied"] = poll_applied
        diag["remote_revision_applied"] = poll_applied
        if poll_applied:
            diag["last_successful_shared_read_ts"] = time.time()
    if last_shared_write_ok is not None:
        diag["last_shared_write_ok"] = last_shared_write_ok
    if last_pick_source is not None:
        diag["last_pick_source"] = last_pick_source

    diag["last_poll_ts"] = time.time()
    try:
        from draft_room_shared_state import SHARED_ROOM_META_KEY

        meta = session.get(SHARED_ROOM_META_KEY) or {}
        if local_revision is None:
            diag["local_revision"] = int(meta.get("revision") or 0)
    except ImportError:
        pass

    live = room
    if live is None:
        live = session.get("live_draft_room")
    if isinstance(live, dict):
        diag["room_id"] = str(live.get("draft_room_id") or "")
        diag["local_current_pick_index"] = live.get("current_pick_index")
        diag["local_pick_count"] = _pick_count(live)
        diag["local_on_clock_team"] = _on_clock_team(live)
        diag["timer_deadline"] = live.get("timer_deadline")
        diag["seconds_remaining"] = live_draft_seconds_remaining(live)
        diag["current_pick_index"] = live.get("current_pick_index")
        diag["on_clock_team"] = diag.get("local_on_clock_team") or ""

    try:
        from draft_room_context import resolve_shared_room_code

        diag["room_code"] = resolve_shared_room_code(session) or None
    except ImportError:
        diag["room_code"] = None

    try:
        from draft_room_context import is_multiplayer_draft_active
        from draft_room_membership import active_participant_team, is_room_host
        from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, get_shared_room_store
        from live_draft_expired_pick import _multiplayer_autopick_allowed

        mp = is_multiplayer_draft_active(session)
        diag["multiplayer_active"] = mp
        diag["team_assignment"] = str(active_participant_team(session) or "")
        if mp:
            code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
            document = get_shared_room_store().load(code) if code else None
            is_host = bool(is_room_host(session, document))
            diag["is_host"] = is_host
            diag["device_role"] = "host" if is_host else "guest"
            diag["auto_pick_allowed"] = bool(_multiplayer_autopick_allowed(session))
    except ImportError:
        pass

    try:
        from live_draft_timer_ui import LIVE_DRAFT_TIMER_DIAG_KEY

        timer_diag = session.get(LIVE_DRAFT_TIMER_DIAG_KEY) or {}
        if isinstance(timer_diag, dict):
            for key in (
                "timer_fragment_active",
                "timer_last_tick_ts",
                "timer_tick_count",
                "computed_remaining",
                "host_auto_pick_eligible",
                "last_auto_pick_attempt",
            ):
                if key in timer_diag:
                    diag[key] = timer_diag.get(key)
    except ImportError:
        pass

    session[LIVE_DRAFT_MP_DIAG_KEY] = diag
    return diag


def render_multiplayer_sync_diagnostics(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    raw = session.get(LIVE_DRAFT_MP_DIAG_KEY)
    if not isinstance(raw, dict):
        return
    with st.expander("Multiplayer sync diagnostics", expanded=developer_mode):
        for key in _MP_DIAG_FIELDS:
            val = raw.get(key)
            st.text(f"{key}: {val if val is not None and val != '' else '—'}")
