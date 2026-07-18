"""Live Draft full-page render checkpoints (Developer Mode diagnostics)."""

from __future__ import annotations

from typing import Any

RENDER_CHECKPOINT_KEY = "_live_draft_render_checkpoints"
RENDER_ABORT_KEY = "_live_draft_render_abort"


def reset_live_draft_render_checkpoints(session: dict[str, Any]) -> None:
    session[RENDER_CHECKPOINT_KEY] = {
        "order": [],
        "sections": {},
        "selected_page": str(session.get("active_page") or ""),
        "lifecycle": "",
        "page_generation": session.get("_active_page_generation"),
        "live_draft_epoch": session.get("_live_draft_page_fragment_epoch"),
        "room_id": "",
        "room_code": str(session.get("active_shared_draft_room_code") or ""),
        "draft_id": "",
    }
    session.pop(RENDER_ABORT_KEY, None)


def note_live_draft_render_checkpoint(
    session: dict[str, Any],
    section: str,
    *,
    phase: str = "completed",
    detail: str = "",
    room: dict[str, Any] | None = None,
) -> None:
    blob = session.get(RENDER_CHECKPOINT_KEY)
    if not isinstance(blob, dict):
        reset_live_draft_render_checkpoints(session)
        blob = session[RENDER_CHECKPOINT_KEY]
    name = str(section or "").strip() or "unknown"
    entry = {
        "phase": str(phase),
        "detail": str(detail or ""),
    }
    sections = blob.setdefault("sections", {})
    if not isinstance(sections, dict):
        sections = {}
        blob["sections"] = sections
    sections[f"{name}:{phase}"] = entry
    order = blob.setdefault("order", [])
    if isinstance(order, list):
        order.append(f"{name}:{phase}")
    live = room if isinstance(room, dict) else session.get("live_draft_room")
    if isinstance(live, dict):
        blob["room_id"] = str(live.get("room_id") or live.get("draft_room_id") or blob.get("room_id") or "")
        blob["draft_id"] = str(live.get("draft_room_id") or live.get("draft_id") or blob.get("draft_id") or "")
    blob["room_code"] = str(session.get("active_shared_draft_room_code") or blob.get("room_code") or "")
    blob["page_generation"] = session.get("_active_page_generation")
    blob["live_draft_epoch"] = session.get("_live_draft_page_fragment_epoch")
    try:
        from live_draft_completion import resolve_live_draft_lifecycle

        blob["lifecycle"] = resolve_live_draft_lifecycle(session)
    except ImportError:
        pass
    session[RENDER_CHECKPOINT_KEY] = blob


def mark_live_draft_render_abort(
    session: dict[str, Any],
    *,
    where: str,
    reason: str,
) -> None:
    session[RENDER_ABORT_KEY] = {
        "where": str(where),
        "reason": str(reason),
        "last_checkpoint": (session.get(RENDER_CHECKPOINT_KEY) or {}).get("order", [])[-1:]
        if isinstance(session.get(RENDER_CHECKPOINT_KEY), dict)
        else [],
    }
    note_live_draft_render_checkpoint(session, where, phase="aborted", detail=reason)


def render_live_draft_checkpoint_panel(st: Any, session: dict[str, Any]) -> None:
    """Developer Mode: show which section last completed when the page truncates."""
    try:
        from suite_workspace import developer_mode_checkbox_enabled

        if not developer_mode_checkbox_enabled(st=st):
            return
    except ImportError:
        if not (session.get("app_developer_mode") or session.get("_suite_developer_mode_user")):
            return
    blob = session.get(RENDER_CHECKPOINT_KEY) if isinstance(session.get(RENDER_CHECKPOINT_KEY), dict) else {}
    abort = session.get(RENDER_ABORT_KEY) if isinstance(session.get(RENDER_ABORT_KEY), dict) else {}
    order = list(blob.get("order") or [])
    with st.expander("Live Draft render checkpoints (Developer Mode)", expanded=bool(abort)):
        st.caption(
            f"page=`{blob.get('selected_page')}` · lifecycle=`{blob.get('lifecycle')}` · "
            f"gen=`{blob.get('page_generation')}` · epoch=`{blob.get('live_draft_epoch')}`"
        )
        st.caption(
            f"room=`{blob.get('room_code')}` · draft=`{blob.get('draft_id')}` · "
            f"room_id=`{blob.get('room_id')}`"
        )
        try:
            from shared_live_draft_snapshot import SHARED_ROOM_SNAPSHOT_KEY

            snap = session.get(SHARED_ROOM_SNAPSHOT_KEY) if isinstance(session.get(SHARED_ROOM_SNAPSHOT_KEY), dict) else {}
            st.caption(
                f"snap_rev=`{snap.get('revision')}` · on_clock=`{snap.get('on_clock_team')}` · "
                f"pick=`{snap.get('current_pick')}` · gen=`{snap.get('room_generation')}` · "
                f"deadline=`{snap.get('timer_deadline_utc')}` · paused=`{snap.get('timer_paused')}`"
            )
        except ImportError:
            pass
        if abort:
            st.error(
                f"Render aborted at **{abort.get('where')}**: {abort.get('reason')} "
                f"(last checkpoint: {abort.get('last_checkpoint')})"
            )
        if order:
            st.code("\n".join(order[-40:]))
        else:
            st.caption("No checkpoints recorded this pass.")
