"""
Resume Draft Simulation Test Mode from Command Center deep links.

Loads or rebuilds ``draft_lab_results`` from a ``draft_room_id`` / ``bb:draft_lab:*`` resume key.
"""

from __future__ import annotations

from typing import Any

try:
    from draft_lab_state import DRAFT_LAB_PAGE, DRAFT_LAB_PAGE_LEGACY, has_pending_draft_lab_handoff
except ImportError:
    DRAFT_LAB_PAGE = "Draft Lab / Simulation"
    DRAFT_LAB_PAGE_LEGACY = "Draft Simulation Test Mode"

    def has_pending_draft_lab_handoff(_session: dict[str, Any]) -> bool:
        return False

PENDING_RESUME_QUERY_KEY = "_suite_pending_resume_query"
DRAFT_LAB_RESUME_PAGE = DRAFT_LAB_PAGE
_DRAFT_LAB_PAGE_NAMES = frozenset({DRAFT_LAB_PAGE, DRAFT_LAB_PAGE_LEGACY})


def _is_draft_lab_page(name: str) -> bool:
    return str(name or "").strip() in _DRAFT_LAB_PAGE_NAMES


DRAFT_LAB_RESUME_ERROR_KEY = "_draft_lab_resume_error"
DRAFT_LAB_RESUME_DIAG_KEY = "_draft_lab_resume_last_diag"
DRAFT_LAB_RESUME_COMPLETED_KEY = "_draft_lab_resume_completed"
DRAFT_LAB_RESUME_REQUESTED_KEY = "_draft_lab_resume_requested"
DRAFT_LAB_RESUME_QUERY_KEYS = frozenset(
    {
        "suite_resume",
        "suite_page",
        "suite_draft_room",
        "suite_draft_section",
        "suite_hof_target",
        "suite_hof_case",
        "suite_ai_question_id",
        "suite_ami_insight",
    }
)


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


def draft_lab_resume_consumed(session: dict[str, Any]) -> bool:
    return bool(session.get(DRAFT_LAB_RESUME_COMPLETED_KEY))


def resume_requested(session: dict[str, Any]) -> bool:
    return bool(
        session.get(DRAFT_LAB_RESUME_REQUESTED_KEY)
        or session.get("_suite_pending_draft_lab_resume")
    )


def forced_page_active(session: dict[str, Any]) -> bool:
    pending = bool(session.get("_suite_pending_draft_lab_resume"))
    nav = str(session.get("_navigate_to_page") or "").strip()
    skip = str(session.get("_skip_page_restore_for") or "").strip()
    return pending or nav == DRAFT_LAB_RESUME_PAGE or skip == DRAFT_LAB_RESUME_PAGE


def _clear_pending_resume_query_draft_lab(session: dict[str, Any]) -> None:
    pending = session.get(PENDING_RESUME_QUERY_KEY)
    if not isinstance(pending, dict):
        return
    for key in DRAFT_LAB_RESUME_QUERY_KEYS:
        pending.pop(key, None)
    if pending:
        session[PENDING_RESUME_QUERY_KEY] = pending
    else:
        session.pop(PENDING_RESUME_QUERY_KEY, None)


def clear_resume_query_params(st: Any) -> None:
    """Remove draft-lab resume params from the URL so refresh does not re-trigger."""
    try:
        qp = st.query_params
        for key in DRAFT_LAB_RESUME_QUERY_KEYS:
            if key in qp:
                del qp[key]
    except Exception:
        pass


