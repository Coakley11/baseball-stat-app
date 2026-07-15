"""Live Draft queue fragment — queue UI only (Phase 6A corrected).

CRITICAL: The fragment must be declared **in the same Streamlit container** that
displays the queue. Writing the queue into ``board_col`` from a fragment mounted
under ``rec_col`` does not update on fragment-scoped reruns — Add/Remove appear
to no-op even though ``draft_queue`` mutates in session.

Rec cards stay **outside** this fragment. Add-from-card uses a full-app paint
(widget outside fragment), which remounts this fragment with the new queue.
Remove/reorder stay fragment-scoped inside ``board_col``.
"""

from __future__ import annotations

from typing import Any

QUEUE_FRAGMENT_MUTATE_KEY = "_live_draft_queue_fragment_mutate"
QUEUE_FRAGMENT_PICK_KEY = "_live_draft_queue_fragment_pick"
QUEUE_ADD_DIAG_KEY = "_live_draft_queue_add_diag"


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
    }


def render_live_draft_queue_fragment(st: Any, session: dict[str, Any]) -> None:
    """Fragment-scoped Draft Queue — call from inside ``board_col`` only."""
    fragment = getattr(st, "fragment", None)

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
            mark_ux_milestone(session, "queue_fragment_begin", rebuild="queue_fragment", st=st)
        except ImportError:
            mark_ux_milestone = None  # type: ignore[assignment]
            note_ux_rerun_scope = None  # type: ignore[assignment]
            settle_ux_action = None  # type: ignore[assignment]

        before_q = list(session.get("draft_queue") or [])
        board_before = _board_len(session)

        from draft_ui import render_draft_queue_panel

        if mark_ux_milestone:
            mark_ux_milestone(session, "queue_paint_start", rebuild="queue_panel", st=st)
        # Render into the fragment's own container (must be board_col at call site).
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

        after_q = list(session.get("draft_queue") or [])
        # Sortable wipe is guarded inside render_draft_queue_panel (drag path only).
        # Do not restore here — a Remove that empties the queue is a valid mutate.

        queue_mutated = after_q != before_q or bool(panel_rerun)

        if _pick_escalation_needed(session, board_before=board_before):
            session[QUEUE_FRAGMENT_PICK_KEY] = True
            if note_ux_rerun_scope:
                note_ux_rerun_scope(session, "app", st=st)
            if mark_ux_milestone:
                mark_ux_milestone(session, "escalate_app_rerun", rebuild="full_app", st=st)
            _app_rerun(st)
            return

        if queue_mutated:
            # Widget interaction already re-ran this fragment once. An extra
            # st.rerun(scope="fragment") doubles paint — only use when the first
            # pass still shows a stale empty panel while session has names.
            painted = [str(x).strip() for x in (session.get("draft_queue") or []) if str(x).strip()]
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
            settle_ux_action(session, where="fragment_settled", st=st)

    if not callable(fragment):
        _body()
        if session.get(QUEUE_FRAGMENT_MUTATE_KEY) or session.get(QUEUE_FRAGMENT_PICK_KEY):
            try:
                from live_draft_safe_mode import request_live_draft_rerun

                request_live_draft_rerun(
                    st,
                    session,
                    "live_draft_queue",
                    room=session.get("live_draft_room"),
                )
            except ImportError:
                st.rerun()
        return

    @fragment
    def _queue_fragment_body() -> None:
        _body()

    _queue_fragment_body()
