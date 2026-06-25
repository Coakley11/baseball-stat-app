"""
Resume Draft Simulation Test Mode from Command Center deep links.

Loads or rebuilds ``draft_lab_results`` from a ``draft_room_id`` / ``bb:draft_lab:*`` resume key.
"""

from __future__ import annotations

from typing import Any

PENDING_RESUME_QUERY_KEY = "_suite_pending_resume_query"
DRAFT_LAB_RESUME_PAGE = "Draft Simulation Test Mode"


def _qp_get(st: Any, name: str) -> str:
    try:
        raw = st.query_params.get(name)
    except Exception:
        return ""
    if raw is None:
        return ""
    if isinstance(raw, list):
        return str(raw[0] or "").strip()
    return str(raw).strip()


def capture_pending_resume_query(st: Any, app_key: str = "baseball") -> dict[str, str]:
    """Persist deep-link query params through auth reruns when URL params remain."""
    try:
        from suite_cloud_state import list_active_resume_query_params

        names = set(list_active_resume_query_params(st, app_key))
    except ImportError:
        names = {
            "suite_resume",
            "suite_page",
            "suite_draft_room",
            "suite_draft_section",
            "suite_workspace",
        }
    names.update({"suite_draft_room", "suite_draft_section", "suite_workspace"})
    captured = {k: _qp_get(st, k) for k in sorted(names) if _qp_get(st, k)}
    if captured:
        st.session_state[PENDING_RESUME_QUERY_KEY] = captured
    elif PENDING_RESUME_QUERY_KEY not in st.session_state:
        st.session_state[PENDING_RESUME_QUERY_KEY] = {}
    return dict(st.session_state.get(PENDING_RESUME_QUERY_KEY) or {})


def pending_resume_query(st: Any) -> dict[str, str]:
    raw = st.session_state.get(PENDING_RESUME_QUERY_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _draft_lab_results_room_id(session: dict[str, Any]) -> str:
    results = session.get("draft_lab_results")
    if not isinstance(results, dict):
        return ""
    handoff = results.get("handoff") if isinstance(results.get("handoff"), dict) else {}
    ctx = results.get("analysis_context") if isinstance(results.get("analysis_context"), dict) else {}
    return str(
        handoff.get("draft_room_id")
        or handoff.get("session_id")
        or ctx.get("draft_room_id")
        or ""
    ).strip()


def _find_live_room(session: dict[str, Any], room_id: str) -> dict[str, Any] | None:
    rid = str(room_id or "").strip()
    if not rid:
        return None
    for key in ("live_draft_room", "live_draft_state"):
        blob = session.get(key)
        if isinstance(blob, dict) and str(blob.get("draft_room_id") or "").strip() == rid:
            return blob
    return None


def schedule_draft_lab_resume_navigation(st: Any, *, page: str, room_id: str = "", section: str = "") -> None:
    """Force Draft Simulation Test Mode to win over default Historical Explorer restore."""
    target = str(page or DRAFT_LAB_RESUME_PAGE).strip() or DRAFT_LAB_RESUME_PAGE
    ss = st.session_state
    ss["_navigate_to_page"] = target
    ss["active_page"] = target
    ss["main_sidebar_page"] = target
    ss["_suite_pending_draft_lab_resume"] = True
    if room_id:
        ss["_suite_resume_draft_room"] = str(room_id).strip()
    if section:
        ss["_suite_resume_draft_section"] = str(section).strip().lower()
    # claim_user_page_ownership triggers reconcile_stale_page_navigation which clears
    # _navigate_to_page — re-assert resume navigation after optional ownership claim.
    try:
        from suite_user_persistence import claim_user_page_ownership

        claim_user_page_ownership(st, "baseball", target)
    except ImportError:
        pass
    ss["_navigate_to_page"] = target
    ss["_skip_page_restore_for"] = target
    ss["active_page"] = target
    ss["main_sidebar_page"] = target
    ss["_suite_page_user_nav"] = True
    ss["active_page_source"] = "suite_resume_launch"


def apply_draft_lab_resume(st: Any) -> dict[str, Any]:
    """Rebuild or confirm draft_lab_results for a resume deep link."""
    ss = st.session_state
    diag: dict[str, Any] = {
        "room_id": str(ss.get("_suite_resume_draft_room") or "").strip(),
        "draft_section": str(ss.get("_suite_resume_draft_section") or "").strip(),
        "draft_lab_results_status": "not_requested",
        "rebuild_attempted": False,
        "rebuild_success": False,
    }
    room_id = diag["room_id"]
    if not room_id and not ss.get("_suite_pending_draft_lab_resume"):
        return diag

    existing = _draft_lab_results_room_id(ss)
    if existing and (not room_id or existing == room_id):
        diag["draft_lab_results_status"] = "already_in_session"
        diag["rebuild_success"] = True
        return diag

    if not room_id:
        diag["draft_lab_results_status"] = "missing_room_id"
        return diag

    room = _find_live_room(ss, room_id)
    if room is None:
        diag["draft_lab_results_status"] = "room_not_in_session"
        return diag

    status = str(room.get("status") or "").strip().lower()
    if status != "complete":
        try:
            from live_draft_safe_mode import is_draft_truly_complete

            if not is_draft_truly_complete(room):
                diag["draft_lab_results_status"] = "room_not_complete"
                return diag
        except ImportError:
            diag["draft_lab_results_status"] = "room_not_complete"
            return diag

    diag["rebuild_attempted"] = True
    try:
        from streamlit_app import live_draft_push_analysis_to_session

        ok = bool(live_draft_push_analysis_to_session(room))
        diag["rebuild_success"] = ok
        diag["draft_lab_results_status"] = "rebuilt_from_room" if ok else "rebuild_failed"
    except Exception as exc:
        diag["draft_lab_results_status"] = f"rebuild_error:{exc}"
    return diag


def draft_lab_resume_diagnostics(st: Any) -> dict[str, Any]:
    """Developer panel: parse resume URL + hydration outcome."""
    pending = pending_resume_query(st)
    out: dict[str, Any] = {
        "query_params": {k: _qp_get(st, k) for k in (
            "suite_resume",
            "suite_page",
            "suite_draft_room",
            "suite_draft_section",
            "suite_workspace",
        )},
        "pending_resume_query": pending,
        "parsed_suite_page": _qp_get(st, "suite_page") or pending.get("suite_page") or "",
        "parsed_suite_resume": _qp_get(st, "suite_resume") or pending.get("suite_resume") or "",
        "parsed_suite_draft_room": str(st.session_state.get("_suite_resume_draft_room") or pending.get("suite_draft_room") or ""),
        "parsed_suite_draft_section": str(st.session_state.get("_suite_resume_draft_section") or pending.get("suite_draft_section") or ""),
        "selected_final_page": str(st.session_state.get("active_page") or ""),
        "scheduled_navigate_to_page": str(st.session_state.get("_navigate_to_page") or ""),
        "suite_page_user_nav": bool(st.session_state.get("_suite_page_user_nav")),
        "pending_draft_lab_resume": bool(st.session_state.get("_suite_pending_draft_lab_resume")),
        "draft_lab_results_room_id": _draft_lab_results_room_id(st.session_state),
        "auth_preserved_pending_query": bool(pending),
    }
    out.update(apply_draft_lab_resume(st))
    return out
