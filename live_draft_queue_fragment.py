"""Phase 6A — Live Draft queue fragment isolation.

Queue add / remove / reorder / drag update only this fragment via Streamlit
fragment-scoped reruns (and explicit ``st.rerun(scope=\"fragment\")`` when the
panel reports a mutate). Recommendation cards share the fragment so
**Add to Queue** paints the queue without rebuilding the board, rec tables,
roster tabs, or category outlook.

Draft-from-queue / Draft-from-card still escalate to a full app rerun so the
board can advance (Phase 6B).

Preserves the red sliding drag-queue UI (``streamlit_sortables`` + styles).
"""

from __future__ import annotations

from typing import Any, Callable

QUEUE_FRAGMENT_MUTATE_KEY = "_live_draft_queue_fragment_mutate"
QUEUE_FRAGMENT_PICK_KEY = "_live_draft_queue_fragment_pick"


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
    """Draft-from-queue/card must refresh board/on-clock (full app, Phase 6B)."""
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


def render_live_draft_queue_fragment(
    st: Any,
    session: dict[str, Any],
    *,
    queue_container: Any | None = None,
    render_cards: Callable[[], None] | None = None,
) -> None:
    """Fragment-scoped queue (+ optional cards) — mutates stay off full-page paint.

    ``queue_container`` — typically ``board_col`` so the queue stays left of cards.
    ``render_cards`` — optional callable that paints rec cards in the current
    Streamlit container (usually ``rec_col``). Sharing the fragment with cards
    lets Add to Queue update the queue list without rebuilding the room.
    """
    fragment = getattr(st, "fragment", None)

    def _body() -> None:
        session.pop(QUEUE_FRAGMENT_MUTATE_KEY, None)
        # Do not clear PICK_KEY here — it is set before app escalate.

        try:
            from live_draft_ux_latency import mark_ux_milestone, note_ux_pass_begin, note_ux_rerun_scope, settle_ux_action

            note_ux_pass_begin(session, st=st)
            mark_ux_milestone(session, "queue_fragment_begin", rebuild="queue_fragment", st=st)
        except ImportError:
            mark_ux_milestone = None  # type: ignore[assignment]
            note_ux_rerun_scope = None  # type: ignore[assignment]
            settle_ux_action = None  # type: ignore[assignment]

        before_q = list(session.get("draft_queue") or [])
        board_before = _board_len(session)

        target = queue_container if queue_container is not None else st
        with target:
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

        if render_cards is not None:
            try:
                if mark_ux_milestone:
                    mark_ux_milestone(
                        session, "rec_cards_paint_start", rebuild="rec_cards", st=st
                    )
                render_cards()
                if mark_ux_milestone:
                    mark_ux_milestone(
                        session, "rec_cards_paint_done", rebuild="rec_cards", st=st
                    )
            except Exception:
                # Never block queue mutations if cards fail to paint.
                try:
                    st.caption("Recommendation cards temporarily unavailable.")
                except Exception:
                    pass

        after_q = list(session.get("draft_queue") or [])
        queue_mutated = after_q != before_q or bool(panel_rerun)

        if _pick_escalation_needed(session, board_before=board_before):
            session[QUEUE_FRAGMENT_PICK_KEY] = True
            if note_ux_rerun_scope:
                note_ux_rerun_scope(session, "app", st=st)
            if settle_ux_action:
                # App escalate — settled after full script page_complete, not here.
                mark_ux_milestone(session, "escalate_app_rerun", rebuild="full_app", st=st)
            _app_rerun(st)
            return

        if queue_mutated:
            session[QUEUE_FRAGMENT_MUTATE_KEY] = True
            if note_ux_rerun_scope:
                note_ux_rerun_scope(session, "fragment", st=st)
            if settle_ux_action:
                # Explicit second fragment pass after widget-driven pass — record it.
                mark_ux_milestone(
                    session, "explicit_fragment_rerun", rebuild="queue_fragment_rerun", st=st
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
