"""
Resume Hall of Fame Case Mode on Career Totals from Command Center deep links.

Handles ``bb:hof_case:{slug}`` resume keys — restores filters, HOF mode, target player,
and stages the related Baseball Insight when a question_id is present.
"""

from __future__ import annotations

from typing import Any

try:
    from draft_lab_resume import PENDING_RESUME_QUERY_KEY, _qp_get, pending_resume_query
except ImportError:
    PENDING_RESUME_QUERY_KEY = "_suite_pending_resume_query"

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

    def pending_resume_query(st: Any) -> dict[str, str]:
        raw = st.session_state.get(PENDING_RESUME_QUERY_KEY)
        return dict(raw) if isinstance(raw, dict) else {}


HOF_CASE_RESUME_PAGE = "Career Totals"
HOF_CASE_RESUME_REQUESTED_KEY = "_hof_case_resume_requested"
HOF_CASE_RESUME_COMPLETED_KEY = "_hof_case_resume_completed"
HOF_CASE_RESUME_PENDING_KEY = "_suite_pending_hof_case_resume"
HOF_CASE_RESUME_DIAG_KEY = "_hof_case_resume_last_diag"
HOF_CASE_RESUME_QUERY_KEYS = frozenset(
    {
        "suite_resume",
        "suite_page",
        "suite_hof_target",
        "suite_hof_case",
        "suite_ai_question_id",
        "suite_ami_insight",
        "suite_workspace",
    }
)


def hof_case_resume_requested(session: dict[str, Any]) -> bool:
    return bool(
        session.get(HOF_CASE_RESUME_REQUESTED_KEY)
        or session.get(HOF_CASE_RESUME_PENDING_KEY)
    )


def hof_case_resume_consumed(session: dict[str, Any]) -> bool:
    return bool(session.get(HOF_CASE_RESUME_COMPLETED_KEY))


def forced_hof_case_page_active(session: dict[str, Any]) -> bool:
    pending = bool(session.get(HOF_CASE_RESUME_PENDING_KEY))
    nav = str(session.get("_navigate_to_page") or "").strip()
    skip = str(session.get("_skip_page_restore_for") or "").strip()
    active = str(session.get("active_page") or "").strip()
    return (
        pending
        or nav == HOF_CASE_RESUME_PAGE
        or skip == HOF_CASE_RESUME_PAGE
        or (hof_case_resume_requested(session) and active == HOF_CASE_RESUME_PAGE)
    )


def _resume_key_from_pending(st: Any) -> str:
    pending = pending_resume_query(st)
    return str(pending.get("suite_resume") or _qp_get(st, "suite_resume") or "").strip()


def _target_from_pending(st: Any) -> str:
    pending = pending_resume_query(st)
    target = str(pending.get("suite_hof_target") or _qp_get(st, "suite_hof_target") or "").strip()
    if target and "-" in target and " " not in target:
        try:
            from hall_of_fame_data import resolve_hof_case_target_slug

            resolved = resolve_hof_case_target_slug(target)
            if resolved:
                return resolved
        except ImportError:
            pass
    if target:
        return target
    resume = _resume_key_from_pending(st)
    if resume.startswith("bb:hof_case:"):
        slug = resume.split(":", 2)[-1].strip()
        try:
            from hall_of_fame_data import resolve_hof_case_target_slug

            return resolve_hof_case_target_slug(slug)
        except ImportError:
            return slug.replace("-", " ").title()
    return ""


def _question_id_from_pending(st: Any) -> str:
    pending = pending_resume_query(st)
    return str(pending.get("suite_ai_question_id") or _qp_get(st, "suite_ai_question_id") or "").strip()


def schedule_hof_case_resume_navigation(
    st: Any,
    *,
    page: str = HOF_CASE_RESUME_PAGE,
    target_player: str = "",
    question_id: str = "",
) -> None:
    """Force Career Totals to win over default Historical Explorer restore."""
    target = str(page or HOF_CASE_RESUME_PAGE).strip() or HOF_CASE_RESUME_PAGE
    ss = st.session_state
    ss[HOF_CASE_RESUME_REQUESTED_KEY] = True
    ss[HOF_CASE_RESUME_PENDING_KEY] = True
    ss["_navigate_to_page"] = target
    ss["active_page"] = target
    ss["main_sidebar_page"] = target
    ss["_skip_page_restore_for"] = target
    ss["_suite_page_user_nav"] = True
    ss["active_page_source"] = "suite_resume_launch"
    if target_player:
        ss["_pending_hof_case_target"] = str(target_player).strip()
    if question_id:
        ss["_pending_hof_case_question_id"] = str(question_id).strip()
    try:
        from suite_user_persistence import claim_user_page_ownership

        claim_user_page_ownership(st, "baseball", target)
    except ImportError:
        pass
    ss["_navigate_to_page"] = target
    ss["_skip_page_restore_for"] = target
    ss["active_page"] = target
    ss["main_sidebar_page"] = target


