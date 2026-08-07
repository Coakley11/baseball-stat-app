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


def wait_bridge_auth_hydrated(
    page,
    suite_sid: str,
    scrape_ledger,
    *,
    timeout_s: float = 180.0,
) -> dict[str, Any]:
    from playwright_auth_current_state_eval import (
        bound_state_passes_observability_resolved,
        evaluate_bound_current_auth_state,
    )
    from playwright_auth_observability import gather_page_observability, probe_dom_current_auth_state
    from playwright_auth_preflight_strict import inspect_start_control, suite_sid_from_url
    from queueui_audit_protocol import scrape_deploy_marker_from_page

    out: dict[str, Any] = {
        "bridge_restore_mode": True,
        "suite_sid": suite_sid,
        "suite_sid_prefix": suite_sid[:8] if suite_sid else "",
        "authenticated_restored": False,
        "failure": "",
        "deployment_sha": "",
        "streamlit_session_id": "",
        "diagnostic_run_id": "",
    }
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        page.wait_for_timeout(5000)
        deploy_sha, _ = scrape_deploy_marker_from_page(page)
        out["deployment_sha"] = str(deploy_sha or "")[:7]
        url_sid = suite_sid_from_url(page.url or "")
        reject = bridge_preflight_rejects_stale_session(
            bridge_sid=suite_sid, url_sid=url_sid, authenticated=False
        )
        if reject == "url_suite_sid_mismatch":
            out["failure"] = reject
            return out
        obs = gather_page_observability(page, harness_sid=suite_sid, strict_failure="")
        ledger = list(obs.get("ledger_rows_for_eval") or scrape_ledger(page) or [])
        cp = obs.get("checkpoint") or {}
        start = obs.get("start_surface") or inspect_start_control(page)
        fi = int(cp.get("start_frame_index") or start.get("frame_index") or 0)
        dom = probe_dom_current_auth_state(page, frame_index=fi) or cp.get("current_auth_dom") or {}
        bound = evaluate_bound_current_auth_state(
            current_auth_dom=dom,
            ledger_rows=ledger,
            diagnostic_run_id=str(cp.get("diagnostic_run_id") or "")[:64],
            streamlit_session_id=str(cp.get("streamlit_session_id") or "")[:36],
            start_enabled=bool(cp.get("start_enabled")),
            start_visible=bool(cp.get("start_visible")),
        )
        out["streamlit_session_id"] = str(cp.get("streamlit_session_id") or "")[:64]
        out["diagnostic_run_id"] = str(cp.get("diagnostic_run_id") or "")[:64]
        if bound_state_passes_observability_resolved(bound) and bool(cp.get("start_enabled")):
            reject = bridge_preflight_rejects_stale_session(
                bridge_sid=suite_sid, url_sid=url_sid or suite_sid, authenticated=True
            )
            if reject:
                out["failure"] = reject
                return out
            out["authenticated_restored"] = True
            out["bound_current_auth"] = {
                k: bound.get(k)
                for k in (
                    "session_flag_present",
                    "is_authenticated",
                    "auth_session_complete",
                    "current_restore_blocked_reason",
                    "apply_authenticated_user_ok",
                )
            }
            return out
    out["failure"] = "bridge_hydration_timeout"
    return out
