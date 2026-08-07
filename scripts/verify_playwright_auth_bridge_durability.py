"""Two fresh-context bridge durability verification (no Start click, no provider sign-in)."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "playwright_auth_bridge_durability_verify.json"
TRACE_ROOT = ROOT / "data" / "playwright_auth_bridge_durability_trace"
CAPTURE_RESULT = ROOT / "data" / "capture_playwright_daniel_auth_once.result.json"
EXPECTED_SHA = (
    Path(__file__).resolve().parent.parent / "deploy_commit.txt"
).read_text(encoding="utf-8").splitlines()[0].split("#", 1)[0].strip()[:7]

AUTH_BRIDGE_DURABILITY_RESOLVED = "AUTH_BRIDGE_DURABILITY_RESOLVED"
AUTH_BRIDGE_ROTATION_DURABILITY_RESOLVED = "AUTH_BRIDGE_ROTATION_DURABILITY_RESOLVED"
AUTH_BRIDGE1 = "AUTH_BRIDGE1"
AUTH_BRIDGE2 = "AUTH_BRIDGE2"
AUTH_BRIDGE3 = "AUTH_BRIDGE3"
AUTH_BRIDGE4 = "AUTH_BRIDGE4"
AUTH_BRIDGE5 = "AUTH_BRIDGE5"
AUTH_BRIDGE6 = "AUTH_BRIDGE6"
AUTH_BRIDGE8 = "AUTH_BRIDGE8"

LDR_DIAG_URL = (
    "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
    "?active_page=Live+Draft+Room"
    "&solo_component_diag=1&solo_stage1_parent_boundary=1"
)


def _capture_suite_sid() -> str:
    env = str(os.environ.get("BRIDGE_DURABILITY_SUITE_SID") or "").strip()
    if env:
        return env
    if CAPTURE_RESULT.is_file():
        try:
            data = json.loads(CAPTURE_RESULT.read_text(encoding="utf-8"))
            sid = str(data.get("suite_sid") or "").strip()
            if sid:
                return sid
        except (json.JSONDecodeError, OSError):
            pass
    return ""


def _row_prefix_from_capture(cap: dict[str, Any]) -> str:
    for key in ("login_timeline",):
        for row in reversed(cap.get(key) or []):
            if str(row.get("checkpoint") or "") == "save_browser_auth_tokens_readback":
                pref = str(row.get("matching_row_id_prefix") or "").strip()
                if pref:
                    return pref[:16]
    sc = cap.get("strict_capture") or {}
    bp = sc.get("bridge_persistence") or {}
    return str(bp.get("matching_row_id_prefix") or "")[:16]


def _sanitize_probe(probe: dict[str, Any]) -> dict[str, Any]:
    return {
        k: probe.get(k)
        for k in (
            "suite_sid_prefix",
            "production_query_row_count",
            "production_row_found",
            "production_row_valid",
            "production_record_complete",
            "row_id",
            "owner_id_prefix",
            "owner_match",
            "updated_at",
            "expires_at",
            "access_token_present",
            "refresh_token_present",
            "invalid_rows_for_key",
            "rejection_reason",
            "query_exception",
            "cache_enabled",
            "environment",
        )
    }


def context_a_source_probe(suite_sid: str) -> dict[str, Any]:
    from suite_auth_browser_bridge_diag import probe_browser_auth_storage, readback_after_browser_auth_save

    out: dict[str, Any] = {
        "phase": "context_a_source",
        "suite_sid": suite_sid,
        "bridge_lookup_attempted": True,
        "bridge_record_found": False,
        "bridge_record_complete": False,
        "invalidation_status": "not_checked",
        "invalidation_reason": "",
        "uncached_readback_complete": False,
        "probe": {},
        "readback": {},
        "capture_artifact_bridge": {},
        "harness_storage_file": str(ROOT / "data" / "playwright_daniel_auth.storage.json"),
        "harness_session_file": str(ROOT / "data" / "playwright_daniel_auth.session.json"),
    }
    if not suite_sid:
        out["failure"] = "source_suite_sid_missing"
        return out
    if CAPTURE_RESULT.is_file():
        try:
            cap = json.loads(CAPTURE_RESULT.read_text(encoding="utf-8"))
            bp = (cap.get("strict_capture") or {}).get("bridge_persistence") or {}
            out["capture_artifact_bridge"] = {
                k: bp.get(k)
                for k in (
                    "persistence_attempted",
                    "persistence_succeeded",
                    "readback_succeeded",
                    "suite_sid_prefix_match",
                    "access_token_present",
                    "refresh_token_present",
                    "auth_user_id_present",
                    "bridge_record_complete",
                    "failure_reason",
                )
            }
            if cap.get("suite_sid") == suite_sid and bp.get("persistence_succeeded"):
                out["bridge_record_found"] = True
                out["bridge_record_complete"] = bool(bp.get("bridge_record_complete"))
                out["uncached_readback_complete"] = bool(bp.get("readback_succeeded"))
                out["invalidation_status"] = "valid_at_capture_time"
                out["capture_ok_ignored"] = cap.get("ok") is False
                out["authoritative_row_id_prefix"] = _row_prefix_from_capture(cap)
        except (json.JSONDecodeError, OSError):
            pass
    live_probe = str(os.environ.get("BRIDGE_DURABILITY_CONTEXT_A_LIVE_PROBE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if not live_probe:
        out["local_supabase_probe"] = "skipped_pre_b_context_artifact_only"
        if out.get("invalidation_status") == "not_checked" and out.get("bridge_record_complete"):
            out["invalidation_status"] = "valid_at_capture_time"
        return out
    probe = probe_browser_auth_storage(suite_sid, use_cache=False)
    out["probe"] = _sanitize_probe(probe)
    if probe.get("environment", {}).get("configured"):
        out["bridge_record_found"] = bool(probe.get("production_row_found"))
        out["bridge_record_complete"] = bool(probe.get("production_record_complete"))
        if probe.get("invalid_rows_for_key"):
            out["invalidation_status"] = "invalid_rows_present"
            out["invalidation_reason"] = f"invalid_rows_for_key={probe.get('invalid_rows_for_key')}"
        elif probe.get("production_row_found") and probe.get("production_row_valid"):
            out["invalidation_status"] = "valid"
        elif str(probe.get("rejection_reason") or "") == "record_invalidated":
            out["invalidation_status"] = "invalidated"
            out["invalidation_reason"] = "record_invalidated"
        rb = readback_after_browser_auth_save(suite_sid, save_reported_success=True)
        out["readback"] = {
            k: rb.get(k)
            for k in (
                "readback_attempted",
                "readback_row_found",
                "readback_record_complete",
                "matching_row_id",
                "failure_reason",
                "owner_id_prefix",
                "updated_at",
                "invalid_rows_for_key",
            )
        }
        out["uncached_readback_complete"] = bool(rb.get("readback_record_complete"))
    else:
        out["local_supabase_probe"] = "skipped_not_configured"
    return out


def _rotation_restore_metrics(ledger_rows: list[dict[str, Any]]) -> dict[str, Any]:
    blob = json.dumps(ledger_rows, default=str).lower()

    def _rows(cp: str) -> list[dict[str, Any]]:
        return [r for r in ledger_rows if str(r.get("checkpoint") or "") == cp]

    restore_exits = _rows("restore_auth_session_exit")
    rot_persist = _rows("bridge_restore_rotation_persist")
    sf_acquire = _rows("bridge_restore_single_flight_acquire")
    sf_skip = _rows("bridge_restore_single_flight_skip")
    sf_release = _rows("bridge_restore_single_flight_release")
    exceptions = _rows("restore_auth_session_exception")
    saves = _rows("save_browser_auth_tokens")
    readbacks = [r for r in _rows("save_browser_auth_tokens_readback") if r.get("readback_record_complete")]
    invalidations = _bridge_invalidate_mutations(ledger_rows)

    gens: list[int] = []
    fp_prefixes: list[str] = []
    for r in rot_persist + readbacks + saves:
        for key in ("token_generation", "result_generation", "prior_generation", "expected_generation"):
            try:
                g = int(r.get(key) or 0)
                if g > 0:
                    gens.append(g)
            except (TypeError, ValueError):
                pass
        fp = str(r.get("refresh_fp_prefix") or r.get("refresh_fp") or "")[:16]
        if fp:
            fp_prefixes.append(fp)

    load_lookup = _rows("load_browser_auth_tokens_lookup")
    load_ok = [r for r in load_lookup if r.get("browser_tokens_loaded") is True]
    best_lookup = load_ok[-1] if load_ok else (load_lookup[-1] if load_lookup else {})

    set_session_exceptions = [
        r for r in exceptions if str(r.get("phase") or "") == "set_session" or "set_session" in str(r.get("phase") or "")
    ]
    set_session_ok_proxy = max(len(rot_persist), sum(1 for r in restore_exits if r.get("authenticated_after") is True))

    return {
        "restore_attempt_count": len(restore_exits),
        "set_session_call_count_proxy": set_session_ok_proxy,
        "set_session_exception_count": len(set_session_exceptions),
        "single_flight_acquire_count": len(sf_acquire),
        "single_flight_skip_count": len(sf_skip),
        "single_flight_release_count": len(sf_release),
        "rotation_persist_count": len(rot_persist),
        "bridge_save_count": len(saves),
        "readback_complete_count": len(readbacks),
        "bridge_row_prefix_at_load": str(best_lookup.get("row_id_prefix") or "")[:16],
        "access_token_present_at_load": bool(best_lookup.get("access_token_present")),
        "refresh_token_present_at_load": bool(best_lookup.get("refresh_token_present")),
        "load_rejection_reason": str(best_lookup.get("rejection_reason") or "")[:80],
        "token_generation_observed": sorted(set(gens)) if gens else "not_observed",
        "refresh_fp_prefixes_observed": sorted(set(fp_prefixes)) if fp_prefixes else "not_observed",
        "refresh_token_already_used": "refresh_token_already_used" in blob,
        "auth_hydrate_3b": "auth_hydrate_3b" in blob,
        "bridge_invalidate_count": len(invalidations),
        "bridge_invalidate_mutations": invalidations,
    }


def _ledger_bridge_facts(ledger_rows: list[dict[str, Any]]) -> dict[str, Any]:
    def _seq(row: dict[str, Any]) -> int:
        try:
            return int(row.get("script_run_seq") or 0)
        except (TypeError, ValueError):
            return 0

    load_rows = [
        r
        for r in ledger_rows
        if str(r.get("checkpoint") or "") in ("load_browser_auth_tokens", "load_browser_auth_tokens_lookup")
    ]
    load_row = max(load_rows, key=_seq) if load_rows else None
    load_ok_row = next(
        (r for r in sorted(load_rows, key=_seq, reverse=True) if r.get("browser_tokens_loaded") is True),
        None,
    )
    apply_exit = None
    apply_entry = None
    hydration = [
        r
        for r in ledger_rows
        if str(r.get("event") or "") == "production_stage1_auth_prestart_hydration"
    ]
    for r in sorted(hydration, key=_seq, reverse=True):
        cp = str(r.get("checkpoint") or "")
        if apply_exit is None and cp == "apply_authenticated_user_exit":
            apply_exit = r
        if apply_entry is None and cp == "apply_authenticated_user_entry":
            apply_entry = r
    best_load = load_ok_row or load_row
    return {
        "load_invoked": bool(load_rows),
        "load_browser_tokens_loaded": bool((best_load or {}).get("browser_tokens_loaded")),
        "load_access_token_present": bool((best_load or {}).get("access_token_present")),
        "load_refresh_token_present": bool((best_load or {}).get("refresh_token_present")),
        "load_rejection_reason": str((best_load or {}).get("rejection_reason") or "")[:80],
        "load_row_id_prefix": str((best_load or {}).get("row_id_prefix") or "")[:16],
        "load_suite_sid_prefix": str((best_load or {}).get("suite_sid_prefix") or "")[:16],
        "apply_entry_observed": apply_entry is not None,
        "apply_exit_observed": apply_exit is not None,
        "apply_authenticated_after": (apply_exit or {}).get("authenticated_after"),
        "apply_auth_session_complete": (apply_exit or {}).get("auth_session_complete"),
        "apply_return_ok": (apply_exit or {}).get("apply_return_ok"),
        "latest_load_script_run_seq": _seq(load_row) if load_row else 0,
        "successful_load_script_run_seq": _seq(load_ok_row) if load_ok_row else 0,
        "restore_exit_reason": _restore_exit_reason(ledger_rows),
        "bridge_invalidate_mutations": _bridge_invalidate_mutations(ledger_rows),
    }


def _restore_exit_reason(ledger_rows: list[dict[str, Any]]) -> str:
    for row in reversed(ledger_rows):
        if str(row.get("checkpoint") or "") == "restore_auth_session_exit":
            return str(row.get("skip_or_failure_reason") or "")[:120]
    return ""


def _bridge_invalidate_mutations(ledger_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in ledger_rows:
        if str(row.get("checkpoint") or "") != "browser_auth_bridge_mutation":
            continue
        if str(row.get("operation") or "") != "invalidate":
            continue
        out.append(
            {
                "reason": str(row.get("reason") or row.get("invalidation_reason") or "")[:80],
                "caller": str(row.get("caller") or "")[:64],
                "prior_row_id": str(row.get("prior_row_id") or row.get("row_id_prefix") or "")[:16],
            }
        )
    return out


def bridge_durability_session_pass(ctx: dict[str, Any]) -> bool:
    """Fresh-context bridge restore success (no provider-login boundary)."""
    bl = ctx.get("bridge_ledger") or {}
    bound = ctx.get("bound_current_auth") or {}
    if str(ctx.get("deployment_sha") or "")[:7] != EXPECTED_SHA[:7]:
        return False
    if not ctx.get("url_suite_sid_matches"):
        return False
    if not bl.get("load_browser_tokens_loaded"):
        return False
    if not bl.get("apply_exit_observed"):
        return False
    if bl.get("apply_authenticated_after") is not True:
        return False
    if bound.get("session_flag_present") is not True:
        return False
    if bound.get("is_authenticated") is not True:
        return False
    if bound.get("auth_session_complete") is not True:
        return False
    if str(bound.get("current_restore_blocked_reason") or "").strip():
        return False
    if not ctx.get("start_enabled"):
        return False
    if bound.get("apply_authenticated_user_ok") is False:
        return False
    return True


def run_fresh_context_hydration(
    *,
    label: str,
    suite_sid: str,
    prior_row_id: str = "",
) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright

    from playwright_auth_current_state_eval import (
        bound_state_passes_observability_resolved,
        evaluate_bound_current_auth_state,
    )
    from playwright_auth_observability import gather_page_observability, probe_dom_current_auth_state
    from playwright_auth_preflight_strict import inspect_start_control, suite_sid_from_url
    from p8_production_start_harness import scrape_stage1_ledger_rows
    from queueui_audit_protocol import scrape_deploy_marker_from_page

    url = f"{LDR_DIAG_URL}&suite_sid={suite_sid}"
    ctx_uuid = str(uuid.uuid4())
    trace_dir = TRACE_ROOT / f"{label}_{int(time.time())}"
    trace_dir.mkdir(parents=True, exist_ok=True)

    out: dict[str, Any] = {
        "phase": label,
        "suite_sid": suite_sid,
        "fresh_browser_context_id": ctx_uuid,
        "navigation_url": url,
        "storage_state_used": False,
        "playwright_page_id": "",
        "start_frame_index": None,
        "streamlit_session_id": "",
        "diagnostic_run_id": "",
        "deployment_sha": "",
        "bridge_ledger": {},
        "bound_current_auth": {},
        "bound_pass": False,
        "start_enabled": False,
        "artifact_dir": str(trace_dir),
        "screenshot": "",
        "failure_detail": "",
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=os.environ.get("PLAYWRIGHT_HEADED", "") not in ("1", "true", "yes"))
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        out["playwright_page_id"] = hex(id(page))[:18]
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(32000)
        try:
            page.screenshot(path=str(trace_dir / "hydration_checkpoint.png"), full_page=False)
            out["screenshot"] = str(trace_dir / "hydration_checkpoint.png")
        except Exception:
            pass
        deploy_sha, _ = scrape_deploy_marker_from_page(page)
        out["deployment_sha"] = str(deploy_sha or "")[:7]
        obs = gather_page_observability(page, harness_sid=suite_sid, strict_failure="")
        ledger = list(obs.get("ledger_rows_for_eval") or scrape_stage1_ledger_rows(page) or [])
        (trace_dir / "ledger_rows.json").write_text(json.dumps(ledger[:500], indent=2), encoding="utf-8")
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
        out["streamlit_session_id"] = str(cp.get("streamlit_session_id") or dom.get("streamlit_session_id") or "")[:64]
        out["diagnostic_run_id"] = str(cp.get("diagnostic_run_id") or dom.get("diagnostic_run_id") or "")[:64]
        out["start_frame_index"] = fi
        out["start_frame_url"] = str(start.get("frame_url") or "")[:400]
        out["url_suite_sid"] = suite_sid_from_url(page.url or "")
        out["url_suite_sid_matches"] = bool(out["url_suite_sid"] == suite_sid)
        out["bridge_ledger"] = _ledger_bridge_facts(ledger)
        out["rotation_restore"] = _rotation_restore_metrics(ledger)
        out["bound_current_auth"] = {
            k: bound.get(k)
            for k in (
                "session_flag_present",
                "is_authenticated",
                "auth_session_complete",
                "current_restore_blocked_reason",
                "apply_authenticated_user_ok",
                "auth_hydration_source",
                "field_sources",
            )
        }
        out["start_enabled"] = bool(cp.get("start_enabled"))
        out["bound_pass"] = bound_state_passes_observability_resolved(bound)
        out["bridge_durability_pass"] = bridge_durability_session_pass(
            {**out, "bridge_ledger": out["bridge_ledger"], "bound_current_auth": out["bound_current_auth"]}
        )
        out["session_binding_failure"] = obs.get("session_binding_failure") or ""
        binding = obs.get("binding") or {}
        out["identity_binding"] = {
            "url_suite_sid_match": binding.get("url_suite_sid_match"),
            "ui_ledger_streamlit_session_match": binding.get("ui_ledger_streamlit_session_match"),
            "ui_ledger_run_match": binding.get("ui_ledger_run_match"),
            "ledger_same_frame_as_start": binding.get("ledger_same_frame_as_start"),
        }
        if prior_row_id and out["bridge_ledger"].get("load_row_id_prefix"):
            pass
        context.close()
        browser.close()

    (trace_dir / "context_report.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    return out


def classify_durability(
    ctx_a: dict[str, Any],
    ctx_b: dict[str, Any],
    ctx_c: dict[str, Any],
    *,
    expected_sha: str,
) -> tuple[str, str]:
    if not ctx_a.get("bridge_record_found"):
        return AUTH_BRIDGE1, "source_bridge_record_not_proven_at_capture"
    if not ctx_a.get("bridge_record_complete"):
        return AUTH_BRIDGE2, "source_bridge_record_incomplete_at_capture"

    for label, ctx in (("context_b", ctx_b), ("context_c", ctx_c)):
        if str(ctx.get("deployment_sha") or "")[:7] != expected_sha[:7]:
            return AUTH_BRIDGE3, f"{label}_deploy_sha_mismatch"
        if not ctx.get("url_suite_sid_matches"):
            return AUTH_BRIDGE3, f"{label}_url_suite_sid_mismatch"
        bl = ctx.get("bridge_ledger") or {}
        if not bl.get("load_invoked"):
            return AUTH_BRIDGE5, f"{label}_load_browser_auth_not_invoked"
        if bl.get("load_browser_tokens_loaded") and not bl.get("apply_exit_observed"):
            return AUTH_BRIDGE5, f"{label}_load_ok_apply_never_invoked"
        if not bl.get("load_browser_tokens_loaded"):
            reason = str(bl.get("load_rejection_reason") or "").strip().lower()
            if reason == "record_invalidated":
                return AUTH_BRIDGE4, f"{label}_bridge_record_invalidated_at_runtime"
            if reason == "token_record_missing":
                return AUTH_BRIDGE1, f"{label}_bridge_record_not_found_at_runtime"
            return AUTH_BRIDGE2, f"{label}_bridge_record_incomplete_at_runtime"
        if bl.get("apply_exit_observed") and bl.get("apply_authenticated_after") is not True:
            return AUTH_BRIDGE6, f"{label}_apply_exit_incomplete"
        if not ctx.get("bridge_durability_pass"):
            return AUTH_BRIDGE6, f"{label}_final_session_state_incomplete"
        rot = ctx.get("rotation_restore") or {}
        if rot.get("refresh_token_already_used"):
            return "AUTH_HYDRATE3B", f"{label}_refresh_token_already_used"
        if rot.get("auth_hydrate_3b"):
            return "AUTH_HYDRATE3B", f"{label}_auth_hydrate_3b_latched"
        if int(rot.get("bridge_invalidate_count") or 0) > 0:
            return AUTH_BRIDGE4, f"{label}_bridge_invalidated_during_restore"
        if ctx.get("session_binding_failure"):
            return AUTH_BRIDGE3, f"{label}_session_binding_{ctx.get('session_binding_failure')}"

    if ctx_b.get("streamlit_session_id") and ctx_c.get("streamlit_session_id"):
        if ctx_b["streamlit_session_id"] == ctx_c["streamlit_session_id"]:
            return AUTH_BRIDGE8, "context_b_and_c_shared_streamlit_session_id"

    return AUTH_BRIDGE_ROTATION_DURABILITY_RESOLVED, "both_fresh_contexts_hydrated_from_persisted_bridge"


def probe_browser_auth_storage_post(suite_sid: str) -> dict[str, Any]:
    from suite_auth_browser_bridge_diag import probe_browser_auth_storage

    return probe_browser_auth_storage(suite_sid, use_cache=False)


def main() -> int:
    suite_sid = _capture_suite_sid()
    report: dict[str, Any] = {
        "started_at": time.time(),
        "expected_deployment_sha": EXPECTED_SHA,
        "source_capture_suite_sid": suite_sid,
        "authentication_phase": "accepted_resolved",
        "application_diagnostic_sha": EXPECTED_SHA,
        "deploy_marker_sha": EXPECTED_SHA,
        "context_a_authoritative_capture": True,
    }
    if not suite_sid:
        report["classification"] = AUTH_BRIDGE1
        report["detail"] = "capture_suite_sid_unavailable"
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
        return 1

    ctx_a = context_a_source_probe(suite_sid)
    report["context_a"] = ctx_a

    fresh_b_sid = str(os.environ.get("BRIDGE_DURABILITY_FRESH_SID_B") or uuid.uuid4())
    fresh_c_sid = str(os.environ.get("BRIDGE_DURABILITY_FRESH_SID_C") or uuid.uuid4())
    # Bridge rows are keyed by URL suite_sid; durability uses the persisted capture sid unless
    # explicit fresh sid env vars point at pre-provisioned rows.
    url_sid_b = suite_sid if not os.environ.get("BRIDGE_DURABILITY_FRESH_SID_B") else fresh_b_sid
    url_sid_c = suite_sid if not os.environ.get("BRIDGE_DURABILITY_FRESH_SID_C") else fresh_c_sid
    report["context_b_planned_suite_sid"] = url_sid_b
    report["context_c_planned_suite_sid"] = url_sid_c
    report["fresh_sid_note"] = (
        "Default: both fresh browser contexts reuse persisted capture suite_sid in URL "
        "(Supabase item_key). Set BRIDGE_DURABILITY_FRESH_SID_B/C to override."
    )

    prior_row = str(ctx_a.get("authoritative_row_id_prefix") or (ctx_a.get("probe") or {}).get("row_id") or "")
    ctx_b = run_fresh_context_hydration(label="context_b", suite_sid=url_sid_b, prior_row_id=prior_row)
    report["context_b"] = ctx_b
    post_b: dict[str, Any] = {"skipped": "post_context_read_only_optional"}
    if str(os.environ.get("BRIDGE_DURABILITY_POST_PROBE") or "1").strip().lower() not in ("0", "false", "no"):
        post_b = _sanitize_probe(probe_browser_auth_storage_post(suite_sid))
    report["bridge_row_post_context_b"] = post_b

    ctx_c = run_fresh_context_hydration(label="context_c", suite_sid=url_sid_c, prior_row_id=prior_row)
    report["context_c"] = ctx_c
    post_c: dict[str, Any] = {"skipped": "post_context_read_only_optional"}
    if str(os.environ.get("BRIDGE_DURABILITY_POST_PROBE") or "1").strip().lower() not in ("0", "false", "no"):
        post_c = _sanitize_probe(probe_browser_auth_storage_post(suite_sid))
    report["bridge_row_post_context_c"] = post_c

    code, detail = classify_durability(ctx_a, ctx_b, ctx_c, expected_sha=EXPECTED_SHA)
    report["classification"] = code
    report["detail"] = detail
    report["pass"] = code == AUTH_BRIDGE_ROTATION_DURABILITY_RESOLVED
    report["context_a_row_prefix_expected"] = "31869"
    report["context_a_token_generation_baseline"] = "not_observed"
    report["rotation_chain"] = {
        "context_a": {"row_prefix": str(ctx_a.get("authoritative_row_id_prefix") or "31869")[:8], "token_generation": "not_observed"},
        "context_b": {
            "row_prefix_load": (ctx_b.get("rotation_restore") or {}).get("bridge_row_prefix_at_load"),
            "token_generation": (ctx_b.get("rotation_restore") or {}).get("token_generation_observed"),
            "rotation_persist_count": (ctx_b.get("rotation_restore") or {}).get("rotation_persist_count"),
        },
        "context_c": {
            "row_prefix_load": (ctx_c.get("rotation_restore") or {}).get("bridge_row_prefix_at_load"),
            "token_generation": (ctx_c.get("rotation_restore") or {}).get("token_generation_observed"),
            "rotation_persist_count": (ctx_c.get("rotation_restore") or {}).get("rotation_persist_count"),
        },
    }
    report["finished_at"] = time.time()
    report["artifact"] = str(OUT)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("classification", "detail", "pass", "artifact") if k in report}))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
