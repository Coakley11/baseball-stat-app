"""Observability: component declaration / return-value binding trace (Case A vs production)."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

TRACE_SESSION_KEY = "_solo_component_binding_trace_v1"
PRODUCTION_PERSISTENT_KEY = "solo_countdown_wake_solo_persistent"


def _script_run_id(session: dict[str, Any]) -> str:
    try:
        from app_page_generation import current_script_run_id

        return str(current_script_run_id(session) or "")
    except ImportError:
        return str(session.get("_live_draft_script_run_id") or "")


def record_binding_boundary(
    session: dict[str, Any],
    *,
    boundary: str,
    call_site: str,
    user_key: str = "",
    raw_in: Any = None,
    raw_out: Any = None,
    session_state_before: Any = None,
    session_state_after: Any = None,
    extra: dict[str, Any] | None = None,
) -> None:
    rows = list(session.get(TRACE_SESSION_KEY) or [])
    row: dict[str, Any] = {
        "ts": time.time(),
        "script_run_seq": int(session.get("_solo_stage1_script_run_seq") or 0),
        "script_run_id": _script_run_id(session)[:32],
        "boundary": boundary,
        "call_site": call_site,
        "user_key": str(user_key or "")[:120],
        "raw_in_repr": repr(raw_in)[:400] if raw_in is not None else "",
        "raw_out_repr": repr(raw_out)[:400] if raw_out is not None else "",
        "session_state_before": repr(session_state_before)[:400],
        "session_state_after": repr(session_state_after)[:400],
    }
    if extra:
        row.update(extra)
    rows.append(row)
    session[TRACE_SESSION_KEY] = rows[-200:]


def declaration_count_this_run(session: dict[str, Any], user_key: str) -> int:
    run_id = _script_run_id(session)
    if not run_id:
        return 0
    n = 0
    for row in session.get(TRACE_SESSION_KEY) or []:
        if not isinstance(row, dict):
            continue
        if row.get("boundary") != "component_mount":
            continue
        if str(row.get("user_key") or "") != user_key:
            continue
        if str(row.get("script_run_id") or "") == run_id[:32]:
            n += 1
    return n


def peek_trace(session: dict[str, Any]) -> list[dict[str, Any]]:
    return list(session.get(TRACE_SESSION_KEY) or [])


def arguments_hash(kwargs: dict[str, Any]) -> str:
    try:
        payload = json.dumps(kwargs, sort_keys=True, default=str)
    except TypeError:
        payload = str(kwargs)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
