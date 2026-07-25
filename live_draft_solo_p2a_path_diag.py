"""P2A hook path breadcrumbs — query-gated diagnostic only (no st.stop)."""

from __future__ import annotations

import html
import json
import time
from typing import Any

from live_draft_solo_placement_micro import (
    REQUESTED_MICRO_KEY,
    SESSION_MICRO_KEY,
    _solo_in_progress_room,
    current_micro_placement,
    micro_from_query,
    micro_isolation_active,
)


def _esc(val: Any) -> str:
    return html.escape(str(val if val is not None else ""), quote=True)


def _latch_snapshot(session: dict[str, Any], st: Any) -> dict[str, str]:
    req = str(session.get(REQUESTED_MICRO_KEY) or session.get("_solo_placement_ladder_requested") or "").upper()
    latched = str(session.get(SESSION_MICRO_KEY) or "").upper()
    query = micro_from_query(st)
    return {
        "requested_placement": req,
        "latched_placement": latched,
        "query_placement": query,
    }


def p2a_trace_requested(st: Any, session: dict[str, Any]) -> bool:
    if not micro_isolation_active(st, session):
        return False
    latch = _latch_snapshot(session, st)
    for key in ("requested_placement", "latched_placement", "query_placement"):
        if latch.get(key) == "P2A":
            return True
    return micro_from_query(st) == "P2A"


def _post_create_open(session: dict[str, Any]) -> bool:
    try:
        from live_draft_creation_trace import POST_CREATE_OPEN_KEY

        return bool(session.get(POST_CREATE_OPEN_KEY))
    except ImportError:
        return False


def _resolve_lifecycle(session: dict[str, Any], room_dict: dict[str, Any]) -> str:
    try:
        from live_draft_completion import resolve_live_draft_lifecycle

        return str(
            resolve_live_draft_lifecycle(session, room=room_dict if room_dict else None) or ""
        )
    except ImportError:
        return ""


def p2a_active_mount_predicates(
    session: dict[str, Any], room_dict: dict[str, Any]
) -> dict[str, bool]:
    lifecycle = _resolve_lifecycle(session, room_dict)
    solo_in_progress = bool(room_dict) and _solo_in_progress_room(session, room_dict)
    return {
        "lifecycle_active_draft": lifecycle == "active_draft",
        "room_status_in_progress": str(room_dict.get("status") or "") == "in_progress",
        "solo_in_progress_room": solo_in_progress,
        "start_pending": bool(session.get("_start_live_draft_pending")),
        "start_in_flight": bool(session.get("_live_draft_start_in_flight")),
    }


def p2a_active_mount_allowed(session: dict[str, Any], room_dict: dict[str, Any]) -> bool:
    p = p2a_active_mount_predicates(session, room_dict)
    return (
        p["lifecycle_active_draft"]
        and p["room_status_in_progress"]
        and p["solo_in_progress_room"]
        and not p["start_pending"]
        and not p["start_in_flight"]
    )


def p2a_defer_until_draft_surface(session: dict[str, Any], room: Any) -> bool:
    """Diagnostic defer: block P2A until start flags clear and post-create room is ready."""
    if session.get("_start_live_draft_pending") or session.get("_live_draft_start_in_flight"):
        return True
    room_dict = room if isinstance(room, dict) else {}
    if _post_create_open(session):
        return not p2a_active_mount_allowed(session, room_dict)
    return False


def p2a_allowance_note(session: dict[str, Any], room: dict[str, Any]) -> str:
    room_dict = room if isinstance(room, dict) else {}
    if _post_create_open(session) and p2a_active_mount_allowed(session, room_dict):
        return "post_create_open_but_active_room_allowed"
    return ""


def collect_p2a_readiness(
    st: Any,
    session: dict[str, Any],
    room: Any,
    *,
    active_page: str = "",
    script_branch: str = "",
) -> dict[str, Any]:
    latch = _latch_snapshot(session, st)
    room_dict = room if isinstance(room, dict) else {}
    receipt: dict[str, Any] = {}
    receipt: dict[str, Any] = {}
    try:
        from live_draft_creation_trace import CREATION_RECEIPT_KEY

        receipt = dict(session.get(CREATION_RECEIPT_KEY) or {})
    except ImportError:
        pass
    post_create_open = _post_create_open(session)
    lifecycle = _resolve_lifecycle(session, room_dict)
    solo_in_progress = bool(room_dict) and _solo_in_progress_room(session, room_dict)
    mount_predicates = p2a_active_mount_predicates(session, room_dict)
    allowance = p2a_allowance_note(session, room_dict)
    return {
        "ts": time.time(),
        "script_branch": script_branch,
        "active_page": str(active_page or session.get("active_page") or ""),
        **latch,
        "current_micro_placement": current_micro_placement(st, session),
        "micro_isolation_active": micro_isolation_active(st, session),
        "active_page_entered": bool(receipt.get("active_page_entered")),
        "creation_success": bool(receipt.get("creation_success")),
        "creation_receipt_json": json.dumps(receipt, default=str)[:2000],
        "post_create_open": post_create_open,
        "start_pending": bool(session.get("_start_live_draft_pending")),
        "start_in_flight": bool(session.get("_live_draft_start_in_flight")),
        "live_draft_room_present": isinstance(room, dict),
        "draft_id": str(room_dict.get("draft_id") or room_dict.get("draft_room_id") or ""),
        "room_id": str(room_dict.get("draft_room_id") or room_dict.get("draft_id") or ""),
        "room_status": str(room_dict.get("status") or ""),
        "solo_in_progress_room": solo_in_progress,
        "lifecycle": lifecycle,
        "executing_setup_branch": lifecycle in ("setup", "") and not solo_in_progress,
        "executing_active_room_branch": lifecycle in ("active_draft", "in_progress") or solo_in_progress,
        "mount_predicates": mount_predicates,
        "post_create_open_allowed": allowance == "post_create_open_but_active_room_allowed",
        "defer_until_draft_surface": p2a_defer_until_draft_surface(session, room_dict),
    }


