"""Shared harness: restore Cloud auth via persisted browser bridge (no app changes)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CAPTURE_RESULT = ROOT / "data" / "capture_playwright_daniel_auth_once.result.json"


def resolve_bridge_suite_sid(*, capture_path: Path | None = None) -> str:
    env = str(os.environ.get("ROOT_AUDIT_BRIDGE_SUITE_SID") or os.environ.get("STAGE1_BRIDGE_SUITE_SID") or "").strip()
    if env:
        return env
    if str(os.environ.get("ROOT_AUDIT_USE_CAPTURE_BRIDGE") or os.environ.get("STAGE1_USE_CAPTURE_BRIDGE") or "1").strip().lower() in (
        "0",
        "false",
        "no",
    ):
        return ""
    cap_path = capture_path or CAPTURE_RESULT
    if not cap_path.is_file():
        return ""
    try:
        data = json.loads(cap_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    bp = (data.get("strict_capture") or {}).get("bridge_persistence") or {}
    sid = str(data.get("suite_sid") or "").strip()
    if sid and bp.get("persistence_succeeded"):
        return sid
    return ""


def bridge_preflight_rejects_stale_session(*, bridge_sid: str, url_sid: str, authenticated: bool) -> str:
    """Return failure reason when bridge/session evidence mismatches."""
    if not bridge_sid:
        return "bridge_sid_missing"
    if url_sid and url_sid != bridge_sid:
        return "url_suite_sid_mismatch"
    if not authenticated:
        return "authenticated_session_not_bound"
    return ""


def resolve_real_accounts_wake(*, bridge_restore_mode: bool) -> bool:
    from bridge_hydration_waiter import resolve_real_accounts_wake as _resolve

    return _resolve(bridge_restore_mode=bridge_restore_mode)


def wait_bridge_auth_hydrated(
    page,
    suite_sid: str,
    scrape_ledger,
    *,
    timeout_s: float = 180.0,
    poll_interval_s: float = 2.0,
    initial_settle_ms: int = 0,
    preamble_mode: str = "stage1",
    expected_application_phase: str = "setup_lobby",
    standalone_start_consumed: bool = False,
) -> dict[str, Any]:
    from bridge_hydration_waiter import (
        AUTH_HYDRATE_FAIL_AUTH_API,
        bound_bridge_auth_only_passes,
        bound_bridge_hydration_passes,
        bridge_load_succeeded,
        detect_restore_rerun_anomaly,
        hydration_fail_fast_from_restore_exit,
        latest_hydration_checkpoint,
        summarize_hydration_sequence,
    )
    from stage1_application_phase import (
        EXPECTED_PHASE_AUTH_ONLY,
        EXPECTED_PHASE_SETUP_LOBBY,
        classify_hydration_timeout,
        classify_ldr_phase_from_page,
    )
    from playwright_auth_current_state_eval import evaluate_bound_current_auth_state
    from playwright_auth_observability import gather_page_observability, probe_dom_current_auth_state
    from playwright_auth_preflight_strict import inspect_start_control, suite_sid_from_url
    from queueui_audit_protocol import scrape_deploy_marker_from_page

    out: dict[str, Any] = {
        "bridge_restore_mode": True,
        "suite_sid": suite_sid,
        "suite_sid_prefix": suite_sid[:8] if suite_sid else "",
        "authenticated_restored": False,
        "failure": "",
        "failure_classification": "",
        "deployment_sha": "",
        "streamlit_session_id": "",
        "diagnostic_run_id": "",
        "preamble_mode": preamble_mode,
        "expected_application_phase": expected_application_phase,
        "hydration_polls": [],
        "first_divergence_from_isolated": "",
    }
    require_start = expected_application_phase == EXPECTED_PHASE_SETUP_LOBBY
    deadline = time.time() + timeout_s
    if initial_settle_ms > 0:
        page.wait_for_timeout(initial_settle_ms)
    poll_n = 0
    while time.time() < deadline:
        poll_n += 1
        t_poll = time.time()
        if poll_n > 1:
            page.wait_for_timeout(int(max(poll_interval_s, 0.5) * 1000))
        deploy_sha, _ = scrape_deploy_marker_from_page(page)
        out["deployment_sha"] = str(deploy_sha or "")[:7]
        url_sid = suite_sid_from_url(page.url or "")
        reject = bridge_preflight_rejects_stale_session(
            bridge_sid=suite_sid, url_sid=url_sid, authenticated=False
        )
        if reject == "url_suite_sid_mismatch":
            out["failure"] = reject
            out["failure_classification"] = "AUTH_HYDRATE8"
            return out
        obs = gather_page_observability(page, harness_sid=suite_sid, strict_failure="")
        ledger = list(obs.get("ledger_rows_for_eval") or scrape_ledger(page) or [])
        cp = obs.get("checkpoint") or {}
        start = obs.get("start_surface") or inspect_start_control(page)
        fi = int(cp.get("start_frame_index") or start.get("frame_index") or 0)
        dom = probe_dom_current_auth_state(page, frame_index=fi) or cp.get("current_auth_dom") or {}
        run_id = str(cp.get("diagnostic_run_id") or "")[:64]
        st_sid = str(cp.get("streamlit_session_id") or "")[:36]
        out["streamlit_session_id"] = st_sid
        out["diagnostic_run_id"] = run_id

        restore_exit = latest_hydration_checkpoint(
            ledger, "restore_auth_session_exit", streamlit_session_id=st_sid, diagnostic_run_id=run_id
        )
        fail_fast = hydration_fail_fast_from_restore_exit(restore_exit)
        if fail_fast:
            out["failure"] = fail_fast
            out["failure_classification"] = "AUTH_HYDRATE3" if "AuthApiError" in fail_fast else "AUTH_HYDRATE8"
            out["restore_exit_snapshot"] = {
                k: restore_exit.get(k)
                for k in (
                    "skip_or_failure_reason",
                    "exception_class",
                    "auth_status",
                    "auth_code",
                    "message_sanitized",
                    "restore_attempt_seq",
                )
            } if restore_exit else {}
            out["hydration_sequence"] = summarize_hydration_sequence(
                ledger, streamlit_session_id=st_sid, diagnostic_run_id=run_id
            )
            out["rerun_anomaly"] = detect_restore_rerun_anomaly(ledger, streamlit_session_id=st_sid)
            return out

        bound = evaluate_bound_current_auth_state(
            current_auth_dom=dom,
            ledger_rows=ledger,
            diagnostic_run_id=run_id,
            streamlit_session_id=st_sid,
            start_enabled=bool(cp.get("start_enabled") or start.get("enabled")),
            start_visible=bool(cp.get("start_visible") or start.get("visible")),
        )
        load_ok = bridge_load_succeeded(ledger, streamlit_session_id=st_sid, diagnostic_run_id=run_id)
        start_enabled = bool(cp.get("start_enabled") or start.get("enabled"))
        start_visible = bool(cp.get("start_visible") if cp.get("start_visible") is not None else start.get("visible"))

        poll_record = {
            "poll": poll_n,
            "elapsed_s": round(t_poll - (deadline - timeout_s), 2),
            "dom_bound": bool(dom.get("streamlit_session_id")),
            "load_ok": load_ok,
            "start_enabled": start_enabled,
            "is_authenticated": bound.get("is_authenticated"),
            "auth_session_complete": bound.get("auth_session_complete"),
            "restore_block": str(bound.get("current_restore_blocked_reason") or "")[:40],
        }
        out["hydration_polls"].append(poll_record)

        auth_only_ok = bound_bridge_auth_only_passes(
            bound,
            suite_sid=suite_sid,
            url_sid=url_sid or suite_sid,
            bridge_load_ok=load_ok,
        )
        if expected_application_phase == EXPECTED_PHASE_AUTH_ONLY and auth_only_ok:
            reject = bridge_preflight_rejects_stale_session(
                bridge_sid=suite_sid, url_sid=url_sid or suite_sid, authenticated=True
            )
            if reject:
                out["failure"] = reject
                return out
            out["authenticated_restored"] = True
            out["hydration_pass_mode"] = "auth_only"
            out["bound_current_auth"] = {
                k: bound.get(k)
                for k in (
                    "session_flag_present",
                    "is_authenticated",
                    "auth_session_complete",
                    "current_restore_blocked_reason",
                    "apply_authenticated_user_ok",
                    "field_sources",
                )
            }
            out["hydration_sequence"] = summarize_hydration_sequence(
                ledger, streamlit_session_id=st_sid, diagnostic_run_id=run_id
            )
            out["rerun_anomaly"] = detect_restore_rerun_anomaly(ledger, streamlit_session_id=st_sid)
            out["hydration_pass_poll"] = poll_n
            return out

        if bound_bridge_hydration_passes(
            bound,
            suite_sid=suite_sid,
            url_sid=url_sid or suite_sid,
            bridge_load_ok=load_ok,
            start_enabled=start_enabled,
            start_visible=start_visible,
            require_start=require_start,
        ):
            reject = bridge_preflight_rejects_stale_session(
                bridge_sid=suite_sid, url_sid=url_sid or suite_sid, authenticated=True
            )
            if reject:
                out["failure"] = reject
                return out
            out["authenticated_restored"] = True
            out["hydration_pass_mode"] = "setup_lobby"
            out["bound_current_auth"] = {
                k: bound.get(k)
                for k in (
                    "session_flag_present",
                    "is_authenticated",
                    "auth_session_complete",
                    "current_restore_blocked_reason",
                    "apply_authenticated_user_ok",
                    "field_sources",
                )
            }
            out["hydration_sequence"] = summarize_hydration_sequence(
                ledger, streamlit_session_id=st_sid, diagnostic_run_id=run_id
            )
            out["rerun_anomaly"] = detect_restore_rerun_anomaly(ledger, streamlit_session_id=st_sid)
            out["hydration_pass_poll"] = poll_n
            return out

    out["failure"] = "bridge_hydration_timeout"
    phase_info = classify_ldr_phase_from_page(page)
    out["application_phase_at_timeout"] = phase_info.get("application_phase")
    timeout_cls = classify_hydration_timeout(
        expected_application_phase=expected_application_phase,
        hydration_polls=out["hydration_polls"],
        application_phase=str(phase_info.get("application_phase") or ""),
        standalone_start_consumed=standalone_start_consumed,
    )
    out["failure_classification"] = timeout_cls.get("failure_classification") or "AUTH_HYDRATE7"
    out["hydration_timeout_root_cause"] = timeout_cls.get("root_cause")
    out["auth_complete_at_timeout"] = timeout_cls.get("auth_complete_at_timeout")
    if timeout_cls.get("mislabeled_as_auth_hydrate7"):
        out["first_divergence_from_isolated"] = timeout_cls.get("root_cause")
    elif out["hydration_polls"]:
        last = out["hydration_polls"][-1]
        if last.get("load_ok") and last.get("is_authenticated") and last.get("auth_session_complete"):
            out["first_divergence_from_isolated"] = (
                "timeout_despite_dom_auth_complete_likely_start_enabled_or_apply_predicate"
            )
    return out
