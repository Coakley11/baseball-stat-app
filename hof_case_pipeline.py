"""Hall of Fame case publish/handoff pipeline tracing (Developer Mode diagnostics)."""

from __future__ import annotations

import traceback
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

HOF_PIPELINE_STATUS_KEY = "_hof_case_pipeline_status"
HOF_PIPELINE_ERRORS_KEY = "_hof_case_pipeline_errors"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def init_hof_pipeline_run(session: dict[str, Any], *, target_player: str = "") -> None:
    """Start a fresh pipeline trace for one HOF submit attempt."""
    session[HOF_PIPELINE_STATUS_KEY] = {
        "started_at": _utc_now(),
        "target_player": str(target_player or "").strip(),
        "steps": {},
    }
    session[HOF_PIPELINE_ERRORS_KEY] = []


def record_hof_pipeline_step(
    session: dict[str, Any],
    step: str,
    *,
    ok: bool,
    detail: Any = None,
    error: str = "",
) -> None:
    """Record one pipeline step outcome (yes/no + optional detail)."""
    status = session.get(HOF_PIPELINE_STATUS_KEY)
    if not isinstance(status, dict):
        status = {"steps": {}}
        session[HOF_PIPELINE_STATUS_KEY] = status
    steps = status.setdefault("steps", {})
    if not isinstance(steps, dict):
        steps = {}
        status["steps"] = steps
    entry: dict[str, Any] = {
        "ok": bool(ok),
        "at": _utc_now(),
    }
    if detail is not None:
        entry["detail"] = detail
    if error:
        entry["error"] = str(error)[:500]
    steps[str(step)] = entry
    if error:
        errors = session.get(HOF_PIPELINE_ERRORS_KEY)
        if not isinstance(errors, list):
            errors = []
            session[HOF_PIPELINE_ERRORS_KEY] = errors
        errors.append({"step": str(step), "error": str(error)[:500], "at": entry["at"]})


def record_hof_pipeline_exception(session: dict[str, Any], step: str, exc: BaseException) -> None:
    """Capture exception type + message for Developer Mode."""
    record_hof_pipeline_step(
        session,
        step,
        ok=False,
        error=f"{type(exc).__name__}: {exc}",
        detail=traceback.format_exc(limit=4)[-600:],
    )


def _deploy_info() -> dict[str, str]:
    try:
        from suite_deploy_marker import (
            format_build_label,
            resolve_commit_source,
            resolve_git_branch,
            resolve_git_commit_short,
        )

        return {
            "deploy_commit": resolve_git_commit_short(),
            "deploy_commit_source": resolve_commit_source(),
            "deploy_branch": resolve_git_branch(),
            "build_label": format_build_label(),
        }
    except ImportError:
        return {"deploy_commit": "unknown", "deploy_commit_source": "unknown", "deploy_branch": "unknown"}


def _url_param_summary(url: str) -> dict[str, str]:
    raw = str(url or "").strip()
    if not raw:
        return {}
    try:
        parsed = urlparse(raw)
        qs = parse_qs(parsed.query)
        keys = (
            "suite_ai_question_id",
            "suite_hof_case",
            "suite_hof_target",
            "suite_ai_area",
            "suite_ai_source_app",
            "suite_workspace",
        )
        out: dict[str, str] = {}
        for key in keys:
            vals = qs.get(key)
            if vals and str(vals[0]).strip():
                out[key] = str(vals[0]).strip()
        return out
    except Exception:
        return {}