def _append_path_log(session: dict[str, Any], row: dict[str, Any]) -> None:
    key = "_solo_p2a_path_log"
    log = list(session.get(key) or [])
    log.append(row)
    session[key] = log[-40:]


def render_p2a_callsite_breadcrumb(
    st: Any,
    session: dict[str, Any],
    room: Any,
    *,
    active_page: str = "",
) -> None:
    if not p2a_trace_requested(st, session):
        return
    snap = collect_p2a_readiness(
        st,
        session,
        room,
        active_page=active_page,
        script_branch="pre_try_micro_p2a_call_site",
    )
    _append_path_log(session, {"event": "callsite", **snap})
    st.markdown(
        f'<div id="solo-p2a-callsite-diag" '
        f'data-present="1" '
        f'data-requested="{_esc(snap.get("requested_placement"))}" '
        f'data-latched="{_esc(snap.get("latched_placement"))}" '
        f'data-query="{_esc(snap.get("query_placement"))}" '
        f'data-active-page="{_esc(snap.get("active_page"))}" '
        f'data-active-page-entered="{1 if snap.get("active_page_entered") else 0}" '
        f'data-room-present="{1 if snap.get("live_draft_room_present") else 0}" '
        f'data-room-id="{_esc(snap.get("room_id"))}" '
        f'data-room-status="{_esc(snap.get("room_status"))}" '
        f'data-solo-in-progress="{1 if snap.get("solo_in_progress_room") else 0}" '
        f'data-start-pending="{1 if snap.get("start_pending") else 0}" '
        f'data-start-in-flight="{1 if snap.get("start_in_flight") else 0}" '
        f'data-post-create-open="{1 if snap.get("post_create_open") else 0}" '
        f'data-lifecycle="{_esc(snap.get("lifecycle"))}" '
        f'data-setup-branch="{1 if snap.get("executing_setup_branch") else 0}" '
        f'data-active-branch="{1 if snap.get("executing_active_room_branch") else 0}" '
        f'data-snap="{_esc(json.dumps(snap, default=str)[:3500])}"></div>',
        unsafe_allow_html=True,
    )


def render_p2a_branch_breadcrumb(
    st: Any,
    session: dict[str, Any],
    *,
    marker: str,
    detail: str = "",
) -> None:
    if not p2a_trace_requested(st, session):
        return
    row = {"event": "branch", "marker": marker, "detail": detail, "ts": time.time()}
    _append_path_log(session, row)
    st.markdown(
        f'<div class="solo-p2a-path-branch" id="solo-p2a-branch-diag" '
        f'data-marker="{_esc(marker)}" data-detail="{_esc(detail)}" '
        f'data-ts="{row["ts"]}"></div>',
        unsafe_allow_html=True,
    )


def render_p2a_fn_entry(
    st: Any,
    session: dict[str, Any],
    room: dict[str, Any],
    *,
    decline: str = "",
) -> None:
    snap = collect_p2a_readiness(
        st,
        session,
        room,
        script_branch="try_micro_p2a_function_entry",
    )
    _append_path_log(session, {"event": "fn_entry", "decline": decline, **snap})
    st.markdown(
        f'<div id="solo-p2a-fn-entry-diag" '
        f'data-present="1" '
        f'data-decline="{_esc(decline)}" '
        f'data-snap="{_esc(json.dumps(snap, default=str)[:3500])}"></div>',
        unsafe_allow_html=True,
    )


def render_p2a_decline(st: Any, session: dict[str, Any], reason: str, **fields: Any) -> None:
    if not p2a_trace_requested(st, session):
        return
    row = {"event": "decline", "reason": reason, "ts": time.time(), **fields}
    _append_path_log(session, row)
    st.markdown(
        f'<div id="solo-p2a-decline-diag" '
        f'data-reason="{_esc(reason)}" '
        f'data-fields="{_esc(json.dumps(fields, default=str)[:1500])}" '
        f'data-ts="{row["ts"]}"></div>',
        unsafe_allow_html=True,
    )


def p2a_hook_ready_reason(st: Any, session: dict[str, Any], room: dict[str, Any]) -> str:
    """Return empty string if hook would proceed past guards (before _run_micro)."""
    if current_micro_placement(st, session) != "P2A":
        return "placement_not_p2a"
    if session.get("_start_live_draft_pending"):
        return "start_pending"
    if session.get("_live_draft_start_in_flight"):
        return "start_in_flight"
    room_dict = room if isinstance(room, dict) else {}
    if _post_create_open(session):
        if p2a_active_mount_allowed(session, room_dict):
            return ""
        return "post_create_open_room_not_ready"
    if not room_dict:
        return "room_missing"
    if not p2a_active_mount_allowed(session, room_dict):
        if str(room_dict.get("status") or "") != "in_progress":
            return "status_not_in_progress"
        if not _solo_in_progress_room(session, room_dict):
            return "status_not_in_progress"
        if _resolve_lifecycle(session, room_dict) != "active_draft":
            return "lifecycle_not_active_draft"
        return "room_not_ready"
    return ""
