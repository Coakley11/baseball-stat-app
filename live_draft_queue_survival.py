"""Draft Queue survival — multi-pass write audit (mutation → settled paint).

Captures A–D checkpoints **and every write/clear** of draft_queue / draft_state.queue
with script-pass IDs so a later app/hydrate pass cannot wipe silently.
"""

from __future__ import annotations

import time
import traceback
from typing import Any

QUEUE_SURVIVAL_LOG_KEY = "_live_draft_queue_survival_log"
QUEUE_WRITE_LOG_KEY = "_live_draft_queue_write_log"
QUEUE_SURVIVAL_MAX = 80
QUEUE_WRITE_MAX = 80
QUEUE_PASS_ID_KEY = "_live_draft_queue_pass_id"
QUEUE_PASS_SEQ_KEY = "_live_draft_queue_pass_seq"
QUEUE_ACTION_ID_KEY = "_live_draft_queue_action_id"

# Explicit clears allowed to empty a populated queue.
_ALLOWED_EMPTY_REASONS = frozenset(
    {
        "clear_queue",
        "remove_from_queue",
        "auth_user_switch",
        "auth_user_restore",
        "leave_shared_room",
        "delete_active_draft",
        "abandon_live_draft",
    }
)


def _names(raw: Any) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _flags(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "draft_state_dirty": bool(session.get("draft_state_dirty")),
        "queue_persist_dirty": bool(session.get("_draft_queue_persist_dirty")),
        "pending_sync": bool(session.get("_draft_workflow_pending_sync")),
        "hydrate_skipped": session.get("_live_draft_queue_hydrate_skipped"),
        "blob_restore_skipped": session.get("_live_draft_queue_blob_restore_skipped"),
        "empty_write_blocked": session.get("_live_draft_queue_empty_write_blocked"),
    }


def current_pass_id(session: dict[str, Any]) -> str:
    return str(session.get(QUEUE_PASS_ID_KEY) or "pass_0")


def current_action_id(session: dict[str, Any]) -> str:
    return str(session.get(QUEUE_ACTION_ID_KEY) or "")


def begin_queue_script_pass(session: dict[str, Any], *, st: Any | None = None) -> str:
    """Call once at the top of each Streamlit script run."""
    del st
    seq = int(session.get(QUEUE_PASS_SEQ_KEY) or 0) + 1
    session[QUEUE_PASS_SEQ_KEY] = seq
    pass_id = f"pass_{seq}"
    session[QUEUE_PASS_ID_KEY] = pass_id
    note_queue_survival(session, "PASS_BEGIN", detail=f"script_run {pass_id}")
    return pass_id


def begin_queue_action(session: dict[str, Any], *, name: str = "") -> str:
    """Start a new Add/Remove action correlation id."""
    action_id = f"act_{int(time.time() * 1000)}_{str(name or 'queue')[:24]}"
    session[QUEUE_ACTION_ID_KEY] = action_id
    session.pop("_live_draft_queue_cleared_at", None)
    session.pop("_live_draft_queue_empty_write_blocked", None)
    return action_id


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
        **_flags(session),
    }


def note_queue_survival(
    session: dict[str, Any],
    point: str,
    *,
    detail: str = "",
    st: Any | None = None,
) -> dict[str, Any]:
    """Record queue layers at A/B/C/D or PASS_BEGIN (any named gate)."""
    del st
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
        "pass_id": current_pass_id(session),
        "action_id": current_action_id(session),
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
            "pass_id": entry["pass_id"],
            "action_id": entry["action_id"],
            "detail": str(detail or "")[:160],
            "previous_point": prev.get("point") if isinstance(prev, dict) else None,
            "previous_pass_id": prev.get("pass_id") if isinstance(prev, dict) else None,
            "previous_queue": list(prev.get("session_draft_queue") or [])[:12]
            if isinstance(prev, dict)
            else [],
        }
    return entry


def record_queue_write(
    session: dict[str, Any],
    *,
    function: str,
    reason: str,
    old_session_queue: list[str] | None = None,
    new_session_queue: list[str] | None = None,
    old_draft_state_queue: list[str] | None = None,
    new_draft_state_queue: list[str] | None = None,
    blocked: bool = False,
    source: str = "",
) -> dict[str, Any]:
    """Log one mutation of session and/or draft_state queue."""
    old_s = _names(old_session_queue)
    new_s = _names(new_session_queue) if new_session_queue is not None else old_s
    old_d = _names(old_draft_state_queue)
    new_d = _names(new_draft_state_queue) if new_draft_state_queue is not None else old_d
    changed = old_s != new_s or old_d != new_d
    wiped = (bool(old_s) and not new_s) or (bool(old_d) and not new_d)
    caller = ""
    try:
        stack = traceback.extract_stack(limit=8)
        frames = [f"{fr.filename.split('/')[-1].split(chr(92))[-1]}:{fr.lineno}:{fr.name}" for fr in stack[:-1]]
        caller = " ← ".join(frames[-4:])
    except Exception:
        caller = ""
    entry = {
        "kind": "write",
        "pass_id": current_pass_id(session),
        "action_id": current_action_id(session),
        "function": str(function or ""),
        "reason": str(reason or "")[:120],
        "source": str(source or "")[:80],
        "old_session_queue": old_s[:12],
        "new_session_queue": new_s[:12],
        "old_draft_state_queue": old_d[:12],
        "new_draft_state_queue": new_d[:12],
        "changed": changed,
        "wiped_to_empty": wiped,
        "blocked": bool(blocked),
        "caller": caller[:240],
        **_flags(session),
    }
    log = list(session.get(QUEUE_WRITE_LOG_KEY) or [])
    log.append(entry)
    session[QUEUE_WRITE_LOG_KEY] = log[-QUEUE_WRITE_MAX:]
    session["_live_draft_queue_write_latest"] = entry
    if wiped and not blocked:
        session["_live_draft_queue_wiped_by"] = {
            "pass_id": entry["pass_id"],
            "action_id": entry["action_id"],
            "function": entry["function"],
            "reason": entry["reason"],
            "old_session_queue": old_s[:12],
            "caller": caller[:240],
            **_flags(session),
        }
        note_queue_survival(
            session,
            "WIPE",
            detail=f"{function}:{reason}",
        )
    return entry