def build_hof_pipeline_status(session: dict[str, Any]) -> dict[str, Any]:
    """Live snapshot for Developer Mode HOF pipeline panel."""
    from applied_math_return_insight import SESSION_PENDING_KEY

    try:
        from hof_case_analysis import resolve_hof_case_analysis
    except ImportError:
        resolve_hof_case_analysis = None  # type: ignore[assignment,misc]

    try:
        from hall_of_fame_data import HOF_CASE_PACKET_KEY
    except ImportError:
        HOF_CASE_PACKET_KEY = "_hof_case_packet"

    packet = session.get(HOF_CASE_PACKET_KEY)
    packet_ok = isinstance(packet, dict) and bool(packet.get("target_player"))
    analysis_ok = False
    if packet_ok and resolve_hof_case_analysis is not None:
        try:
            analysis = resolve_hof_case_analysis(packet)
            analysis_ok = bool(analysis.get("thesis") or analysis.get("case_memo"))
        except Exception:
            analysis_ok = False

    pending = session.get(SESSION_PENDING_KEY)
    try:
        from hof_case_resume import HOF_SUBMIT_PENDING_SNAPSHOT_KEY
    except ImportError:
        HOF_SUBMIT_PENDING_SNAPSHOT_KEY = "_hof_case_submit_pending_insight"
    submit_snap = session.get(HOF_SUBMIT_PENDING_SNAPSHOT_KEY)
    if not isinstance(submit_snap, dict):
        submit_snap = {}

    def _pending_body_ok(row: dict[str, Any] | None) -> bool:
        return isinstance(row, dict) and bool(str(row.get("conclusion") or row.get("short_answer") or "").strip())

    pending_ok = _pending_body_ok(pending if isinstance(pending, dict) else None) or _pending_body_ok(submit_snap)
    effective_pending = pending if isinstance(pending, dict) and _pending_body_ok(pending) else submit_snap

    insight_id = ""
    if isinstance(effective_pending, dict):
        insight_id = str(effective_pending.get("insight_id") or "").strip()
    qid = str((effective_pending or {}).get("question_id") or "").strip() if isinstance(effective_pending, dict) else ""

    last_diag = session.get("_hof_case_last_submit_diag")
    if not isinstance(last_diag, dict):
        last_diag = {}
    if not insight_id:
        insight_id = str(last_diag.get("insight_id") or "").strip()
    if not qid:
        qid = str(last_diag.get("question_id") or "").strip()

    last_blob = session.get("_hof_case_last_ami_blob")
    if not isinstance(last_blob, dict):
        last_blob = {}

    store_trace = session.get("_ami_insight_store_trace")
    if not isinstance(store_trace, dict):
        store_trace = {}
    if not insight_id:
        insight_id = str(
            store_trace.get("store_insight_id")
            or store_trace.get("return_link_insight_id")
            or ""
        ).strip()

    eff_url = ""
    if isinstance(effective_pending, dict):
        eff_url = str(effective_pending.get("full_analysis_url") or "").strip()
    pend_url = ""
    if isinstance(pending, dict):
        pend_url = str(pending.get("full_analysis_url") or "").strip()
    action_url = str(
        last_diag.get("action_url") or eff_url or pend_url or last_blob.get("action_url") or ""
    ).strip()

    pipeline = session.get(HOF_PIPELINE_STATUS_KEY)
    if not isinstance(pipeline, dict):
        pipeline = {}

    flags = {
        "force_insight_render": bool(session.get("_ami_force_insight_render")),
        "submit_render_this_run": bool(session.get("_ami_submit_render_insight_this_run")),
        "insight_return_preserve": bool(session.get("_ami_insight_return_preserve")),
        "skip_page_restore_for": str(session.get("_skip_page_restore_for") or ""),
        "insight_staged_for_resume": str(session.get("_hof_case_insight_staged_for_resume") or ""),
        "insight_render_success": session.get("_ami_insight_render_success"),
        "insight_render_skipped_reason": str(session.get("_ami_insight_render_skipped_reason") or ""),
        "render_attempted": session.get("_ami_insight_render_attempted"),
        "render_returned": session.get("_ami_insight_render_returned"),
        "render_output_success": session.get("_ami_insight_render_output_success"),
        "last_deferred_save_reason": str(session.get("_suite_last_deferred_save_reason") or ""),
        "persist_insight_dirty": bool(session.get("_suite_persist_insight_dirty")),
    }

    checks = {
        "hof_packet_built": packet_ok,
        "hof_case_analysis_resolved": analysis_ok,
        "compact_insight_record_built": bool(
            pipeline.get("steps", {}).get("compact_insight_built", {}).get("ok")
            if isinstance(pipeline.get("steps"), dict)
            else pending_ok
        ),
        "baseball_card_staged_in_session": pending_ok,
        "baseball_card_render_flag_present": bool(
            flags["force_insight_render"] or flags["submit_render_this_run"]
        ),
        "store_applied_math_insight_called": bool(
            pipeline.get("steps", {}).get("store_applied_math_insight", {}).get("ok")
            if isinstance(pipeline.get("steps"), dict)
            else store_trace.get("store_blob_written_success")
        ),
        "cloud_insight_publish_success": bool(store_trace.get("store_blob_written_success")),
        "ami_blob_persist_success": bool(
            pipeline.get("steps", {}).get("persist_question_context_blob", {}).get("ok")
            if isinstance(pipeline.get("steps"), dict)
            else bool(last_blob)
        ),
    }

    return {
        **_deploy_info(),
        "hof_handoff_fix_marker": "hof_publish_handoff_v2",
        "checks": checks,
        "ids": {
            "question_id": qid or str(last_diag.get("question_id") or last_blob.get("question_id") or ""),
            "insight_id": insight_id,
            "resume_key": str(last_blob.get("resume_key") or ""),
            "blob_type": str(last_diag.get("blob_type") or last_blob.get("blob_type") or ""),
        },
        "open_full_analysis_url": action_url,
        "open_full_analysis_url_params": _url_param_summary(action_url),
        "command_center_last_submit_diag": last_diag,
        "ami_blob_audit": last_blob.get("hof_ami_audit") if isinstance(last_blob.get("hof_ami_audit"), dict) else {},
        "insight_store_trace": store_trace,
        "session_flags": flags,
        "pipeline_steps": pipeline.get("steps") if isinstance(pipeline.get("steps"), dict) else {},
        "pipeline_errors": list(session.get(HOF_PIPELINE_ERRORS_KEY) or []),
        "pending_insight_preview": {
            "conclusion_len": len(str((effective_pending or {}).get("conclusion") or ""))
            if isinstance(effective_pending, dict)
            else 0,
            "method": str((effective_pending or {}).get("method") or "")[:120]
            if isinstance(effective_pending, dict)
            else "",
            "source_page": str((effective_pending or {}).get("source_page") or "")
            if isinstance(effective_pending, dict)
            else "",
            "session_key": SESSION_PENDING_KEY,
            "submit_snapshot_present": _pending_body_ok(submit_snap),
        },
    }