def finalize_draft_lab_resume(st: Any, *, applied: bool = True) -> None:
    """One-shot completion — release navigation locks after resume/hydration."""
    ss = st.session_state
    ss[DRAFT_LAB_RESUME_COMPLETED_KEY] = True
    pending = dict(ss.get(PENDING_RESUME_QUERY_KEY) or {})
    resume_key = str(pending.get("suite_resume") or "").strip()
    if resume_key:
        try:
            from shared_draft_context import mark_resume_key_consumed

            mark_resume_key_consumed(ss, resume_key)
        except ImportError:
            ss["_suite_last_consumed_resume_key"] = resume_key
    ss.pop("_suite_pending_draft_lab_resume", None)
    if _is_draft_lab_page(str(ss.get("_navigate_to_page") or "")):
        ss.pop("_navigate_to_page", None)
    if _is_draft_lab_page(str(ss.get("_skip_page_restore_for") or "")):
        ss.pop("_skip_page_restore_for", None)
    _clear_pending_resume_query_draft_lab(ss)
    clear_resume_query_params(st)
    if applied:
        ss.pop(DRAFT_LAB_RESUME_ERROR_KEY, None)


def cancel_draft_lab_resume_navigation(st: Any, user_page: str) -> None:
    """User picked a different page — stop forcing Draft Simulation Test Mode."""
    ss = st.session_state
    if not resume_requested(ss) and not forced_page_active(ss):
        return
    target = str(user_page or "").strip()
    if target and target != DRAFT_LAB_RESUME_PAGE:
        finalize_draft_lab_resume(st, applied=draft_lab_resume_consumed(ss))


def mark_resume_requested(session: dict[str, Any]) -> None:
    session[DRAFT_LAB_RESUME_REQUESTED_KEY] = True
    session["_suite_pending_draft_lab_resume"] = True


def _resume_diag_flags(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "resume_requested": resume_requested(session),
        "resume_applied": bool(session.get(DRAFT_LAB_RESUME_DIAG_KEY)),
        "resume_completed": draft_lab_resume_consumed(session),
        "forced_page_active": forced_page_active(session),
        "final_selected_page": str(session.get("active_page") or ""),
    }


def capture_pending_resume_query(st: Any, app_key: str = "baseball") -> dict[str, str]:
    """Persist deep-link query params through auth reruns when URL params remain."""
    if draft_lab_resume_consumed(st.session_state):
        return dict(st.session_state.get(PENDING_RESUME_QUERY_KEY) or {})
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


def parse_resume_room_id(st: Any, session: dict[str, Any] | None = None) -> str:
    """Resolve draft room id from session, pending query capture, or resume key."""
    ss = session if isinstance(session, dict) else {}
    room_id = str(ss.get("_suite_resume_draft_room") or "").strip()
    pending = pending_resume_query(st) if st is not None else {}
    if not room_id:
        room_id = str(pending.get("suite_draft_room") or "").strip()
    if not room_id and st is not None:
        room_id = _qp_get(st, "suite_draft_room")
    resume = ""
    if st is not None:
        resume = _qp_get(st, "suite_resume")
    if not resume:
        resume = str(pending.get("suite_resume") or "").strip()
    if not room_id and resume.startswith("bb:draft_lab:"):
        tail = resume.split(":", 2)[-1].strip()
        if tail.startswith("team:"):
            room_id = tail.split(":", 1)[-1].strip()
        elif tail not in {"team", "team_analysis"}:
            room_id = tail
    return room_id


def parse_resume_draft_section(st: Any, session: dict[str, Any] | None = None) -> str:
    ss = session if isinstance(session, dict) else {}
    section = str(ss.get("_suite_resume_draft_section") or "").strip().lower()
    pending = pending_resume_query(st) if st is not None else {}
    if not section:
        section = str(pending.get("suite_draft_section") or "").strip().lower()
    if not section and st is not None:
        section = _qp_get(st, "suite_draft_section").strip().lower()
    resume = ""
    if st is not None:
        resume = _qp_get(st, "suite_resume")
    if not resume:
        resume = str(pending.get("suite_resume") or "").strip()
    if not section and resume.startswith("bb:draft_lab:team:"):
        section = "team_analysis"
    return section


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


def _draft_lab_results_nonempty(session: dict[str, Any]) -> bool:
    results = session.get("draft_lab_results")
    if not isinstance(results, dict):
        return False
    draft = results.get("draft")
    if draft is None:
        return False
    try:
        return not getattr(draft, "empty", True)
    except Exception:
        return bool(draft)


