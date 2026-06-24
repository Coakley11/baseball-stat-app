"""Temporary join-flow tracing for Live Draft Room multiplayer (dev / acceptance)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

JOIN_TRACE_KEY = "_draft_join_trace"
JOIN_TRACE_MAX = 40


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def trace_join_step(session: dict[str, Any], step: str, **fields: Any) -> None:
    """Append a join-flow event to session trace and application log."""
    entry: dict[str, Any] = {"ts": _utc_now_iso(), "step": str(step)}
    for key, value in fields.items():
        if value is not None:
            entry[key] = value
    trace = session.get(JOIN_TRACE_KEY)
    if not isinstance(trace, list):
        trace = []
    trace.append(entry)
    session[JOIN_TRACE_KEY] = trace[-JOIN_TRACE_MAX:]
    try:
        detail = " ".join(f"{k}={v!r}" for k, v in fields.items() if v is not None)
        log.info("draft_join_trace step=%s %s", step, detail)
    except Exception:
        log.info("draft_join_trace step=%s", step)


def join_trace_visible(session: dict[str, Any]) -> bool:
    if session.get("dev_mode") or session.get("app_developer_mode"):
        return True
    try:
        from suite_workspace import _developer_query_enabled

        st_obj = type("S", (), {"session_state": session})()
        if _developer_query_enabled(st_obj):
            return True
    except ImportError:
        pass
    return False


def render_join_trace_panel(st: Any, session: dict[str, Any]) -> None:
    if not join_trace_visible(session):
        return
    trace = session.get(JOIN_TRACE_KEY)
    if not isinstance(trace, list) or not trace:
        return
    with st.expander("Join flow trace (dev)", expanded=False):
        for row in reversed(trace[-20:]):
            if not isinstance(row, dict):
                continue
            parts = [str(row.get("ts") or "")[:19], str(row.get("step") or "")]
            extras = {k: v for k, v in row.items() if k not in ("ts", "step")}
            if extras:
                parts.append(str(extras))
            st.caption(" · ".join(p for p in parts if p))
