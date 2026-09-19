"""Paint the Live Draft nav-sidebar queue mirror from canonical session layers."""

from __future__ import annotations

from typing import Any


def resolve_sidebar_queue_names(session: dict[str, Any]) -> tuple[list[str], str]:
    """Return (names, source) from the strongest canonical queue layer."""
    try:
        from draft_state import DRAFT_QUEUE_KEY
        from draft_ui import _resolve_visible_draft_queue

        names, src = _resolve_visible_draft_queue(session, qkey=DRAFT_QUEUE_KEY)
        if names:
            return list(names), str(src)
    except Exception:
        pass
    for key in (
        "draft_queue",
        "_live_draft_queue_last_good",
        "_live_draft_queue_sidebar_mirror",
    ):
        raw = session.get(key) or []
        names = [str(x).strip() for x in raw if str(x).strip()]
        if names:
            return names, key
    ds = session.get("draft_state")
    if isinstance(ds, dict):
        names = [str(x).strip() for x in (ds.get("queue") or []) if str(x).strip()]
        if names:
            return names, "draft_state.queue"
    return [], "empty"


def paint_live_draft_sidebar_queue_mirror(st: Any, session: dict[str, Any]) -> list[str]:
    """Paint numbered queue rows into the Streamlit sidebar (safe to call twice/run)."""
    names, src = resolve_sidebar_queue_names(session)
    session["_live_draft_queue_sidebar_mirror"] = list(names)
    session["_live_draft_queue_sidebar_source"] = str(src)
    # Keep widget key aligned so later resolves cannot fall back to empty.
    if names:
        session["draft_queue"] = list(names)
        session["_live_draft_queue_last_good"] = list(names)
    try:
        st.sidebar.markdown("**Draft queue**")
    except Exception:
        pass
    if not names:
        st.sidebar.caption("Queue empty — add from Live Draft Room.")
        return []
    for i, name in enumerate(names[:12]):
        c1, c2 = st.sidebar.columns([4, 1])
        with c1:
            st.caption(f"{i + 1}. {name[:36]}{'…' if len(name) > 36 else ''}")
        with c2:
            if st.button(
                "✕",
                key=f"sidebar_mirror_rm_{i}_{hash(name) & 0xFFFF:x}_{int(session.get('_draft_queue_revision') or 0)}",
                help=f"Remove {name} from Draft Queue",
            ):
                try:
                    from draft_state import remove_player_from_user_draft_queue

                    remove_player_from_user_draft_queue(
                        session, name, reason="sidebar_mirror_remove"
                    )
                except ImportError:
                    session["draft_queue"] = [
                        p for p in (session.get("draft_queue") or []) if str(p).strip() != name
                    ]
                try:
                    st.rerun()
                except Exception:
                    pass
    if len(names) > 12:
        st.sidebar.caption(f"+{len(names) - 12} more")
    return list(names)