def _find_live_room_in_session(session: dict[str, Any], room_id: str) -> dict[str, Any] | None:
    rid = str(room_id or "").strip().upper()
    if not rid:
        return None
    for key in ("live_draft_room", "live_draft_state"):
        blob = session.get(key)
        if isinstance(blob, dict) and str(blob.get("draft_room_id") or "").strip().upper() == rid:
            return blob
    return None


def _load_room_from_cloud_session(session: dict[str, Any], room_id: str) -> dict[str, Any] | None:
    rid = str(room_id or "").strip().upper()
    if not rid:
        return None
    try:
        from live_draft_state import _live_draft_from_blob, room_from_persist_dict
        from suite_storage_supabase import load_current_state_for_app
    except ImportError:
        return None
    try:
        cloud = load_current_state_for_app("baseball")
    except Exception:
        return None
    metrics = cloud.get("metrics") if isinstance(cloud.get("metrics"), dict) else {}
    full = metrics.get("full_session") if isinstance(metrics.get("full_session"), dict) else {}
    blob = _live_draft_from_blob(full)
    if not isinstance(blob, dict):
        blob = _live_draft_from_blob(cloud)
    if not isinstance(blob, dict):
        return None
    if str(blob.get("draft_room_id") or "").strip().upper() != rid:
        return None
    restored = room_from_persist_dict(blob)
    return restored if isinstance(restored, dict) else None