def render_hof_pipeline_debug(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    """Developer Mode only — collapsed HOF publish/handoff pipeline status."""
    if not developer_mode:
        return
    status = build_hof_pipeline_status(session)
    with st.expander("Developer: HOF pipeline status", expanded=False):
        deploy = status.get("deploy_commit", "unknown")
        branch = status.get("deploy_branch", "unknown")
        st.caption(
            f"Baseball build `{status.get('build_label', deploy)}` · commit `{deploy}` · branch `{branch}` · "
            f"marker `{status.get('hof_handoff_fix_marker', '')}`"
        )
        checks = status.get("checks") if isinstance(status.get("checks"), dict) else {}
        if checks:
            rows = [f"- **{name.replace('_', ' ')}**: {'yes' if val else 'no'}" for name, val in checks.items()]
            st.markdown("\n".join(rows))
        errors = status.get("pipeline_errors")
        if isinstance(errors, list) and errors:
            st.error("Pipeline failures detected:")
            for row in errors[-5:]:
                if isinstance(row, dict):
                    st.code(f"{row.get('step')}: {row.get('error')}")
        st.json(status)


def persist_question_context_blob_traced(session: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Persist AMI blob and record pipeline outcome."""
    qid = str(payload.get("question_id") or "").strip()
    trace: dict[str, Any] = {"question_id": qid, "stored": False, "error": None}
    try:
        from suite_analytical_question import persist_question_context_blob

        persist_question_context_blob(payload)
        trace["stored"] = True
        record_hof_pipeline_step(session, "persist_question_context_blob", ok=True, detail={"question_id": qid})
    except Exception as exc:
        trace["error"] = f"{type(exc).__name__}: {exc}"
        record_hof_pipeline_exception(session, "persist_question_context_blob", exc)
    session["_hof_case_last_blob_persist_trace"] = trace
    return trace