def _clear_pending_resume_query_hof(session: dict[str, Any]) -> None:
    pending = session.get(PENDING_RESUME_QUERY_KEY)
    if not isinstance(pending, dict):
        return
    for key in HOF_CASE_RESUME_QUERY_KEYS:
        pending.pop(key, None)
    if pending:
        session[PENDING_RESUME_QUERY_KEY] = pending
    else:
        session.pop(PENDING_RESUME_QUERY_KEY, None)


def clear_hof_resume_query_params(st: Any) -> None:
    try:
        qp = st.query_params
        for key in HOF_CASE_RESUME_QUERY_KEYS:
            if key in qp:
                del qp[key]
    except Exception:
        pass


def finalize_hof_case_resume(st: Any, *, applied: bool = True) -> None:
    """One-shot completion — release navigation locks after resume/hydration."""
    ss = st.session_state
    ss[HOF_CASE_RESUME_COMPLETED_KEY] = True
    pending = dict(ss.get(PENDING_RESUME_QUERY_KEY) or {})
    resume_key = str(pending.get("suite_resume") or _qp_get(st, "suite_resume") or "").strip()
    if resume_key:
        try:
            from shared_draft_context import mark_resume_key_consumed

            mark_resume_key_consumed(ss, resume_key)
        except ImportError:
            ss["_suite_last_consumed_resume_key"] = resume_key
    ss.pop(HOF_CASE_RESUME_PENDING_KEY, None)
    if str(ss.get("_navigate_to_page") or "").strip() == HOF_CASE_RESUME_PAGE:
        ss.pop("_navigate_to_page", None)
    if str(ss.get("_skip_page_restore_for") or "").strip() == HOF_CASE_RESUME_PAGE:
        ss.pop("_skip_page_restore_for", None)
    _clear_pending_resume_query_hof(ss)
    clear_hof_resume_query_params(st)
    if applied:
        ss.pop("_hof_case_resume_error", None)


def cancel_hof_case_resume_navigation(st: Any, user_page: str) -> None:
    """User picked a different page — stop forcing Career Totals."""
    ss = st.session_state
    if not hof_case_resume_requested(ss) and not forced_hof_case_page_active(ss):
        return
    target = str(user_page or "").strip()
    if target and target != HOF_CASE_RESUME_PAGE:
        finalize_hof_case_resume(st, applied=hof_case_resume_consumed(ss))


def _stage_hof_case_insight(st: Any, *, question_id: str, target_player: str, resume_key: str) -> None:
    if not question_id:
        return
    try:
        from applied_math_return_insight import (
            SESSION_PENDING_KEY,
            build_submit_fallback_insight,
            insight_return_query_id,
            stage_pending_insight,
        )
        from hall_of_fame_data import CASE_SCORE_LABEL
        from suite_analytical_question import load_analytical_question_payload
    except ImportError:
        return
    if insight_return_query_id(st):
        return
    payload = load_analytical_question_payload(question_id)
    if not isinstance(payload, dict):
        return
    question = str(payload.get("question") or "").strip()
    action_url = str(payload.get("action_url") or "").strip()
    insight = build_submit_fallback_insight(
        question=question,
        source_app="baseball",
        source_page=HOF_CASE_RESUME_PAGE,
        question_id=question_id,
        full_analysis_url=action_url,
        resume_key=resume_key,
    )
    target = str(target_player or "").strip()
    if target:
        insight.conclusion = f"{CASE_SCORE_LABEL} queued for {target}."
    insight.method = CASE_SCORE_LABEL
    source_state = payload.get("source_state") if isinstance(payload.get("source_state"), dict) else {}
    stage_pending_insight(st, insight, return_context=source_state if source_state else None)
    st.session_state[SESSION_PENDING_KEY] = insight.to_dict()
    st.session_state["_ami_force_insight_render"] = True