def load_completed_room_for_resume(
    session: dict[str, Any],
    room_id: str,
    *,
    st: Any | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Load a completed live draft room from session, shared store, or cloud state."""
    rid = str(room_id or "").strip()
    if not rid:
        return None, ""

    room = _find_live_room_in_session(session, rid)
    if isinstance(room, dict):
        return room, "session_live_draft_room"

    try:
        from draft_room_shared_state import document_to_runtime_room, find_shared_room_document_by_draft_room_id

        doc, source = find_shared_room_document_by_draft_room_id(rid)
        if isinstance(doc, dict):
            runtime = document_to_runtime_room(doc)
            if isinstance(runtime, dict):
                session["active_shared_draft_room_code"] = str(doc.get("room_code") or "").strip().upper()
                return runtime, source or "shared_room"
    except ImportError:
        pass

    cloud_room = _load_room_from_cloud_session(session, rid)
    if isinstance(cloud_room, dict):
        return cloud_room, "cloud_full_session"

    return None, ""


def _room_is_complete(room: dict[str, Any]) -> bool:
    status = str(room.get("status") or "").strip().lower()
    if status == "complete":
        return True
    try:
        from live_draft_safe_mode import is_draft_truly_complete

        return bool(is_draft_truly_complete(room))
    except ImportError:
        return False


def _apply_draft_section_preference(session: dict[str, Any], section: str) -> None:
    sec = str(section or "").strip().lower()
    if not sec:
        return
    session["_suite_resume_draft_section"] = sec
    if sec == "team_analysis":
        session["draft_lab_preferred_tab"] = "Team Analysis"
        pf = session.setdefault("page_filter_state", {})
        if isinstance(pf, dict):
            block = pf.setdefault(DRAFT_LAB_RESUME_PAGE, {})
            if isinstance(block, dict):
                block["preferred_tab"] = "Team Analysis"


def schedule_draft_lab_resume_navigation(st: Any, *, page: str, room_id: str = "", section: str = "") -> None:
    """Force target draft page to win over default Historical Explorer restore."""
    target = str(page or DRAFT_LAB_RESUME_PAGE).strip() or DRAFT_LAB_RESUME_PAGE
    if _is_draft_lab_page(target):
        target = DRAFT_LAB_PAGE
    ss = st.session_state
    pending = pending_resume_query(st)
    resume_key = str(pending.get("suite_resume") or "").strip()
    if not resume_key and room_id:
        if target == "Live Draft Room":
            resume_key = f"bb:live_draft:{room_id}"
        else:
            resume_key = f"bb:draft_lab:{room_id}"
    try:
        from shared_draft_context import is_fresh_resume_request

        fresh = is_fresh_resume_request(ss, resume_key)
    except ImportError:
        fresh = bool(resume_key)
    if draft_lab_resume_consumed(ss) and not resume_requested(ss) and not fresh:
        return
    mark_resume_requested(ss)
    if room_id:
        ss["_suite_resume_draft_room"] = str(room_id).strip()
    if section:
        ss["_suite_resume_draft_section"] = str(section).strip().lower()
    try:
        from suite_user_persistence import claim_user_page_ownership

        claim_user_page_ownership(st, "baseball", target)
    except ImportError:
        pass
    ss["_navigate_to_page"] = target
    ss["active_page"] = target
    ss["_skip_page_restore_for"] = target
    ss["_suite_page_user_nav"] = True
    ss["_suite_nav_consumed_this_run"] = False
    ss["_suite_nav_consumed_target"] = target
    ss["active_page_source"] = "suite_resume_launch"


def _push_analysis_to_session(room: dict[str, Any]) -> bool:
    from streamlit_app import live_draft_push_analysis_to_session

    return bool(live_draft_push_analysis_to_session(room))


def apply_draft_lab_resume(st: Any) -> dict[str, Any]:
    """Rebuild or confirm draft_lab_results for a resume deep link."""
    ss = st.session_state
    try:
        from live_draft_start_progress import is_live_draft_start_in_flight

        if is_live_draft_start_in_flight(ss):
            diag = {"draft_lab_results_status": "skipped_live_draft_start_in_flight"}
            diag.update(_resume_diag_flags(ss))
            ss[DRAFT_LAB_RESUME_DIAG_KEY] = diag
            return diag
        from live_draft_state import has_active_live_draft

        live = ss.get("live_draft_room")
        if has_active_live_draft(ss) and isinstance(live, dict) and str(live.get("status") or "") in ("in_progress", "paused"):
            diag = {"draft_lab_results_status": "skipped_active_live_draft"}
            diag.update(_resume_diag_flags(ss))
            ss[DRAFT_LAB_RESUME_DIAG_KEY] = diag
            return diag
    except ImportError:
        pass
    diag: dict[str, Any] = {
        "draft_lab_results_status": "not_requested",
        "rebuild_attempted": False,
        "rebuild_success": False,
        "room_load_source": "",
    }
    diag.update(_resume_diag_flags(ss))

    room_id = parse_resume_room_id(st, ss)
    if draft_lab_resume_consumed(ss):
        if _draft_lab_results_nonempty(ss):
            diag["draft_lab_results_status"] = "resume_completed"
            diag["draft_lab_results_after"] = True
            ss[DRAFT_LAB_RESUME_DIAG_KEY] = diag
            return diag
        pending_resume = bool(ss.get("_suite_pending_draft_lab_resume"))
        if not room_id and not pending_resume:
            diag["draft_lab_results_status"] = "resume_completed_empty"
            ss[DRAFT_LAB_RESUME_DIAG_KEY] = diag
            return diag

    draft_section = parse_resume_draft_section(st, ss)
    diag["room_id"] = room_id
    diag["draft_section"] = draft_section
    if room_id and not ss.get("_suite_resume_draft_room"):
        ss["_suite_resume_draft_room"] = room_id
    if draft_section:
        _apply_draft_section_preference(ss, draft_section)

    diag["draft_lab_results_before"] = _draft_lab_results_nonempty(ss)
    diag["draft_lab_results_room_id_before"] = _draft_lab_results_room_id(ss)

    pending_resume = bool(ss.get("_suite_pending_draft_lab_resume"))
    if not room_id and not pending_resume:
        ss[DRAFT_LAB_RESUME_DIAG_KEY] = diag
        return diag

    existing_rid = _draft_lab_results_room_id(ss)
    if _draft_lab_results_nonempty(ss) and existing_rid and (not room_id or existing_rid.upper() == room_id.upper()):
        diag["draft_lab_results_status"] = "already_in_session"
        diag["rebuild_success"] = True
        diag["draft_lab_results_after"] = True
        finalize_draft_lab_resume(st, applied=True)
        diag.update(_resume_diag_flags(ss))
        ss[DRAFT_LAB_RESUME_DIAG_KEY] = diag
        return diag

    if not room_id:
        diag["draft_lab_results_status"] = "missing_room_id"
        if pending_resume:
            ss[DRAFT_LAB_RESUME_ERROR_KEY] = {
                "room_id": "",
                "message": "Draft analysis could not be restored — no room id in the resume link.",
            }
            finalize_draft_lab_resume(st, applied=False)
            diag.update(_resume_diag_flags(ss))
        ss[DRAFT_LAB_RESUME_DIAG_KEY] = diag
        return diag

    room, load_source = load_completed_room_for_resume(ss, room_id, st=st)
    diag["room_load_source"] = load_source
    if room is None:
        diag["draft_lab_results_status"] = "room_not_found"
        ss[DRAFT_LAB_RESUME_ERROR_KEY] = {
            "room_id": room_id,
            "message": (
                f"Draft analysis could not be restored. Room id: **{room_id}**. "
                "Open **Live Draft Room** and click **Analyze Completed Draft**, or start from the latest completed draft there."
            ),
        }
        finalize_draft_lab_resume(st, applied=False)
        diag.update(_resume_diag_flags(ss))
        ss[DRAFT_LAB_RESUME_DIAG_KEY] = diag
        return diag

    if not _room_is_complete(room):
        diag["draft_lab_results_status"] = "room_not_complete"
        ss[DRAFT_LAB_RESUME_ERROR_KEY] = {
            "room_id": room_id,
            "message": (
                f"Draft room **{room_id}** is not complete yet. "
                "Finish the live draft, then use **Analyze Completed Draft**."
            ),
        }
        finalize_draft_lab_resume(st, applied=False)
        diag.update(_resume_diag_flags(ss))
        ss[DRAFT_LAB_RESUME_DIAG_KEY] = diag
        return diag

    ss["live_draft_room"] = room
    diag["rebuild_attempted"] = True
    try:
        ok = _push_analysis_to_session(room)
        diag["rebuild_success"] = ok
        diag["draft_lab_results_status"] = "rebuilt_from_room" if ok else "rebuild_failed"
        diag["draft_lab_results_after"] = _draft_lab_results_nonempty(ss)
        if ok:
            finalize_draft_lab_resume(st, applied=True)
        else:
            ss[DRAFT_LAB_RESUME_ERROR_KEY] = {
                "room_id": room_id,
                "message": (
                    f"Draft analysis could not be rebuilt from room **{room_id}**. "
                    "Open **Live Draft Room** and click **Analyze Completed Draft**."
                ),
            }
            finalize_draft_lab_resume(st, applied=False)
    except Exception as exc:
        diag["draft_lab_results_status"] = f"rebuild_error:{exc}"
        ss[DRAFT_LAB_RESUME_ERROR_KEY] = {
            "room_id": room_id,
            "message": f"Draft analysis restore failed: {exc}",
        }
        finalize_draft_lab_resume(st, applied=False)
    diag.update(_resume_diag_flags(ss))
    ss[DRAFT_LAB_RESUME_DIAG_KEY] = diag
    return diag


def render_draft_lab_resume_error(st: Any) -> None:
    """Show restore failure instead of a silent empty Draft Lab."""
    err = st.session_state.get(DRAFT_LAB_RESUME_ERROR_KEY)
    if not isinstance(err, dict) or not err.get("message"):
        return
    st.error(str(err.get("message") or "Draft analysis could not be restored."))
    room_id = str(err.get("room_id") or "").strip()
    if room_id:
        st.caption(f"Resume room id: `{room_id}`")


def draft_lab_resume_diagnostics(st: Any) -> dict[str, Any]:
    """Developer panel: parse resume URL + hydration outcome."""
    ss = st.session_state
    pending = pending_resume_query(st)
    resume_key = _qp_get(st, "suite_resume") or pending.get("suite_resume") or ""
    room_id = parse_resume_room_id(st, ss)
    out: dict[str, Any] = {
        "query_params": {k: _qp_get(st, k) for k in (
            "suite_resume",
            "suite_page",
            "suite_draft_room",
            "suite_draft_section",
            "suite_workspace",
        )},
        "pending_resume_query": pending,
        "resume_key": resume_key,
        "parsed_room_id": room_id,
        "parsed_draft_section": parse_resume_draft_section(st, ss),
        "parsed_suite_page": _qp_get(st, "suite_page") or pending.get("suite_page") or "",
        "parsed_suite_resume": resume_key,
        "parsed_suite_draft_room": room_id,
        "parsed_suite_draft_section": parse_resume_draft_section(st, ss),
        "selected_final_page": str(ss.get("active_page") or ""),
        "scheduled_navigate_to_page": str(ss.get("_navigate_to_page") or ""),
        "suite_page_user_nav": bool(ss.get("_suite_page_user_nav")),
        "_suite_resume_draft_room_set": bool(ss.get("_suite_resume_draft_room")),
        "suite_draft_room_query": _qp_get(st, "suite_draft_room") or pending.get("suite_draft_room") or "",
        "pending_draft_lab_resume": bool(ss.get("_suite_pending_draft_lab_resume")),
        "draft_lab_results_before_hydration": _draft_lab_results_nonempty(ss),
        "draft_lab_results_room_id": _draft_lab_results_room_id(ss),
        "auth_preserved_pending_query": bool(pending),
        "last_hydration_diag": dict(ss.get(DRAFT_LAB_RESUME_DIAG_KEY) or {}),
    }
    out.update(_resume_diag_flags(ss))
    out["pending_draft_lab_handoff"] = has_pending_draft_lab_handoff(ss)
    out["draft_lab_results_after_hydration"] = _draft_lab_results_nonempty(ss)
    out["draft_lab_results_room_id_after"] = _draft_lab_results_room_id(ss)
    out["draft_lab_resume_error"] = ss.get(DRAFT_LAB_RESUME_ERROR_KEY)
    out.update(_resume_diag_flags(ss))
    return out


def reapply_pending_baseball_resume(st: Any) -> bool:
    """Re-schedule navigation from pending query after auth reruns clear URL params."""
    ss = st.session_state
    pending = pending_resume_query(st)
    if not pending:
        return False
    page = str(pending.get("suite_page") or "").strip()
    resume = str(pending.get("suite_resume") or "").strip()
    room_id = str(pending.get("suite_draft_room") or "").strip()
    section = str(pending.get("suite_draft_section") or "").strip().lower()
    if not page and resume.startswith("bb:live_draft:"):
        page = "Live Draft Room"
    if not page and resume.startswith("bb:draft_lab:"):
        page = DRAFT_LAB_RESUME_PAGE
    if not page:
        return False
    current = str(ss.get("active_page") or "").strip()
    if draft_lab_resume_consumed(ss) and current and current != page:
        return False
    if current == page and not ss.get("_suite_pending_draft_lab_resume"):
        return False
    schedule_draft_lab_resume_navigation(st, page=page, room_id=room_id, section=section)
    return True


def apply_baseball_suite_resume(st: Any) -> dict[str, Any]:
    """Hydrate live draft room for Command Center deep links (any target page)."""
    ss = st.session_state
    diag: dict[str, Any] = {"room_hydrated": False, "room_load_source": ""}
    room_id = parse_resume_room_id(st, ss)
    if not room_id:
        return diag
    existing = ss.get("live_draft_room")
    if isinstance(existing, dict) and str(existing.get("draft_room_id") or "").strip().upper() == room_id.upper():
        diag["room_hydrated"] = True
        diag["room_load_source"] = "session_live_draft_room"
        return diag
    room, load_source = load_completed_room_for_resume(ss, room_id, st=st)
    if isinstance(room, dict):
        ss["live_draft_room"] = room
        diag["room_hydrated"] = True
        diag["room_load_source"] = load_source
    return diag
