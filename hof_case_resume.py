"""
Resume Hall of Fame Case Mode on Career Totals from Command Center deep links.

Handles ``bb:hof_case:{slug}`` resume keys — restores filters, HOF mode, target player,
and stages the related Baseball Insight when a question_id is present.

Workspace restore runs first; HOF overlay applies on Career Totals without clobbering
unrelated state (e.g. active live draft).
"""

from __future__ import annotations

import copy
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
HOF_PENDING_OVERLAY_KEY = "_hof_case_pending_overlay"
HOF_PROTECTED_SNAPSHOT_KEY = "_hof_case_protected_workspace_snapshot"
HOF_LAST_SUBMIT_SOURCE_STATE_KEY = "_hof_case_last_submit_source_state"
HOF_LAST_SUBMIT_BUNDLE_KEY = "_hof_case_last_resume_bundle"
HOF_INSIGHT_STAGED_KEY = "_hof_case_insight_staged_for_resume"
HOF_WORKSPACE_RESTORED_KEY = "_hof_case_workspace_restored"

# Session keys not always included in build_baseball_disk_state — captured in submit bundle supplement.
try:
    from baseball_hof_activity import HOF_WORKFLOW_SUPPLEMENT_KEYS
except ImportError:
    HOF_WORKFLOW_SUPPLEMENT_KEYS = frozenset(
        {
            "workflow_recently_viewed",
            "workflow_favorite_targets",
            "draft_assistant_focus_players",
            "draft_queue",
        }
    )

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

# Unrelated workspace keys preserved across HOF resume overlay.
HOF_RESUME_PROTECTED_KEYS = frozenset(
    {
        "live_draft_room",
        "live_draft_state",
        "draft_room_state",
        "draft_room_table",
        "draft_queue",
        "draft_assistant_focus_players",
        "workflow_favorite_targets",
        "draft_shared_settings",
        "room_your_team",
        "room_format",
        "room_team_count",
        "room_rounds",
        "room_window",
        "fantasy_draft_projection_style",
        "allow_free_pool_drafting",
    }
)


