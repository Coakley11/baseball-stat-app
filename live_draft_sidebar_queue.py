"""Paint the Live Draft nav-sidebar queue mirror from canonical session layers."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_PAINT_LOG = Path(__file__).resolve().parent / "data" / "tb_probe" / "sidebar_queue_paint.jsonl"


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
    try:
        writes = list(session.get("_live_draft_queue_write_log") or [])
        for entry in reversed(writes):
            if not isinstance(entry, dict):
                continue
            names = [str(x).strip() for x in (entry.get("new_session_queue") or []) if str(x).strip()]
            if names:
                return names, f"write_log:{entry.get('function')}"
    except Exception:
        pass
    return [], "empty"


def paint_live_draft_sidebar_queue_mirror(st: Any, session: dict[str, Any]) -> list[str]:
    """Paint numbered queue rows into the Streamlit sidebar (idempotent per ScriptRun).

    Caller owns the ``**Draft queue**`` heading — this paint must not duplicate it.
    Safe to call once per run from the persistent workflow sidebar only.
    """
    if session.get("_live_draft_sidebar_queue_painted_this_run"):
        return list(session.get("_live_draft_queue_sidebar_mirror") or [])
    session["_live_draft_sidebar_queue_painted_this_run"] = True

    names, src = resolve_sidebar_queue_names(session)
    session["_live_draft_queue_sidebar_source"] = str(src)
    if names:
        session["_live_draft_queue_sidebar_mirror"] = list(names)
        session["draft_queue"] = list(names)
        session["_live_draft_queue_last_good"] = list(names)
    try:
        _PAINT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _PAINT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "ts": time.time(),
                        "src": src,
                        "names": list(names)[:12],
                        "draft_queue": [
                            str(x).strip()
                            for x in (session.get("draft_queue") or [])
                            if str(x).strip()
                        ][:12],
                        "last_good": [
                            str(x).strip()
                            for x in (session.get("_live_draft_queue_last_good") or [])
                            if str(x).strip()
                        ][:12],
                    }
                )
                + "\n"
            )
    except Exception:
        pass

    if not names:
        st.sidebar.caption("Queue empty — add from Live Draft Room.")
        return []

    # Compact scrape-friendly line (harness + human glance).
    st.sidebar.caption("Draft Queue: " + ", ".join(names[:8]))
    try:
        from draft_queue_contract import draft_status_label, queue_draft_status

        status = queue_draft_status(session, names)
    except ImportError:
        status, draft_status_label = {}, None
    try:
        from player_photos import queue_photo_info, render_queue_headshot_inline_html, reset_queue_photo_budget

        reset_queue_photo_budget(session)
    except ImportError:
        queue_photo_info = None
    for i, name in enumerate(names[:12]):
        c1, c2 = st.sidebar.columns([4, 1])
        with c1:
            short = f"{name[:36]}{'…' if len(name) > 36 else ''}"
            info = status.get(name.strip().lower())
            photo = ""
            if queue_photo_info is not None:
                try:
                    photo = render_queue_headshot_inline_html(queue_photo_info(session, name))
                except Exception:
                    photo = ""
            if photo:
                import html as _html

                text = f"{i + 1}. {_html.escape(short)}"
                if info and draft_status_label:
                    text = f"<s>{text}</s> · ✓ {_html.escape(draft_status_label(info, short=True))}"
                st.markdown(f'<div style="font-size:0.82rem;line-height:1.35;color:#475569;">{photo}{text}</div>',
                            unsafe_allow_html=True)
            elif info and draft_status_label:
                # Still in the personal queue for other drafts; taken in this one, by whom.
                st.caption(f"{i + 1}. ~~{short}~~ · ✓ {draft_status_label(info, short=True)}")
            else:
                st.caption(f"{i + 1}. {short}")
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
    try:
        import draft_queue_modes as dqm

        if dqm.current_mode(session) == "adaptive":
            state = dqm.draft_state(session, dqm.draft_source(session)) or {}
            orders = state.get("orders") or {}
            if orders:
                order = orders[max(orders, key=int)]
                fixed = {n.strip().lower(): i for i, n in enumerate(n for n in names if n.strip().lower() not in taken)}
                marks = []
                for i, n in enumerate(order[:8]):
                    d = fixed.get(n.strip().lower(), i) - i
                    marks.append(f"{i + 1}. {n}" + (" ↑" if d >= 2 else (" ↓" if d <= -2 else "")))
                st.sidebar.caption("Adaptive order (this draft): " + " · ".join(marks))
    except Exception:
        pass
    return list(names)
