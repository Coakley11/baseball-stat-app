"""Draft Queue survival trace — mutation → prepare → paint.

Identifies which lifecycle step clears ``draft_queue`` after Add to Queue.
Not a performance tool — correctness only.
"""

from __future__ import annotations

from typing import Any

QUEUE_SURVIVAL_LOG_KEY = "_live_draft_queue_survival_log"
QUEUE_SURVIVAL_MAX = 40


def _names(raw: Any) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def snapshot_queue_layers(session: dict[str, Any]) -> dict[str, Any]:
    """Capture the four queue representations the user asked to compare."""
    try:
        from draft_state import DRAFT_QUEUE_KEY, canonical_draft_workflow

        qkey = DRAFT_QUEUE_KEY
        canonical = canonical_draft_workflow(session) or {}
    except ImportError:
        qkey = "draft_queue"
        canonical = {}
    ds = session.get("draft_state") if isinstance(session.get("draft_state"), dict) else {}
    widget = _names(session.get(qkey))
    return {
        "session_draft_queue": widget,
        "draft_state_queue": _names(ds.get("queue")),
        "canonical_queue": _names(canonical.get("queue")),
        "widget_queue": widget,
        "session_key": qkey,
        "draft_state_dirty": bool(session.get("draft_state_dirty")),
        "queue_persist_dirty": bool(session.get("_draft_queue_persist_dirty")),
        "pending_sync": bool(session.get("_draft_workflow_pending_sync")),
        "hydrate_skipped": session.get("_live_draft_queue_hydrate_skipped"),
    }


def note_queue_survival(
    session: dict[str, Any],
    point: str,
    *,
    detail: str = "",
    st: Any | None = None,
) -> dict[str, Any]:
    """Record queue layers at A/B/C/D (or any named gate)."""
    del st  # reserved for future Streamlit logging hooks
    layers = snapshot_queue_layers(session)
    prev = None
    log = list(session.get(QUEUE_SURVIVAL_LOG_KEY) or [])
    if log and isinstance(log[-1], dict):
        prev = log[-1]
    cleared = False
    if isinstance(prev, dict):
        prev_q = list(prev.get("session_draft_queue") or [])
        now_q = list(layers.get("session_draft_queue") or [])
        cleared = bool(prev_q) and not now_q
    entry = {
        "point": str(point),
        "detail": str(detail or "")[:160],
        "cleared_since_previous": cleared,
        **layers,
    }
    log.append(entry)
    session[QUEUE_SURVIVAL_LOG_KEY] = log[-QUEUE_SURVIVAL_MAX:]
    session["_live_draft_queue_survival_latest"] = entry
    if cleared:
        session["_live_draft_queue_cleared_at"] = {
            "point": str(point),
            "detail": str(detail or "")[:160],
            "previous_point": prev.get("point") if isinstance(prev, dict) else None,
            "previous_queue": list(prev.get("session_draft_queue") or [])[:12]
            if isinstance(prev, dict)
            else [],
        }
    return entry


def render_queue_survival_panel(st: Any, session: dict[str, Any]) -> None:
    """Sidebar: A→D survival log (Developer Mode / measurement)."""
    log = [e for e in list(session.get(QUEUE_SURVIVAL_LOG_KEY) or []) if isinstance(e, dict)]
    cleared = session.get("_live_draft_queue_cleared_at")
    with st.sidebar.expander("Queue survival (Add → paint)", expanded=True):
        st.caption(
            "Points: A=after Add · B=before prepare · C=after prepare · D=before paint. "
            "Find the first point where session_draft_queue becomes []."
        )
        if isinstance(cleared, dict):
            st.error(
                f"CLEARED at **{cleared.get('point')}** "
                f"(after **{cleared.get('previous_point')}**): "
                f"{cleared.get('previous_queue')}"
            )
        if not log:
            st.info("No survival samples yet — click ⭐ Add to Queue.")
            return
        # Show last cycle (from latest A, or last 8 entries).
        recent = log[-12:]
        rows = []
        for e in recent:
            rows.append(
                {
                    "point": e.get("point"),
                    "sess": e.get("session_draft_queue"),
                    "draft_state": e.get("draft_state_queue"),
                    "canonical": e.get("canonical_queue"),
                    "dirty": e.get("draft_state_dirty"),
                    "cleared": e.get("cleared_since_previous"),
                    "detail": e.get("detail"),
                }
            )
        try:
            import pandas as pd

            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        except Exception:
            st.json(rows)
        st.json(session.get("_live_draft_queue_survival_latest") or {})