def hof_case_resume_requested(session: dict[str, Any]) -> bool:
    return bool(
        session.get(HOF_CASE_RESUME_REQUESTED_KEY)
        or session.get(HOF_CASE_RESUME_PENDING_KEY)
        or isinstance(session.get(HOF_PENDING_OVERLAY_KEY), dict)
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


def snapshot_protected_workspace(session: dict[str, Any]) -> dict[str, Any]:
    snap: dict[str, Any] = {}
    for key in HOF_RESUME_PROTECTED_KEYS:
        if key not in session:
            continue
        try:
            snap[key] = copy.deepcopy(session[key])
        except Exception:
            snap[key] = session[key]
    return snap


def restore_protected_workspace(session: dict[str, Any], snap: dict[str, Any] | None) -> None:
    if not isinstance(snap, dict) or not snap:
        return
    for key, val in snap.items():
        session[key] = copy.deepcopy(val)


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


def _load_hof_source_state(st: Any, *, question_id: str) -> dict[str, Any]:
    source_state: dict[str, Any] = {}
    if question_id:
        try:
            from suite_analytical_question import load_analytical_question_source_state

            loaded = load_analytical_question_source_state(question_id)
            if isinstance(loaded, dict) and loaded:
                source_state = loaded
        except ImportError:
            pass
    if not source_state:
        stored = st.session_state.get(HOF_LAST_SUBMIT_SOURCE_STATE_KEY)
        if isinstance(stored, dict):
            source_state = copy.deepcopy(stored)
    return source_state


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
    ss.pop(HOF_PENDING_OVERLAY_KEY, None)
    ss.pop(HOF_PROTECTED_SNAPSHOT_KEY, None)
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


def _career_filter_keys_from_state(state: dict[str, Any] | None) -> dict[str, Any]:
    """Extract Career Totals filter keys present in a workspace snapshot or session."""
    if not isinstance(state, dict):
        return {}
    out: dict[str, Any] = {}
    try:
        from career_totals_state import is_career_state_key

        cs = state.get("career_state")
        if isinstance(cs, dict) and isinstance(cs.get("filters"), dict):
            for key, val in cs["filters"].items():
                if is_career_state_key(str(key)):
                    out[str(key)] = val
        pf = state.get("page_filter_state")
        if isinstance(pf, dict):
            block = pf.get("Career Totals")
            if isinstance(block, dict):
                for key, val in block.items():
                    if is_career_state_key(str(key)):
                        out[str(key)] = val
        for key, val in state.items():
            if is_career_state_key(str(key)) and key not in out:
                out[str(key)] = val
    except ImportError:
        for key in (
            "career_year_range_filter",
            "career_sort_stat_filter",
            "career_hof_case_mode",
            "career_hof_case_target_player",
            "career_hof_membership_filter",
        ):
            if key in state:
                out[key] = state[key]
        for key, val in state.items():
            if str(key).startswith("career_") and str(key).endswith("_min"):
                out[str(key)] = val
    return out


def apply_hof_case_workspace_restore(
    st: Any,
    workspace_snapshot: dict[str, Any] | None,
    *,
    session_supplement: dict[str, Any] | None = None,
) -> bool:
    """Restore full Baseball Analytics workspace from submit-time snapshot."""
    if not isinstance(workspace_snapshot, dict) or not workspace_snapshot:
        return False
    ss = st.session_state
    ss[HOF_WORKSPACE_RESTORED_KEY] = False
    try:
        from baseball_persistent_state import apply_baseball_disk_state

        ss["_hof_case_workspace_restore_in_progress"] = True
        apply_baseball_disk_state(st, copy.deepcopy(workspace_snapshot))
        if isinstance(session_supplement, dict):
            for key, val in session_supplement.items():
                ss[key] = copy.deepcopy(val)
        try:
            from draft_state import prepare_draft_workflow

            prepare_draft_workflow(ss)
        except ImportError:
            pass
        ss[HOF_WORKSPACE_RESTORED_KEY] = True
        ss["_hof_case_skip_prepare_reconcile"] = True
        return True
    except ImportError:
        return False
    finally:
        ss.pop("_hof_case_workspace_restore_in_progress", None)


def _load_hof_resume_bundle(st: Any, resume_key: str) -> dict[str, Any]:
    bundle: dict[str, Any] = {}
    stored = st.session_state.get(HOF_LAST_SUBMIT_BUNDLE_KEY)
    if isinstance(stored, dict) and str(stored.get("resume_key") or "") == resume_key:
        bundle = copy.deepcopy(stored)
    if not bundle:
        try:
            from baseball_hof_activity import load_hof_case_resume_bundle

            bundle = load_hof_case_resume_bundle(resume_key)
        except ImportError:
            bundle = {}
    return bundle if isinstance(bundle, dict) else {}


def record_hof_case_submit_snapshot(
    session: dict[str, Any],
    source_state: dict[str, Any] | None,
    *,
    resume_bundle: dict[str, Any] | None = None,
) -> None:
    """Persist last HOF submit source_state and workspace bundle for diagnostics."""
    if isinstance(source_state, dict) and source_state:
        session[HOF_LAST_SUBMIT_SOURCE_STATE_KEY] = copy.deepcopy(source_state)
    if isinstance(resume_bundle, dict) and resume_bundle:
        session[HOF_LAST_SUBMIT_BUNDLE_KEY] = copy.deepcopy(resume_bundle)


def _restore_hof_case_insight(
    st: Any,
    *,
    insight_dict: dict[str, Any] | None,
    question_id: str,
    target_player: str,
    resume_key: str,
    source_state: dict[str, Any] | None,
    action_url: str = "",
) -> bool:
    """Stage exactly one Baseball Insight card from submit snapshot or AMI blob."""
    if st.session_state.get(HOF_INSIGHT_STAGED_KEY) == question_id and question_id:
        return bool(st.session_state.get("_ami_pending_insight"))
    try:
        from applied_math_return_insight import SESSION_PENDING_KEY, insight_return_query_id
    except ImportError:
        return False
    if insight_return_query_id(st):
        return False

    if isinstance(insight_dict, dict) and insight_dict.get("insight_id"):
        st.session_state[SESSION_PENDING_KEY] = copy.deepcopy(insight_dict)
        st.session_state["_ami_force_insight_render"] = True
        if isinstance(source_state, dict) and source_state:
            st.session_state["_ami_return_context"] = copy.deepcopy(source_state)
        if question_id:
            st.session_state[HOF_INSIGHT_STAGED_KEY] = question_id
        return True

    return _stage_hof_case_insight_once(
        st,
        question_id=question_id,
        target_player=target_player,
        resume_key=resume_key,
        source_state=source_state,
        action_url=action_url,
    )


def _stage_hof_case_insight_once(
    st: Any,
    *,
    question_id: str,
    target_player: str,
    resume_key: str,
    source_state: dict[str, Any] | None,
    action_url: str = "",
) -> bool:
    if not question_id:
        return False
    if st.session_state.get(HOF_INSIGHT_STAGED_KEY) == question_id:
        return False
    try:
        from applied_math_return_insight import _question_is_dismissed
    except ImportError:
        _question_is_dismissed = lambda _st, _qid: False  # type: ignore[assignment,misc]
    if _question_is_dismissed(st, question_id):
        return False
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
        return False
    if insight_return_query_id(st):
        return False
    payload = load_analytical_question_payload(question_id)
    if not isinstance(payload, dict):
        return False
    question = str(payload.get("question") or "").strip()
    blob_action_url = str(payload.get("action_url") or action_url or "").strip()
    if not blob_action_url:
        try:
            from suite_analytical_question import build_applied_math_resume_url

            blob_action_url = build_applied_math_resume_url(payload)
        except ImportError:
            blob_action_url = str(action_url or "").strip()
    insight = build_submit_fallback_insight(
        question=question,
        source_app="baseball",
        source_page=HOF_CASE_RESUME_PAGE,
        question_id=question_id,
        full_analysis_url=blob_action_url,
        resume_key=resume_key,
    )
    target = str(target_player or "").strip()
    ctx = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    packet = ctx.get("hof_case_packet") if isinstance(ctx.get("hof_case_packet"), dict) else {}
    try:
        from hof_case_analysis import compose_hof_statistical_case, format_hof_case_memo_markdown

        analysis = (
            packet.get("hof_case_analysis")
            if isinstance(packet.get("hof_case_analysis"), dict)
            else compose_hof_statistical_case(packet)
        )
        insight.conclusion = str(
            analysis.get("thesis") or packet.get("hof_case_summary") or ""
        ).strip()
        insight.short_answer = insight.conclusion
        insight.method = f"{CASE_SCORE_LABEL} — {analysis.get('verdict_bucket', '—')}"
        insight.supporting_points = list(analysis.get("supporting_points") or [])[:8]
    except ImportError:
        if packet.get("hof_case_summary"):
            insight.short_answer = str(packet["hof_case_summary"])
        if target:
            rate = packet.get("hall_of_fame_rate_pct")
            total = packet.get("total_players_returned")
            hof_n = packet.get("hall_of_famers_returned")
            cohort = f" Cohort: {hof_n}/{total} HOF ({rate}%)." if total is not None else ""
            insight.conclusion = f"{CASE_SCORE_LABEL} for {target}.{cohort}"
        insight.method = CASE_SCORE_LABEL
    ent_state = source_state if isinstance(source_state, dict) else (
        payload.get("source_state") if isinstance(payload.get("source_state"), dict) else None
    )
    stage_pending_insight(st, insight, return_context=ent_state if ent_state else None)
    st.session_state[SESSION_PENDING_KEY] = insight.to_dict()
    st.session_state["_ami_force_insight_render"] = True
    st.session_state[HOF_INSIGHT_STAGED_KEY] = question_id
    return True


def apply_hof_case_resume(st: Any) -> dict[str, Any]:
    """Schedule HOF resume navigation and queue overlay for after workspace restore."""
    resume = _resume_key_from_pending(st)
    diag: dict[str, Any] = {
        "hof_case_resume_status": "not_requested",
        "resume_key": resume,
        "target_player": "",
        "question_id": "",
        "parsed_query": dict(pending_resume_query(st)),
        "active_page_before": str(st.session_state.get("active_page") or ""),
        "draft_room_status_before": _draft_status_summary(st.session_state),
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

    ss = st.session_state
    bundle = _load_hof_resume_bundle(st, resume)
    workspace_snapshot = bundle.get("workspace_snapshot") if isinstance(bundle.get("workspace_snapshot"), dict) else {}
    workspace_restored = apply_hof_case_workspace_restore(
        st,
        workspace_snapshot,
        session_supplement=bundle.get("session_supplement")
        if isinstance(bundle.get("session_supplement"), dict)
        else None,
    )
    diag["workspace_snapshot_found"] = bool(workspace_snapshot)
    diag["workspace_restored"] = workspace_restored
    diag["workspace_career_filters_captured"] = _career_filter_keys_from_state(workspace_snapshot)
    diag["draft_room_status_after_workspace"] = _draft_status_summary(ss)

    source_state = _load_hof_source_state(st, question_id=qid)
    if not source_state and isinstance(bundle.get("source_state"), dict):
        source_state = copy.deepcopy(bundle["source_state"])
    ss[HOF_PENDING_OVERLAY_KEY] = {
        "source_state": copy.deepcopy(source_state) if source_state else {},
        "target_player": target,
        "question_id": qid,
        "resume_key": resume,
        "resume_bundle": copy.deepcopy(bundle) if bundle else {},
        "workspace_restored": workspace_restored,
    }

    schedule_hof_case_resume_navigation(st, target_player=target, question_id=qid)

    try:
        from hall_of_fame_data import CAREER_HOF_CASE_MODE_KEY, CAREER_HOF_CASE_TARGET_KEY

        ss[CAREER_HOF_CASE_MODE_KEY] = True
        if target:
            ss[CAREER_HOF_CASE_TARGET_KEY] = target
    except ImportError:
        ss["career_hof_case_mode"] = True
        if target:
            ss["career_hof_case_target_player"] = target

    diag["hof_case_resume_status"] = "overlay_queued"
    diag["overlay_has_source_state"] = bool(source_state)
    diag["active_page_after_schedule"] = str(ss.get("active_page") or "")
    ss[HOF_CASE_RESUME_DIAG_KEY] = diag
    return diag


def apply_pending_hof_case_overlay(st: Any) -> dict[str, Any]:
    """Apply queued HOF overlay on Career Totals after page filters reconcile."""
    ss = st.session_state
    pending = ss.get(HOF_PENDING_OVERLAY_KEY)
    diag: dict[str, Any] = {
        "overlay_applied": False,
        "active_page": str(ss.get("active_page") or ""),
        "workspace_restored": bool(ss.get(HOF_WORKSPACE_RESTORED_KEY)),
        "draft_room_status_before": _draft_status_summary(ss),
    }
    if not isinstance(pending, dict):
        return diag

    bundle = pending.get("resume_bundle") if isinstance(pending.get("resume_bundle"), dict) else {}
    source_state = pending.get("source_state") if isinstance(pending.get("source_state"), dict) else {}
    target = str(pending.get("target_player") or bundle.get("target_player") or "").strip()
    qid = str(pending.get("question_id") or bundle.get("question_id") or "").strip()
    resume_key = str(pending.get("resume_key") or bundle.get("resume_key") or "").strip()
    action_url = str(bundle.get("action_url") or "").strip()
    workspace_restored = bool(pending.get("workspace_restored") or ss.get(HOF_WORKSPACE_RESTORED_KEY))

    if not workspace_restored and isinstance(bundle.get("workspace_snapshot"), dict):
        workspace_restored = apply_hof_case_workspace_restore(
            st,
            bundle["workspace_snapshot"],
            session_supplement=bundle.get("session_supplement")
            if isinstance(bundle.get("session_supplement"), dict)
            else None,
        )

    if source_state and not workspace_restored:
        try:
            from applied_math_context import apply_source_state_to_session

            apply_source_state_to_session(ss, source_state, schedule_navigation=False)
        except ImportError:
            try:
                from career_totals_state import (
                    apply_career_source_state_from_ami,
                    apply_pending_career_filter_restore,
                )

                apply_career_source_state_from_ami(ss, source_state)
                apply_pending_career_filter_restore(ss)
            except ImportError:
                pass
    elif source_state and workspace_restored:
        try:
            from career_totals_state import (
                apply_career_source_state_from_ami,
                apply_pending_career_filter_restore,
            )

            apply_career_source_state_from_ami(ss, source_state)
            apply_pending_career_filter_restore(ss)
        except ImportError:
            pass

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

    ss[CAREER_HOF_CASE_MODE_KEY] = True
    if target:
        ss[CAREER_HOF_CASE_TARGET_KEY] = target
    ent = source_state.get("entity_params") if isinstance(source_state.get("entity_params"), dict) else {}
    packet = ent.get("hof_case_packet")
    if not isinstance(packet, dict):
        packet = bundle.get("hof_case_packet")
    if isinstance(packet, dict):
        ss[HOF_CASE_PACKET_KEY] = copy.deepcopy(packet)

    insight_dict = bundle.get("insight") if isinstance(bundle.get("insight"), dict) else None
    insight_staged = _restore_hof_case_insight(
        st,
        insight_dict=insight_dict,
        question_id=qid,
        target_player=target,
        resume_key=resume_key,
        source_state=source_state,
        action_url=action_url,
    )

    ss.pop(HOF_PENDING_OVERLAY_KEY, None)
    diag["overlay_applied"] = True
    diag["insight_staged"] = insight_staged
    diag["career_filters_after_overlay"] = _career_filter_keys_from_state(ss)
    diag["draft_room_status_after"] = _draft_status_summary(ss)
    diag["career_year_range"] = ss.get("career_year_range_filter")
    diag["career_hr_min"] = ss.get("career_HR_min")
    diag["draft_queue_len"] = len(ss.get("draft_queue") or [])
    diag["watchlist_len"] = len(ss.get("draft_assistant_focus_players") or [])
    diag["tracked_len"] = len(ss.get("workflow_recently_viewed") or [])
    prev = dict(ss.get(HOF_CASE_RESUME_DIAG_KEY) or {})
    prev.update(diag)
    prev["hof_case_resume_status"] = "overlay_applied"
    ss[HOF_CASE_RESUME_DIAG_KEY] = prev
    return diag


def _draft_status_summary(session: dict[str, Any]) -> dict[str, Any]:
    room = session.get("live_draft_room")
    if not isinstance(room, dict):
        return {"has_room": False}
    return {
        "has_room": True,
        "status": str(room.get("status") or ""),
        "draft_room_id": str(room.get("draft_room_id") or ""),
        "picks": len(room.get("draft_board") or []),
    }


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
        prev = dict(ss.get(HOF_CASE_RESUME_DIAG_KEY) or {})
        prev.update(
            {
                "page_reforced_after_workspace": True,
                "page_before_enforce": current,
            }
        )
        ss[HOF_CASE_RESUME_DIAG_KEY] = prev
        return True
    return False


def finalize_hof_case_resume_if_ready(st: Any) -> bool:
    """Mark resume complete once Career Totals is active and overlay has been applied."""
    ss = st.session_state
    resume = _resume_key_from_pending(st)
    if not resume.startswith("bb:hof_case:") and not hof_case_resume_requested(ss):
        return False
    if hof_case_resume_consumed(ss):
        return False
    if isinstance(ss.get(HOF_PENDING_OVERLAY_KEY), dict):
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


def render_hof_case_resume_debug(st: Any, *, developer_mode: bool = False) -> None:
    """Developer diagnostics for Hall of Fame Case resume flow."""
    if not developer_mode:
        return
    ss = st.session_state
    diag = dict(ss.get(HOF_CASE_RESUME_DIAG_KEY) or {})
    if not diag and not hof_case_resume_requested(ss):
        return
    qid = str(diag.get("question_id") or _question_id_from_pending(st) or "").strip()
    resume = str(diag.get("resume_key") or _resume_key_from_pending(st) or "").strip()
    bundle = _load_hof_resume_bundle(st, resume) if resume else {}
    blob_found = False
    action_url = str(bundle.get("action_url") or "").strip()
    if qid:
        try:
            from suite_analytical_question import load_analytical_question_payload

            payload = load_analytical_question_payload(qid)
            blob_found = bool(payload)
            if not action_url:
                action_url = str(payload.get("action_url") or "").strip()
        except ImportError:
            pass
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
                "career_year_range": ss.get("career_year_range_filter"),
                "career_hr_min": ss.get("career_HR_min"),
                "career_hof_filter": ss.get("career_hof_membership_filter"),
                "packet_target": (ss.get("_hof_case_packet") or {}).get("target_player")
                if isinstance(ss.get("_hof_case_packet"), dict)
                else None,
                "workspace_snapshot_found": bool(bundle.get("workspace_snapshot")),
                "workspace_restored": bool(ss.get(HOF_WORKSPACE_RESTORED_KEY)),
                "career_filters_in_snapshot": _career_filter_keys_from_state(
                    bundle.get("workspace_snapshot") if isinstance(bundle.get("workspace_snapshot"), dict) else {}
                ),
                "career_filters_in_session": _career_filter_keys_from_state(ss),
                "ami_question_id": qid,
                "ami_action_url": action_url,
                "ami_blob_found": blob_found,
                "insight_in_bundle": bool(bundle.get("insight")),
                "insight_pending": bool(ss.get("_ami_pending_insight")),
                "insight_staged_key": ss.get(HOF_INSIGHT_STAGED_KEY),
                "insight_cards_rendered": ss.get("_hof_insight_render_count"),
                "draft_queue_len": len(ss.get("draft_queue") or []),
                "watchlist_len": len(ss.get("draft_assistant_focus_players") or []),
                "tracked_len": len(ss.get("workflow_recently_viewed") or []),
                "draft_room_status": _draft_status_summary(ss),
                "last_submit_source_state": bool(ss.get(HOF_LAST_SUBMIT_SOURCE_STATE_KEY)),
                "last_submit_bundle": bool(ss.get(HOF_LAST_SUBMIT_BUNDLE_KEY)),
                "last_submit_diag": ss.get("_hof_case_last_submit_diag"),
                "ami_blob_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
                "ami_blob_type": (payload or {}).get("blob_type") if isinstance(payload, dict) else None,
                "ami_app_context_type": (payload or {}).get("app_context_type") if isinstance(payload, dict) else None,
                "last_diag": diag,
            }
        )