def apply_hof_case_resume(st: Any) -> dict[str, Any]:
    """Hydrate Hall of Fame Case Mode session state from a resume deep link."""
    resume = _resume_key_from_pending(st)
    diag: dict[str, Any] = {
        "hof_case_resume_status": "not_requested",
        "resume_key": resume,
        "target_player": "",
        "question_id": "",
        "parsed_query": dict(pending_resume_query(st)),
        "final_page_before": str(st.session_state.get("active_page") or ""),
    }
    if not resume.startswith("bb:hof_case:"):
        st.session_state[HOF_CASE_RESUME_DIAG_KEY] = diag
        return diag

    if hof_case_resume_consumed(st.session_state) and not forced_hof_case_page_active(st.session_state):
        diag["hof_case_resume_status"] = "already_completed"
        st.session_state[HOF_CASE_RESUME_DIAG_KEY] = diag
        return diag

    diag["hof_case_resume_status"] = "requested"
    target = _target_from_pending(st)
    qid = _question_id_from_pending(st)
    diag["target_player"] = target
    diag["question_id"] = qid

    schedule_hof_case_resume_navigation(st, target_player=target, question_id=qid)

    try:
        from hall_of_fame_data import (
            CAREER_HOF_CASE_MODE_KEY,
            CAREER_HOF_CASE_TARGET_KEY,
            HOF_CASE_PACKET_KEY,
        )
    except ImportError:
        CAREER_HOF_CASE_MODE_KEY = "career_hof_case_mode"
        CAREER_HOF_CASE_TARGET_KEY = "career_hof_case_target_player"
        HOF_CASE_PACKET_KEY = "_hof_case_packet"

    ss = st.session_state
    ss[CAREER_HOF_CASE_MODE_KEY] = True
    if target:
        ss[CAREER_HOF_CASE_TARGET_KEY] = target

    source_state: dict[str, Any] = {}
    if qid:
        try:
            from suite_analytical_question import load_analytical_question_source_state

            loaded = load_analytical_question_source_state(qid)
            if isinstance(loaded, dict):
                source_state = loaded
        except ImportError:
            pass

    if source_state:
        try:
            from career_totals_state import apply_career_source_state_from_ami

            apply_career_source_state_from_ami(ss, source_state)
        except ImportError:
            try:
                from applied_math_context import apply_source_state_to_session

                apply_source_state_to_session(ss, source_state, schedule_navigation=False)
            except ImportError:
                pass
        ent = source_state.get("entity_params") if isinstance(source_state.get("entity_params"), dict) else {}
        packet = ent.get("hof_case_packet")
        if isinstance(packet, dict):
            ss[HOF_CASE_PACKET_KEY] = packet
        if ent.get("hof_case_target"):
            ss[CAREER_HOF_CASE_TARGET_KEY] = str(ent["hof_case_target"])
        if ent.get("hof_case_mode"):
            ss[CAREER_HOF_CASE_MODE_KEY] = True

    _stage_hof_case_insight(st, question_id=qid, target_player=target, resume_key=resume)
    diag["hof_case_resume_status"] = "applied"
    diag["final_page_after"] = str(ss.get("active_page") or "")
    ss[HOF_CASE_RESUME_DIAG_KEY] = diag
    return diag


def enforce_hof_case_page_after_workspace(st: Any) -> bool:
    """Re-force Career Totals after workspace blob overwrote the resume page."""
    ss = st.session_state
    resume = _resume_key_from_pending(st)
    if not resume.startswith("bb:hof_case:"):
        return False
    if hof_case_resume_consumed(ss) and not forced_hof_case_page_active(ss):
        return False
    current = str(ss.get("active_page") or "").strip()
    if current != HOF_CASE_RESUME_PAGE:
        schedule_hof_case_resume_navigation(
            st,
            target_player=_target_from_pending(st),
            question_id=_question_id_from_pending(st),
        )
        ss[HOF_CASE_RESUME_DIAG_KEY] = {
            **dict(ss.get(HOF_CASE_RESUME_DIAG_KEY) or {}),
            "page_reforced_after_workspace": True,
            "page_before_enforce": current,
        }
        return True
    return False


def finalize_hof_case_resume_if_ready(st: Any) -> bool:
    """Mark resume complete once Career Totals is the active page."""
    ss = st.session_state
    resume = _resume_key_from_pending(st)
    if not resume.startswith("bb:hof_case:") and not hof_case_resume_requested(ss):
        return False
    if hof_case_resume_consumed(ss):
        return False
    active = str(ss.get("active_page") or "").strip()
    if active == HOF_CASE_RESUME_PAGE:
        finalize_hof_case_resume(st, applied=True)
        return True
    return False


def reapply_pending_hof_case_resume(st: Any) -> bool:
    """Re-schedule Career Totals navigation after auth reruns clear URL params."""
    resume = _resume_key_from_pending(st)
    if not resume.startswith("bb:hof_case:"):
        return False
    pending = pending_resume_query(st)
    page = str(pending.get("suite_page") or _qp_get(st, "suite_page") or HOF_CASE_RESUME_PAGE).strip()
    if not page:
        page = HOF_CASE_RESUME_PAGE
    if hof_case_resume_consumed(st.session_state) and not forced_hof_case_page_active(st.session_state):
        return False
    schedule_hof_case_resume_navigation(
        st,
        page=page,
        target_player=_target_from_pending(st),
        question_id=_question_id_from_pending(st),
    )
    return True


def render_hof_case_resume_debug(st: Any) -> None:
    """Developer diagnostics for Hall of Fame Case resume flow."""
    ss = st.session_state
    diag = dict(ss.get(HOF_CASE_RESUME_DIAG_KEY) or {})
    if not diag and not hof_case_resume_requested(ss):
        return
    with st.expander("Developer: Hall of Fame Case resume", expanded=False):
        st.json(
            {
                "resume_requested": hof_case_resume_requested(ss),
                "resume_completed": hof_case_resume_consumed(ss),
                "forced_page_active": forced_hof_case_page_active(ss),
                "active_page": ss.get("active_page"),
                "pending_query": pending_resume_query(st),
                "hof_case_mode": ss.get("career_hof_case_mode"),
                "hof_case_target": ss.get("career_hof_case_target_player"),
                "packet_target": (ss.get("_hof_case_packet") or {}).get("target_player")
                if isinstance(ss.get("_hof_case_packet"), dict)
                else None,
                "last_diag": diag,
            }
        )