def should_block_empty_queue_write(
    session: dict[str, Any],
    *,
    old_queue: list[str],
    new_queue: list[str],
    reason: str,
) -> bool:
    """Refuse silent empties of a populated queue except explicit clear reasons."""
    if _names(new_queue):
        return False
    if not _names(old_queue):
        return False
    base = str(reason or "").strip()
    if base in _ALLOWED_EMPTY_REASONS:
        return False
    # Always block accidental empties while dirty/pending, and also when wiping
    # a known non-empty widget without an explicit clear reason.
    if (
        session.get("draft_state_dirty")
        or session.get("_draft_workflow_pending_sync")
        or session.get("_draft_queue_persist_dirty")
        or current_action_id(session)
    ):
        return True
    return True  # pop→[] without explicit reason is never allowed


def render_queue_survival_panel(st: Any, session: dict[str, Any]) -> None:
    """Sidebar: multi-pass survival + write audit (Developer Mode only)."""
    try:
        from suite_workspace import developer_mode_checkbox_enabled

        if not developer_mode_checkbox_enabled(st=st):
            return
    except ImportError:
        if not (
            bool(session.get("app_developer_mode"))
            or bool(session.get("_suite_developer_mode_user"))
        ):
            return
    log = [e for e in list(session.get(QUEUE_SURVIVAL_LOG_KEY) or []) if isinstance(e, dict)]
    writes = [e for e in list(session.get(QUEUE_WRITE_LOG_KEY) or []) if isinstance(e, dict)]
    cleared = session.get("_live_draft_queue_cleared_at")
    wiped = session.get("_live_draft_queue_wiped_by")
    with st.sidebar.expander("Queue survival (Add → paint)", expanded=True):
        st.caption(
            f"Current pass=`{current_pass_id(session)}` · action=`{current_action_id(session) or '—'}` · "
            "A/B/C/D plus WRITE/WIPE across every app pass until settled."
        )
        if isinstance(wiped, dict):
            st.error(
                f"WIPED by **{wiped.get('function')}** reason=`{wiped.get('reason')}` "
                f"pass=`{wiped.get('pass_id')}` old={wiped.get('old_session_queue')}"
            )
            st.caption(f"caller: {wiped.get('caller') or '—'}")
        elif isinstance(cleared, dict):
            st.error(
                f"CLEARED at **{cleared.get('point')}** pass=`{cleared.get('pass_id')}` "
                f"(after **{cleared.get('previous_point')}** / {cleared.get('previous_pass_id')}): "
                f"{cleared.get('previous_queue')}"
            )
        if session.get("_live_draft_queue_empty_write_blocked"):
            st.warning(f"Blocked empty write: {session.get('_live_draft_queue_empty_write_blocked')}")
        if not log and not writes:
            st.info("No survival samples yet — click ⭐ Add to Queue.")
            return
        rows = []
        for e in log[-16:]:
            rows.append(
                {
                    "point": e.get("point"),
                    "pass": e.get("pass_id"),
                    "sess": e.get("session_draft_queue"),
                    "draft_state": e.get("draft_state_queue"),
                    "dirty": e.get("draft_state_dirty"),
                    "cleared": e.get("cleared_since_previous"),
                    "detail": e.get("detail"),
                }
            )
        try:
            import pandas as pd

            st.markdown("**Checkpoints**")
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        except Exception:
            st.json(rows[-8:])
        write_rows = []
        for e in writes[-16:]:
            write_rows.append(
                {
                    "pass": e.get("pass_id"),
                    "fn": e.get("function"),
                    "reason": e.get("reason"),
                    "old": e.get("old_session_queue"),
                    "new": e.get("new_session_queue"),
                    "wipe": e.get("wiped_to_empty"),
                    "blocked": e.get("blocked"),
                    "dirty": e.get("draft_state_dirty"),
                }
            )
        if write_rows:
            st.markdown("**Writes / clears**")
            try:
                import pandas as pd

                st.dataframe(pd.DataFrame(write_rows), width="stretch", hide_index=True)
            except Exception:
                st.json(write_rows[-8:])
        st.json(
            {
                "latest_checkpoint": session.get("_live_draft_queue_survival_latest"),
                "latest_write": session.get("_live_draft_queue_write_latest"),
                "wiped_by": wiped,
            }
        )
