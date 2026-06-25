"""Background shared-room polling for Live Draft Room — fragment-safe."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any


LIVE_DRAFT_POLL_DIAG_KEY = "_live_draft_poll_diag"


def _poll_suppressed_reason(session: dict[str, Any]) -> str:
    if session.get("_live_draft_manual_pick_in_flight"):
        return "manual_pick_in_flight"
    if session.get("_pending_manual_draft_pick"):
        return "pending_manual_pick"
    return ""


def record_live_poll_diagnostics(
    session: dict[str, Any],
    *,
    local_revision: int | None = None,
    remote_revision: int | None = None,
    live_poll_enabled: bool | None = None,
    live_poll_interval_ms: int | None = None,
    remote_update_detected: bool | None = None,
    remote_update_applied: bool | None = None,
    poll_suppressed_reason: str | None = None,
) -> dict[str, Any]:
    diag = dict(session.get(LIVE_DRAFT_POLL_DIAG_KEY) or {})
    fields = {
        "local_revision": local_revision,
        "remote_revision": remote_revision,
        "live_poll_enabled": live_poll_enabled,
        "live_poll_interval_ms": live_poll_interval_ms,
        "remote_update_detected": remote_update_detected,
        "remote_update_applied": remote_update_applied,
        "poll_suppressed_reason": poll_suppressed_reason,
    }
    for key, val in fields.items():
        if val is not None:
            diag[key] = val
    session[LIVE_DRAFT_POLL_DIAG_KEY] = diag
    try:
        from draft_commit_diagnostics import record_draft_commit_diagnostics

        record_draft_commit_diagnostics(session, **{k: v for k, v in fields.items() if v is not None})
    except ImportError:
        pass
    return diag


def render_live_poll_diagnostics(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    raw = session.get(LIVE_DRAFT_POLL_DIAG_KEY)
    if not isinstance(raw, dict):
        return
    with st.expander("Live poll diagnostics", expanded=developer_mode):
        for key in (
            "local_revision",
            "remote_revision",
            "live_poll_enabled",
            "live_poll_interval_ms",
            "remote_update_detected",
            "remote_update_applied",
            "poll_suppressed_reason",
        ):
            val = raw.get(key)
            st.text(f"{key}: {val if val is not None and val != '' else '—'}")


def _local_revision(session: dict[str, Any]) -> int:
    try:
        from draft_room_shared_state import SHARED_ROOM_META_KEY

        return int((session.get(SHARED_ROOM_META_KEY) or {}).get("revision") or 0)
    except ImportError:
        return 0


def _run_shared_poll(session: dict[str, Any]) -> bool:
    try:
        from draft_room_context import poll_shared_draft_room, reset_shared_draft_sync_gate
    except ImportError:
        return False
    reset_shared_draft_sync_gate(session)
    return bool(poll_shared_draft_room(session))


def render_live_draft_poll_fragment(st: Any, session: dict[str, Any]) -> None:
    """Poll shared room on an interval and rerun when a remote pick lands."""
    try:
        from draft_room_context import is_multiplayer_draft_active
        from suite_egress_policy import shared_draft_poll_interval_sec
    except ImportError:
        return
    if not is_multiplayer_draft_active(session):
        record_live_poll_diagnostics(session, live_poll_enabled=False)
        return

    interval_sec = float(shared_draft_poll_interval_sec(session))
    record_live_poll_diagnostics(
        session,
        live_poll_enabled=True,
        live_poll_interval_ms=int(interval_sec * 1000),
        local_revision=_local_revision(session),
    )

    try:
        fragment = st.fragment
    except AttributeError:
        suppressed = _poll_suppressed_reason(session)
        if suppressed:
            record_live_poll_diagnostics(session, poll_suppressed_reason=suppressed)
            return
        changed = _run_shared_poll(session)
        record_live_poll_diagnostics(
            session,
            local_revision=_local_revision(session),
            remote_update_detected=changed,
            remote_update_applied=changed,
        )
        if changed:
            _rerun_after_poll(st, session)
        return

    @fragment(run_every=timedelta(seconds=interval_sec))
    def _poll_tick() -> None:
        local_rev = _local_revision(session)
        suppressed = _poll_suppressed_reason(session)
        if suppressed:
            record_live_poll_diagnostics(
                session,
                local_revision=local_rev,
                poll_suppressed_reason=suppressed,
            )
            return
        changed = _run_shared_poll(session)
        remote_rev = _local_revision(session)
        record_live_poll_diagnostics(
            session,
            local_revision=local_rev,
            remote_revision=remote_rev,
            remote_update_detected=changed or remote_rev > local_rev,
            remote_update_applied=changed,
            poll_suppressed_reason="",
        )
        if changed:
            session.pop("_live_draft_rec_cache", None)
            _rerun_after_poll(st, session)

    _poll_tick()


def _rerun_after_poll(st: Any, session: dict[str, Any]) -> None:
    try:
        from live_draft_safe_mode import reconcile_live_draft_room, request_live_draft_rerun

        room = session.get("live_draft_room")
        if isinstance(room, dict):
            reconcile_live_draft_room(session, room)
        request_live_draft_rerun(st, session, "poll_fragment", room=room)
    except ImportError:
        st.rerun()
