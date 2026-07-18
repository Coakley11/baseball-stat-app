"""Background shared-room polling for Live Draft Room — fragment-safe."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any


LIVE_DRAFT_POLL_DIAG_KEY = "_live_draft_poll_diag"


def _poll_suppressed_reason(session: dict[str, Any]) -> str:
    try:
        from live_draft_termination import live_draft_fragments_suppressed

        if live_draft_fragments_suppressed(session):
            return "fragments_suppressed_or_deleting"
    except ImportError:
        pass
    try:
        from live_draft_completion import LIFECYCLE_SETUP, resolve_live_draft_lifecycle

        if resolve_live_draft_lifecycle(session) == LIFECYCLE_SETUP:
            return "lifecycle_setup"
    except ImportError:
        pass
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
    if not developer_mode:
        return
    try:
        from page_diagnostics import suppress_inline_diagnostics

        if suppress_inline_diagnostics(developer_mode):
            return
    except ImportError:
        pass
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
    """Single lightweight shared-room poller — head first; full doc only on revision change."""
    suppressed = _poll_suppressed_reason(session)
    if suppressed:
        session.pop("_live_draft_poll_fragment_active", None)
        record_live_poll_diagnostics(
            session, live_poll_enabled=False, poll_suppressed_reason=suppressed
        )
        return
    # Suppress the duplicate page-level poll while this fragment owns the loop.
    session["_live_draft_poll_fragment_active"] = True
    try:
        from live_draft_start_progress import should_skip_live_draft_poll

        if should_skip_live_draft_poll(session):
            record_live_poll_diagnostics(session, live_poll_enabled=False, poll_suppressed_reason="draft_start_in_flight")
            return
    except ImportError:
        pass
    try:
        from draft_room_context import is_multiplayer_draft_active
        from suite_egress_policy import shared_draft_poll_interval_sec
    except ImportError:
        return
    if not is_multiplayer_draft_active(session):
        record_live_poll_diagnostics(session, live_poll_enabled=False)
        return

    # Prefer ~1s during active drafts so guests converge within the 1–2s budget.
    interval_sec = min(1.0, float(shared_draft_poll_interval_sec(session)))
    try:
        room = session.get("live_draft_room")
        if isinstance(room, dict) and str(room.get("status") or "") == "in_progress":
            dl = room.get("timer_deadline")
            if dl is not None and float(dl) <= time.time() + 2.0:
                interval_sec = 0.5
    except Exception:
        pass
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
        try:
            from live_draft_mp_diagnostics import record_multiplayer_sync_diagnostics

            record_multiplayer_sync_diagnostics(
                session,
                local_revision=local_rev if not changed else remote_rev,
                remote_revision=remote_rev,
                poll_applied=changed,
            )
        except ImportError:
            pass
        record_live_poll_diagnostics(
            session,
            local_revision=local_rev,
            remote_revision=remote_rev,
            remote_update_detected=changed or remote_rev > local_rev,
            remote_update_applied=changed,
            poll_suppressed_reason="",
        )
        if changed:
            # Do not wipe recommendation caches here — board/timer paint first.
            session["_live_draft_recs_pending_after_pick"] = True
            try:
                from live_draft_render_trace import ldr_rerun

                ldr_rerun(session, "poll_fragment", reason="fragment_poll_changed", st=st)
            except ImportError:
                pass
            _rerun_after_poll(st, session)

    _poll_tick()


def _rerun_after_poll(st: Any, session: dict[str, Any]) -> None:
    try:
        from live_draft_safe_mode import request_poll_apply_rerun

        request_poll_apply_rerun(st, session, room=session.get("live_draft_room"))
    except ImportError:
        st.rerun()
