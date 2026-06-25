"""Multiplayer live draft sync diagnostics — visible on all devices in dev mode."""

from __future__ import annotations

import time
from typing import Any

from live_draft_timer_logic import live_draft_current_slot, live_draft_seconds_remaining

LIVE_DRAFT_MP_DIAG_KEY = "_live_draft_mp_diag"


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
    if poll_applied is not None:
        diag["remote_update_applied"] = poll_applied
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
        diag["timer_deadline"] = live.get("timer_deadline")
        diag["seconds_remaining"] = live_draft_seconds_remaining(live)
        diag["current_pick_index"] = live.get("current_pick_index")
        slot = live_draft_current_slot(live)
        diag["on_clock_team"] = str(slot.get("Team") or "") if isinstance(slot, dict) else ""

    try:
        from draft_room_context import is_multiplayer_draft_active
        from draft_room_membership import is_room_host
        from draft_room_shared_state import ACTIVE_SHARED_ROOM_CODE_KEY, get_shared_room_store
        from live_draft_expired_pick import _multiplayer_autopick_allowed

        mp = is_multiplayer_draft_active(session)
        diag["multiplayer_active"] = mp
        if mp:
            code = str(session.get(ACTIVE_SHARED_ROOM_CODE_KEY) or "").strip().upper()
            document = get_shared_room_store().load(code) if code else None
            diag["is_host"] = bool(is_room_host(session, document))
            diag["auto_pick_allowed"] = bool(_multiplayer_autopick_allowed(session))
    except ImportError:
        pass

    session[LIVE_DRAFT_MP_DIAG_KEY] = diag
    return diag


def render_multiplayer_sync_diagnostics(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    raw = session.get(LIVE_DRAFT_MP_DIAG_KEY)
    if not isinstance(raw, dict):
        return
    with st.expander("Multiplayer sync diagnostics", expanded=developer_mode):
        for key in (
            "room_id",
            "local_revision",
            "remote_revision",
            "last_poll_ts",
            "last_successful_shared_read_ts",
            "timer_deadline",
            "seconds_remaining",
            "current_pick_index",
            "on_clock_team",
            "is_host",
            "auto_pick_allowed",
            "last_pick_source",
            "last_shared_write_ok",
            "remote_update_applied",
            "multiplayer_active",
        ):
            val = raw.get(key)
            st.text(f"{key}: {val if val is not None and val != '' else '—'}")
