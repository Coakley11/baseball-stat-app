"""Live Draft queue panel mount (Phase 6A corrected — fragment disabled).

Phase 6A originally used ``@st.fragment``. That path produced a session/UI
mismatch: Add mutated ``draft_queue`` (diagnostics green) while the visible
Draft Queue stayed on a stale Empty caption. Until fragment paint is proven,
the queue renders on the full-app path inside ``board_col``.
"""

from __future__ import annotations

from typing import Any

QUEUE_FRAGMENT_MUTATE_KEY = "_live_draft_queue_fragment_mutate"
QUEUE_FRAGMENT_PICK_KEY = "_live_draft_queue_fragment_pick"
QUEUE_ADD_DIAG_KEY = "_live_draft_queue_add_diag"
QUEUE_PAINT_DIAG_KEY = "_live_draft_queue_paint_diag"

# Keep False until Add→visible-queue is verified on Cloud. Fragment isolation
# can return after that gate.
USE_QUEUE_FRAGMENT = False


def _fragment_rerun(st: Any) -> None:
    try:
        st.rerun(scope="fragment")
    except TypeError:
        st.rerun()


def _app_rerun(st: Any) -> None:
    try:
        st.rerun(scope="app")
    except TypeError:
        st.rerun()


def _board_len(session: dict[str, Any]) -> int:
    try:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        room = session.get(LIVE_DRAFT_ROOM_KEY)
    except ImportError:
        room = session.get("live_draft_room")
    if isinstance(room, dict):
        return len(room.get("draft_board") or [])
    return 0


def _pick_escalation_needed(session: dict[str, Any], *, board_before: int) -> bool:
    if board_before < _board_len(session):
        return True
    if session.get("_pending_manual_draft_pick"):
        return True
    if session.get("_live_draft_manual_pick_in_flight"):
        return True
    try:
        from live_draft_pick_persist import PICK_PERSIST_DIRTY_KEY

        if session.get(PICK_PERSIST_DIRTY_KEY):
            return True
    except ImportError:
        pass
    return bool(session.get(QUEUE_FRAGMENT_PICK_KEY))


def _queue_names(session: dict[str, Any]) -> list[str]:
    try:
        from draft_state import DRAFT_QUEUE_KEY

        key = DRAFT_QUEUE_KEY
    except ImportError:
        key = "draft_queue"
    return [str(x).strip() for x in (session.get(key) or []) if str(x).strip()]


def record_queue_add_diag(
    session: dict[str, Any],
    *,
    name: str,
    before: list[str],
    after: list[str],
    added: bool,
) -> None:
    """Dev diagnostics: prove Add mutated session draft_queue."""
    session[QUEUE_ADD_DIAG_KEY] = {
        "name": str(name or ""),
        "before_len": len(before),
        "after_len": len(after),
        "before": list(before)[:12],
        "after": list(after)[:12],
        "added": bool(added),
        "mutated": list(before) != list(after),
        "session_key": "draft_queue",
    }


def record_queue_paint_diag(
    session: dict[str, Any],
    *,
    stage: str,
    queue: list[str],
    extra: dict[str, Any] | None = None,
) -> None:
    """Dev diagnostics: session queue at each paint stage (source of truth for UI)."""
    entry = dict(session.get(QUEUE_PAINT_DIAG_KEY) or {})
    if not isinstance(entry, dict):
        entry = {}
    snap = {
        "len": len(queue),
        "names": list(queue)[:12],
    }
    if extra:
        snap.update(extra)
    entry[str(stage)] = snap
    entry["session_key"] = "draft_queue"
    entry["last_stage"] = str(stage)
    entry["mismatch"] = bool(
        (entry.get("before_panel") or {}).get("len")
        != (entry.get("inside_panel") or {}).get("len")
    ) if entry.get("before_panel") and entry.get("inside_panel") else False
    session[QUEUE_PAINT_DIAG_KEY] = entry


def render_live_draft_queue_fragment(st: Any, session: dict[str, Any]) -> None:
    """Draft Queue mount — call from inside ``board_col`` only."""
    try:
        from live_draft_termination import live_draft_fragments_suppressed

        if live_draft_fragments_suppressed(session):
            return
    except ImportError:
        pass

    def _body() -> None:
        session.pop(QUEUE_FRAGMENT_MUTATE_KEY, None)

        try:
            from live_draft_ux_latency import (
                mark_ux_milestone,
                note_ux_pass_begin,
                note_ux_rerun_scope,
                settle_ux_action,
            )

            note_ux_pass_begin(session, st=st)
            mark_ux_milestone(session, "queue_mount_begin", rebuild="queue_panel", st=st)
        except ImportError:
            mark_ux_milestone = None  # type: ignore[assignment]
            note_ux_rerun_scope = None  # type: ignore[assignment]
            settle_ux_action = None  # type: ignore[assignment]

        before_q = _queue_names(session)
        board_before = _board_len(session)
        try:
            from live_draft_queue_survival import note_queue_survival

            note_queue_survival(
                session,
                "D",
                detail="immediately before queue paint",
                st=st,
            )
        except ImportError:
            pass
        record_queue_paint_diag(
            session,
            stage="before_panel",
            queue=before_q,
            extra={
                "hydrate_skipped": session.get("_live_draft_queue_hydrate_skipped"),
                "blob_restore_skipped": session.get("_live_draft_queue_blob_restore_skipped"),
                "draft_state_queue_len": len(
                    ((session.get("draft_state") or {}) if isinstance(session.get("draft_state"), dict) else {}).get(
                        "queue"
                    )
                    or []
                ),
            },
        )

        from draft_ui import render_draft_queue_panel

        if mark_ux_milestone:
            mark_ux_milestone(session, "queue_paint_start", rebuild="queue_panel", st=st)
        panel_rerun = render_draft_queue_panel(
            st,
            session,
            key_prefix="live_queue",
            max_rows=20,
            show_subheader=True,
            compact=False,
        )
        if mark_ux_milestone:
            mark_ux_milestone(session, "queue_paint_done", rebuild="queue_panel", st=st)

        after_q = _queue_names(session)
        record_queue_paint_diag(
            session,
            stage="after_panel",
            queue=after_q,
            extra={"panel_rerun": bool(panel_rerun)},
        )

        queue_mutated = after_q != before_q or bool(panel_rerun)

        if _pick_escalation_needed(session, board_before=board_before):
            session[QUEUE_FRAGMENT_PICK_KEY] = True
            if note_ux_rerun_scope:
                note_ux_rerun_scope(session, "app", st=st)
            if mark_ux_milestone:
                mark_ux_milestone(session, "escalate_app_rerun", rebuild="full_app", st=st)
            _app_rerun(st)
            return

        if USE_QUEUE_FRAGMENT and queue_mutated:
            painted = _queue_names(session)
            if painted and not before_q and panel_rerun:
                session[QUEUE_FRAGMENT_MUTATE_KEY] = True
                if note_ux_rerun_scope:
                    note_ux_rerun_scope(session, "fragment", st=st)
                if mark_ux_milestone:
                    mark_ux_milestone(
                        session,
                        "explicit_fragment_rerun",
                        rebuild="queue_fragment_rerun",
                        st=st,
                    )
                _fragment_rerun(st)
                return

        if settle_ux_action:
            settle_ux_action(session, where="queue_settled", st=st)

    fragment = getattr(st, "fragment", None) if USE_QUEUE_FRAGMENT else None
    if not callable(fragment):
        # Non-fragment path: _body() already calls st.rerun when escalating a pick.
        _body()
        return

    @fragment
    def _queue_fragment_body() -> None:
        _body()

    _queue_fragment_body()
