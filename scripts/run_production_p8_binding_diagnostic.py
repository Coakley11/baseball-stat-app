"""Focused Cloud P8 transport/binding ladder — one expiration, no Stage 1A grade."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "production_p8_binding_diagnostic.json"
HEARTBEAT_OUT = ROOT / "data" / "production_p8_binding_diagnostic_heartbeat.json"
LOG_OUT = ROOT / "data" / "p8_binding_handoff_run.out"
SCREENSHOT_DIR = ROOT / "data" / "p8_focused_binding_screenshots"
BASELINE_PATH = ROOT / "data" / "stage1a_4fa3d42_core_harness11979f5.out"
PRODUCTION_WIDGET_KEY = "solo_countdown_wake_solo_persistent"


def p8_focused_production_url(*, harness_run_id: str = "") -> str:
    from run_production_stage1_authenticated import production_url

    base = production_url()
    join = "&" if "?" in base else "?"
    parts = [base]
    if "solo_p8_focused_binding=" not in base:
        parts.append(f"{join}solo_p8_focused_binding=1")
        join = "&"
    run = str(harness_run_id or "").strip().lower()
    if run and "solo_p8_harness_run_id=" not in base:
        parts.append(f"{join}solo_p8_harness_run_id={run}")
    return "".join(parts)

P8_ORDER = (
    ("P8-L1", "browser_deadline_crossed"),
    ("P8-L2", "expiration_send_claimed"),
    ("P8-L3", "transport_before_postMessage"),
    ("P8-L4", "immediate_parent_setComponentValue"),
    ("P8-L5", "event_source_matches_connected_iframe"),
    ("P8-L6", "streamlit_protocol_accepted"),
    ("P8-L7", "direct_component_return_exact_token"),
    ("P8-L8", "session_state_exact_token"),
    ("P8-L9", "process_production_expire_token_entered"),
)

P8BIND_MAP = {
    "P8-L1": "P8A",
    "P8-L2": "P8A",
    "P8-L3": "P8A",
    "P8-L4": "P8BIND1",
    "P8-L5": "P8BIND2",
    "P8-L6": "P8BIND3",
    "P8-L7": "P8BIND4",
    "P8-L8": "P8BIND5",
    "P8-L9": "P8BIND6",
}


def resolve_required_sha() -> str:
    """Required binding implementation anchor from deploy pin (not stale env)."""
    pin = ""
    try:
        line = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0]
        pin = line.split("#", 1)[0].strip().lower()[:7]
    except Exception:
        pin = ""
    if pin:
        return pin
    return str(os.environ.get("REQUIRED_CLOUD_SHA") or "").strip().lower()[:7]


def _persist_partial(report: dict[str, Any], *, phase: str) -> None:
    report["last_persist_phase"] = phase
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    try:
        from p8_focused_binding_heartbeat import write_heartbeat

        write_heartbeat(
            phase,
            required_cloud_sha=str(report.get("required_cloud_sha") or ""),
            observed_cloud_sha=str(report.get("cloud_sha") or ""),
            extra={"diagnostic_run_id": report.get("diagnostic_run_id")},
        )
    except Exception:
        pass


def _screenshot(page, name: str, run_id: str) -> str:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"{run_id}_{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        return str(path)
    except Exception:
        return ""


def _ledger_rows(exp: dict[str, Any]) -> list[dict[str, Any]]:
    filtered = exp.get("filtered_ledger_rows")
    if isinstance(filtered, list) and filtered:
        return [r for r in filtered if isinstance(r, dict)]
    meta = exp.get("ledger_meta") or {}
    rows = list(meta.get("merged_server_ledger") or [])
    if not rows:
        rows = list(exp.get("merged_server_ledger") or [])
    return [r for r in rows if isinstance(r, dict)]


    filtered = exp.get("filtered_ledger_rows")
    if isinstance(filtered, list) and filtered:
        return [r for r in filtered if isinstance(r, dict)]
    meta = exp.get("ledger_meta") or {}
    rows = list(meta.get("merged_server_ledger") or [])
    if not rows:
        rows = list(exp.get("merged_server_ledger") or [])
    return [r for r in rows if isinstance(r, dict)]


def _infer_run_id(rows: list[dict[str, Any]], room_id: str) -> str:
    room = str(room_id or "").strip().upper()
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        rr = str(row.get("room_id") or "").strip().upper()
        if room and rr and rr != room:
            continue
        rid = str(row.get("run_id") or "").strip()
        if rid:
            counts[rid] = counts.get(rid, 0) + 1
    if not counts:
        for row in rows:
            rid = str(row.get("run_id") or "").strip()
            if rid:
                counts[rid] = counts.get(rid, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def classify_contradiction_root_cause(
    *,
    unfiltered_rows: list[dict[str, Any]],
    filtered_meta: dict[str, Any],
    python_chain: dict[str, Any],
    gate_rows: list[dict[str, Any]],
) -> str:
    obs_before = sum(
        1
        for r in unfiltered_rows
        if isinstance(r, dict) and r.get("event") == "production_stage1_delivery_only_observation_completed"
    )
    obs_after = sum(
        1
        for r in filtered_meta.get("filtered_rows") or []
        if isinstance(r, dict) and r.get("event") == "production_stage1_delivery_only_observation_completed"
    )
    flush_before = sum(
        1
        for r in unfiltered_rows
        if isinstance(r, dict) and r.get("event") == "production_stage1_post_bind_actionable_flush"
    )
    flush_after = sum(
        1
        for r in filtered_meta.get("filtered_rows") or []
        if isinstance(r, dict) and r.get("event") == "production_stage1_post_bind_actionable_flush"
    )
    if (obs_before or flush_before) and obs_after == 0 and flush_after == 0:
        return "P8C4"
    if gate_rows:
        decisions = {str(g.get("decision") or "") for g in gate_rows if isinstance(g, dict)}
        if "reject_mount_token_not_bound" in decisions:
            return "P8C1"
        if "reject_pending_token_not_bound" in decisions:
            return "P8C2"
        if any(d.startswith("pass_") for d in decisions) and not python_chain.get("bound_in_python_surfaces"):
            return "P8C3"
    if (obs_after or flush_after) and not python_chain.get("bound_in_python_surfaces"):
        for row in filtered_meta.get("filtered_rows") or []:
            if not isinstance(row, dict):
                continue
            if row.get("event") == "production_stage1_post_bind_actionable_flush":
                src = str(row.get("bound_token_source") or "")
                if src in ("", "mount_token", "expected_token"):
                    return "P8C5"
    if python_chain.get("bound_in_python_surfaces") and not python_chain.get("reaches_process_with_exact_token"):
        return "P8C7"
    if not python_chain.get("bound_in_python_surfaces"):
        return "P8BIND4"
    return "P8C8"

def _production_countdown_send_evidence(exp: dict[str, Any], rv: dict[str, Any]) -> dict[str, Any]:
    double = dict((rv.get("browser") or {}).get("double_production_send_analysis") or exp.get("double_production_send_analysis") or {})
    timeline = list(double.get("timeline") or [])
    prod_rows = [r for r in timeline if isinstance(r, dict) and r.get("widget_key") == PRODUCTION_WIDGET_KEY]
    prod_stages = {str(r.get("stage") or "") for r in prod_rows}
    send_previews = [str(r.get("token_preview") or "") for r in prod_rows if r.get("token_preview")]
    return {
        "production_timeline_rows": len(prod_rows),
        "production_stages": sorted(prod_stages),
        "production_send_token_previews": send_previews,
        "deadline_crossed": "browser_deadline_crossed" in prod_stages,
        "expiration_send_claimed": "expiration_send_claimed" in prod_stages
        or "component_value_sent" in prod_stages
        or "transport_before_postMessage" in prod_stages,
        "postmessage_attempted": bool(
            prod_stages & {"transport_before_postMessage", "transport_postmessage_invoked", "component_value_sent"}
        ),
    }


def _iframe_source_grading(exp: dict[str, Any], rv: dict[str, Any]) -> dict[str, Any]:
    browser = rv.get("browser") or {}
    levels = browser.get("authoritative_receipt_levels") or {}
    sink = dict(exp.get("parent_event_sink") or {})
    sink_logic = sink.get("logical") or {}
    assoc = (sink_logic.get("source_association") or {}) if isinstance(sink_logic, dict) else {}
    if not assoc:
        primary = {}
        scv_rows = sink_logic.get("scv_logical_receipts") if isinstance(sink_logic, dict) else None
        if isinstance(scv_rows, list) and scv_rows:
            primary = scv_rows[0].get("source_association") or {}
        assoc = primary if isinstance(primary, dict) else {}
    prod_match_count = int(assoc.get("production_countdown_match_count") or 0)
    primary_match = assoc.get("primary_match") or {}
    is_prod = bool(primary_match.get("is_production_countdown"))
    level3 = bool(
        levels.get("LEVEL_3_CURRENT_COMPONENT_SOURCE_MATCH_IMMEDIATE")
        or levels.get("LEVEL_3_CURRENT_COMPONENT_SOURCE_MATCH_TOP")
    )
    authoritative = prod_match_count >= 1 and is_prod and level3
    if prod_match_count >= 1 and is_prod and not level3:
        grade = "NOT_AUTHORITATIVELY_GRADED"
        pass_l5 = None
    elif prod_match_count == 0 and not is_prod and int(sink_logic.get("scv_count") or 0) >= 1:
        grade = "NOT_AUTHORITATIVELY_GRADED"
        pass_l5 = None
    elif authoritative:
        grade = "AUTHORITATIVE_PASS"
        pass_l5 = True
    elif level3 is False and int(sink_logic.get("scv_count") or 0) >= 1 and prod_match_count == 0:
        grade = "AUTHORITATIVE_FAIL"
        pass_l5 = False
    else:
        grade = "NOT_AUTHORITATIVELY_GRADED"
        pass_l5 = None
    return {
        "grading": grade,
        "pass": pass_l5,
        "production_countdown_match_count": prod_match_count,
        "primary_match": primary_match,
        "durable_sink_scv_count": int(sink_logic.get("scv_count") or 0),
        "browser_level3": level3,
        "browser_level4": levels.get("LEVEL_4_STREAMLIT_PROTOCOL_ACCEPTED"),
        "browser_level5": levels.get("LEVEL_5_PYTHON_VALUE_BOUND"),
        "note": "Browser LEVEL_4/5 are reported separately; not used alone for production transport failure.",
    }


def _python_binding_chain(exp: dict[str, Any], rv: dict[str, Any], token: str) -> dict[str, Any]:
    py = rv.get("python_component") or {}
    audit = dict(exp.get("stage1_audit") or exp.get("audit") or {})
    callbacks = list(audit.get("callbacks") or [])
    ledger = _ledger_rows(exp)
    coalesced = str(py.get("coalesced_component_value") or "")
    ss_val = str(py.get("session_state_widget_value_transport_scrape") or "")
    decl_ret = str(py.get("direct_component_return_declaration") or "")
    mount_ret = str(py.get("direct_component_return_mount_diag") or "")
    direct = coalesced or decl_ret or mount_ret
    handoff_rows = [
        r
        for r in ledger
        if str(r.get("event") or "") == "production_stage1_callback_handoff_written"
        and (not token or str(r.get("raw_token") or "") == token)
    ]
    handoff_token = str((handoff_rows[-1] if handoff_rows else {}).get("raw_token") or "")
    bound_in_python = bool(
        token
        and (
            token in direct
            or token in ss_val
            or token == handoff_token
            or any(str(r.get("equals_expected")) == "True" for r in handoff_rows if str(r.get("raw_token") or "") == token)
        )
    )
    obs_claims = [
        c
        for c in callbacks
        if c.get("delivery_claimed") and str(c.get("callback_source") or "") == "return_value_session_bind"
    ]
    obs_events = [
        r
        for r in ledger
        if str(r.get("event") or "") == "production_stage1_delivery_only_observation_completed"
        and (not token or str(r.get("bound_token") or r.get("token") or "") == token)
        and str(r.get("bound_token_source") or "") in (
            "direct_component_return",
            "same_key_session_state",
            "durable_callback_handoff",
        )
        and r.get("exact_match") is True
    ]
    post_bind = [
        r
        for r in ledger
        if str(r.get("event") or "") == "production_stage1_post_bind_actionable_flush"
        and (not token or str(r.get("bound_token") or "") == token)
        and str(r.get("bound_token_source") or "") in (
            "direct_component_return",
            "same_key_session_state",
            "durable_callback_handoff",
        )
    ]
    flush_events = [
        r
        for r in ledger
        if str(r.get("event") or "")
        in (
            "production_stage1_post_bind_actionable_flush",
            "production_stage1_flush_persistent_wake_delivery_entry",
            "production_stage1_return_value_session_bind_entry",
        )
    ]
    post_bind_flush = post_bind
    rv_bind_entry = [r for r in flush_events if r.get("event") == "production_stage1_return_value_session_bind_entry"]
    proc_events = [
        r
        for r in ledger
        if str(r.get("event") or "") == "production_stage1_process_production_expire_token_entry"
        and (not token or str(r.get("expected_token") or r.get("token") or "") == token)
    ]
    source_boundary_ok = True
    for c in callbacks:
        if c.get("reject_code") == "callback_source_not_allowed":
            source_boundary_ok = False
    actionable_accepted = [
        c
        for c in callbacks
        if c.get("delivery_claimed")
        and not c.get("reject_code")
        and str(c.get("callback_source") or "") == "return_value_session_bind"
    ]
    ledger_accepted = sum(
        1
        for r in ledger
        if isinstance(r, dict)
        and str(r.get("event") or "") == "production_stage1_token_claim_result"
        and r.get("accepted") is True
    )
    ledger_try_claim = sum(
        1
        for r in ledger
        if isinstance(r, dict) and str(r.get("event") or "") == "production_stage1_try_claim_about_to_call"
    )
    ledger_autopick = sum(
        1
        for r in ledger
        if isinstance(r, dict) and str(r.get("event") or "") == "production_stage1_autopick_about_to_enter"
    )
    ledger_commits = sum(
        1
        for r in ledger
        if isinstance(r, dict) and str(r.get("event") or "") == "production_stage1_token_action_complete"
    )
    observation_zero_claims = len(obs_claims) == 0 and ledger_accepted == 0 and ledger_autopick == 0
    return {
        "exact_token": token,
        "direct_return": direct,
        "session_state_value": ss_val,
        "coalesced_value": coalesced,
        "bound_in_python_surfaces": bound_in_python,
        "delivery_only_observation_events": len(obs_events),
        "observation_claims_count": len(obs_claims),
        "observation_zero_claims": observation_zero_claims,
        "ledger_accepted_claims": ledger_accepted,
        "ledger_try_claim_calls": ledger_try_claim,
        "ledger_autopick_entries": ledger_autopick,
        "ledger_committed_picks": ledger_commits,
        "post_bind_flush_events": len(post_bind_flush),
        "flush_or_bind_entry_events": len(flush_events),
        "return_value_session_bind_entry_events": len(rv_bind_entry),
        "process_production_expire_token_entries": len(proc_events),
        "callback_source_authorization_ok": source_boundary_ok,
        "actionable_accepted_count": len(actionable_accepted),
        "reaches_process_with_exact_token": bool(proc_events and bound_in_python),
    }


def evaluate_p8_ladder(
    exp: dict[str, Any], rv: dict[str, Any], *, start_val: dict[str, Any] | None = None
) -> dict[str, Any]:
    cs = set(exp.get("client_stages") or [])
    browser = rv.get("browser") or {}
    levels_auth = browser.get("authoritative_receipt_levels") or {}
    py = rv.get("python_component") or {}
    prod_send = _production_countdown_send_evidence(exp, rv)
    iframe_grade = _iframe_source_grading(exp, rv)
    token = str(
        exp.get("token_sent")
        or browser.get("exact_expiration_token")
        or (prod_send.get("production_send_token_previews") or [""])[0]
        or py.get("expected_canonical_token_mount_diag")
        or (start_val or {}).get("authoritative_state", {}).get("production_token")
        or (start_val or {}).get("authoritative_state", {}).get("expire_token")
        or ""
    ).strip()
    if token and "|" in token and token.endswith("|"):
        token = token.rstrip("|")
    python_chain = _python_binding_chain(exp, rv, token)

    checks: dict[str, Any] = {}
    checks["P8-L1"] = bool(prod_send.get("deadline_crossed") or "browser_deadline_crossed" in cs)
    checks["P8-L2"] = bool(prod_send.get("expiration_send_claimed"))
    checks["P8-L3"] = bool(prod_send.get("postmessage_attempted"))
    sink_logic = (exp.get("parent_event_sink") or {}).get("logical") or {}
    checks["P8-L4"] = bool(
        int(sink_logic.get("scv_count") or 0) >= 1
        or levels_auth.get("LEVEL_2_ACTUAL_IMMEDIATE_PARENT_FRAME2")
    )
    if iframe_grade.get("grading") == "NOT_AUTHORITATIVELY_GRADED":
        checks["P8-L5"] = "NOT_AUTHORITATIVELY_GRADED"
    else:
        checks["P8-L5"] = bool(iframe_grade.get("pass"))
    checks["P8-L6"] = "INFORMATIONAL_ONLY"
    checks["P8-L7"] = bool(python_chain.get("bound_in_python_surfaces"))
    checks["P8-L8"] = bool(token and token in str(python_chain.get("session_state_value") or ""))
    checks["P8-L9"] = bool(python_chain.get("reaches_process_with_exact_token"))

    authoritative_steps: list[tuple[str, bool | None, str]] = [
        ("AUTH-1_production_send", checks["P8-L1"] and checks["P8-L2"] and checks["P8-L3"], "P8A"),
        ("AUTH-2_python_bound_token", bool(checks["P8-L7"]), "P8BIND4"),
        (
            "AUTH-3_delivery_only_observation_exact",
            python_chain.get("delivery_only_observation_events", 0) >= 1
            and python_chain.get("observation_zero_claims")
            and python_chain.get("bound_in_python_surfaces"),
            "P8BIND6",
        ),
        (
            "AUTH-4_post_bind_flush",
            python_chain.get("post_bind_flush_events", 0) >= 1
            or python_chain.get("return_value_session_bind_entry_events", 0) >= 1,
            "P8BIND6",
        ),
        (
            "AUTH-5_process_entry_exact_token",
            bool(checks["P8-L9"]) and python_chain.get("callback_source_authorization_ok"),
            "P8BIND6",
        ),
    ]
    if iframe_grade.get("grading") == "AUTHORITATIVE_FAIL":
        authoritative_steps.insert(
            1,
            ("AUTH-1b_production_iframe_source", False, "P8BIND2"),
        )
    elif iframe_grade.get("grading") == "AUTHORITATIVE_PASS":
        authoritative_steps.insert(1, ("AUTH-1b_production_iframe_source", True, "P8BIND2"))

    first_missing = ""
    classification = "P8BIND7"
    for step_id, ok, bind_code in authoritative_steps:
        if ok is False:
            first_missing = step_id
            classification = bind_code
            break
    else:
        classification = "P8_ALL_BOUNDARIES_PASS"

    authoritative_pass = classification == "P8_ALL_BOUNDARIES_PASS" and all(
        s[1] for s in authoritative_steps if s[1] is not None
    )

    ladder_detail = [{"level": k, "pass": v} for k, v in checks.items()]
    sink_row = (sink_logic.get("scv_logical_receipts") or []) if isinstance(sink_logic, dict) else []
    primary_scv = sink_row[0] if sink_row else {}

    return {
        "exact_token": token,
        "widget_key": PRODUCTION_WIDGET_KEY,
        "room_id": str(rv.get("room_id") or exp.get("room_id") or ""),
        "production_sha": str(rv.get("cloud_sha") or exp.get("cloud_sha") or ""),
        "checks": checks,
        "ladder_detail": ladder_detail,
        "first_missing_level": first_missing or None,
        "classification": classification,
        "authoritative_pass": authoritative_pass,
        "authoritative_steps": [
            {"step": s[0], "pass": s[1], "bind_code": s[2]} for s in authoritative_steps
        ],
        "production_countdown_send": prod_send,
        "minimal_diag_iframe": iframe_grade,
        "python_binding_chain": python_chain,
        "authoritative_receipt_levels": levels_auth,
        "durable_sink_scv_count": int(sink_logic.get("scv_count") or 0),
        "component_return_value": python_chain.get("direct_return"),
        "session_state_value": python_chain.get("session_state_value"),
        "iframe_identity": {
            "iframe_remounts": browser.get("iframe_remounts"),
            "tick_cancellations": browser.get("tick_cancellations"),
            "primary_scv_iframe_instance": str(primary_scv.get("iframe_instance_id") or ""),
            "source_association": primary_scv.get("source_association") or iframe_grade.get("primary_match"),
        },
        "comparison_notes": [],
    }


def authoritative_diagnostic_pass(ladder: dict[str, Any]) -> bool:
    chain = ladder.get("python_binding_chain") or {}
    token = str(ladder.get("exact_token") or "")
    if not token:
        return False
    if not chain.get("bound_in_python_surfaces"):
        return False
    if not chain.get("observation_zero_claims"):
        return False
    if chain.get("delivery_only_observation_events", 0) < 1 and not chain.get("post_bind_flush_events"):
        return False
    if not chain.get("callback_source_authorization_ok"):
        return False
    if chain.get("process_production_expire_token_entries", 0) < 1:
        return False
    return bool(ladder.get("authoritative_pass"))


def load_baseline_summary() -> dict[str, Any]:
    if not BASELINE_PATH.is_file():
        return {}
    try:
        data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    rv = data.get("return_value_chain") or {}
    br = rv.get("browser") or {}
    return {
        "cloud_sha": "4fa3d42",
        "widget_key": PRODUCTION_WIDGET_KEY,
        "component_value_sent": br.get("component_value_sent"),
        "LEVEL_5_PYTHON_VALUE_BOUND": (br.get("authoritative_receipt_levels") or {}).get("LEVEL_5_PYTHON_VALUE_BOUND"),
        "durable_sink_scv_count": (br.get("authoritative_receipt_levels") or {}).get("durable_sink_scv_count"),
        "return_value_session_bind_accepted": True,
        "callback_timeline_len": len((rv.get("delivery") or {}).get("callback_timeline") or []),
    }


def compare_traces(current: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    if not baseline:
        notes.append("baseline_4fa3d42_harness_not_loaded")
        return notes
    if baseline.get("LEVEL_5_PYTHON_VALUE_BOUND") and not current.get("authoritative_receipt_levels", {}).get(
        "LEVEL_5_PYTHON_VALUE_BOUND"
    ):
        notes.append("4fa3d42_had_python_bind_current_does_not")
    if int(baseline.get("durable_sink_scv_count") or 0) >= 1 and int(current.get("durable_sink_scv_count") or 0) == 0:
        notes.append("4fa3d42_durable_parent_scv_present_current_absent")
    if current.get("checks", {}).get("P8-L3") and not current.get("checks", {}).get("P8-L4"):
        notes.append("browser_send_claimed_but_immediate_parent_missed_scv")
    if current.get("checks", {}).get("P8-L4") and not current.get("checks", {}).get("P8-L5"):
        notes.append("parent_received_scv_but_source_not_matched_to_connected_iframe")
    if current.get("iframe_identity", {}).get("iframe_remounts", 0) and int(
        current.get("iframe_identity", {}).get("iframe_remounts") or 0
    ) >= 1:
        notes.append("iframe_remount_observed_during_window")
    return notes


def run_diagnostic() -> dict[str, Any]:
    required = resolve_required_sha()
    from p8_canary_build_gate import (
        commit_has_binding_correction,
        evaluate_cloud_binding_readiness,
        git_head_short,
        local_deploy_pin,
        poll_live_cloud_sha,
        scrape_cloud_runtime_deploy_probe,
    )
    from replay_playwright_daniel_auth_preflight import run_preflight
    from playwright_daniel_auth_session import STORAGE_PATH, harness_ready
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from p8_canonical_production_start import establish_single_solo_live_draft
    from p8_focused_setup_classify import FOCUSED_SETUP_TRACE, classify_focused_setup_boundary
    from run_production_stage1_authenticated import (
        build_return_value_chain_report,
        build_parent_boundary_validation,
        ensure_fresh_setup_lobby,
        production_url,
        validate_production_draft_start,
        wait_one_expiration,
        authenticated_probe,
    )
    from p8_diagnostic_setup import (
        classify_focused_p8_outcome,
        collect_setup_stage_diagnostics,
        ensure_p8_ldr_setup_surface,
        score_bound_token_gate_rows,
    )
    from run_production_solo_soak import scrape_deploy_build
    from run_solo_clean_verification import scrape_live_sha
    from stage1_parent_event_sink import ParentEventSinkStore, install_parent_event_sink

    if not harness_ready():
        return {"aborted": True, "reason": "auth_harness_incomplete"}
    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        return {"aborted": True, "reason": "auth_replay_preflight_failed", "preflight": pre}

    report: dict[str, Any] = {
        "started_at": time.time(),
        "required_cloud_sha": required,
        "diagnostic_run_id": "",
        "mode": "p8_binding_diagnostic",
        "git_head": git_head_short(),
        "deploy_pin": local_deploy_pin(),
        "implementation_presence_at_required": commit_has_binding_correction(required),
        "accepted_root_cause": "BIND5",
    }
    from p8_focused_binding_heartbeat import (
        configure_diagnostic_log_path,
        diagnostic_run_id,
        log_line,
        write_heartbeat,
    )
    from p8_focused_diagnostic_lock import acquire_focused_diagnostic_lock, release_focused_diagnostic_lock
    from p8_focused_gate_readiness import poll_focused_gate_deploy_readiness

    report["diagnostic_run_id"] = diagnostic_run_id()
    report["harness_run_id"] = report["diagnostic_run_id"]
    report["application_diagnostic_run_id"] = ""
    per_run_log = ROOT / "data" / f"p8_binding_{report['harness_run_id']}.out"
    report["log_path"] = str(per_run_log)
    configure_diagnostic_log_path(per_run_log)
    ok_lock, lock_msg = acquire_focused_diagnostic_lock(
        harness_run_id=report["harness_run_id"],
        log_path=per_run_log,
    )
    if not ok_lock:
        report["aborted"] = True
        report["abort_reason"] = lock_msg
        report["focused_p8_outcome"] = lock_msg.split(" — ", 1)[0] if " — " in lock_msg else lock_msg
        log_line(lock_msg)
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        return report
    log_line(f"focused_p8_binding_diagnostic start required_sha={required}")
    write_heartbeat("deploy_poll_start", required_cloud_sha=required, extra={"diagnostic_phase": "deploy_readiness"})
    deploy_wait_cap_s = 900.0

    def _on_poll(row: dict[str, Any], poll_report: dict[str, Any]) -> None:
        readiness = row.get("binding_readiness") or {}
        write_heartbeat(
            "deploy_poll_attempt",
            required_cloud_sha=required,
            observed_cloud_sha=str(row.get("sha") or poll_report.get("live_sha") or ""),
            extra={
                "poll_attempt": row.get("attempt"),
                "build": row.get("build"),
                "binding_readiness_ok": readiness.get("ok"),
                "readiness_result": readiness.get("ok"),
                "focused_gate_ok": row.get("focused_gate_ok"),
                "diagnostic_phase": "deploy_readiness",
                "elapsed_readiness_s": row.get("elapsed_s"),
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )

    poll = poll_focused_gate_deploy_readiness(
        required_sha=required,
        cap_s=deploy_wait_cap_s,
        poll_s=25.0,
        nav_timeout_s=90,
        on_poll_attempt=_on_poll,
    )
    report["deploy_poll"] = poll
    readiness = poll.get("binding_readiness") or {}
    report["cloud_binding_readiness"] = readiness
    report["focused_gate_runtime_presence"] = poll.get("focused_gate_presence") or {}
    live_runtime = str(readiness.get("runtime_git_head_short") or poll.get("live_sha") or "")
    report["implementation_presence_at_live"] = commit_has_binding_correction(live_runtime)
    if not poll.get("ok"):
        live = str(poll.get("live_sha") or readiness.get("runtime_git_head_short") or "")
        impl_live = report.get("implementation_presence_at_live") or commit_has_binding_correction(live)
        handoff_missing = not impl_live.get("prod_callback_handoff_module")
        if live.startswith("6d24920") or (live and handoff_missing and required.startswith("22ce3e3")):
            focused = "INVALID_CALLBACK_HANDOFF_NOT_DEPLOYED"
            boundary = "INVALID_CALLBACK_HANDOFF_NOT_DEPLOYED — RUNTIME MISSING 22ce3e3 HANDOFF BYTECODE"
        elif required.startswith("a5516e4") or required == "a5516e4":
            focused = "INVALID_FOCUSED_GATE_NOT_DEPLOYED"
            boundary = (
                "INVALID_FOCUSED_GATE_NOT_DEPLOYED — AUTHORIZED FOCUSED STOP-BEFORE-CLAIM GATE NOT ON CLOUD"
            )
        else:
            focused = "INVALID_FIX_NOT_DEPLOYED"
            boundary = "INVALID_FIX_NOT_DEPLOYED — BIND5 BYTECODE NOT ON CLOUD RUNTIME"
        report["aborted"] = True
        report["abort_reason"] = "cloud_binding_readiness_not_proven_before_diagnostic"
        report["focused_p8_outcome"] = focused
        report["failure_boundary"] = boundary
        report["deploy_wait"] = {
            "cap_s": deploy_wait_cap_s,
            "elapsed_s": poll.get("elapsed_s"),
            "poll_count": poll.get("poll_count"),
            "observed_sha": live,
            "observed_build": poll.get("live_build"),
            "required_sha": required,
            "last_heartbeat_path": str(HEARTBEAT_OUT),
        }
        write_heartbeat(
            "aborted_deploy_readiness",
            required_cloud_sha=required,
            observed_cloud_sha=live,
            extra={"focused_p8_outcome": focused, "diagnostic_phase": "aborted"},
        )
        log_line(focused)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        release_focused_diagnostic_lock()
        return report
    if not report["implementation_presence_at_live"].get("ok"):
        report["aborted"] = True
        report["abort_reason"] = "binding_correction_not_present_at_runtime_git"
        report["focused_p8_outcome"] = "INVALID_FIX_NOT_DEPLOYED"
        report["failure_boundary"] = "INVALID_FIX_NOT_DEPLOYED — RUNTIME IMPLEMENTATION CHECKS FAILED"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        return report
    parent_sink = ParentEventSinkStore()
    url = p8_focused_production_url(harness_run_id=str(report.get("harness_run_id") or ""))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
        try:
            from stage1_parent_observer_probe import HARNESS_TOP_OBSERVER_INIT_SCRIPT
            from stage1_harness_observability import LEDGER_DURABLE_INIT_SCRIPT

            context.add_init_script(HARNESS_TOP_OBSERVER_INIT_SCRIPT)
            context.add_init_script(LEDGER_DURABLE_INIT_SCRIPT)
        except ImportError:
            pass
        page = context.new_page()
        from p8_ledger_observability import (
            OUT_AFTER_SEND,
            OUT_FINAL,
            OUT_PRE,
            P8LedgerHarnessCollector,
            audit_stored_diagnostic_artifact,
            capture_all_ledger_sources,
            classify_observability_failure,
            enrich_expiration_ledger,
            observability_validity_gate,
            summarize_filter_rejections,
            write_checkpoint,
        )

        collector = P8LedgerHarnessCollector()
        report["d73bcf3_observability_audit"] = audit_stored_diagnostic_artifact(OUT) if OUT.is_file() else {}
        report["parent_event_sink_install"] = install_parent_event_sink(page, parent_sink)
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(15000)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(3000)
        except Exception:
            pass
        page.wait_for_timeout(20000)
        runtime_dom = scrape_cloud_runtime_deploy_probe(page)
        sha = (runtime_dom.get("runtime_git_head_short") or scrape_live_sha(page) or scrape_deploy_build(page) or "")[:7].lower()
        report["cloud_sha"] = sha
        report["cloud_runtime_probe"] = runtime_dom
        report["cloud_build"] = runtime_dom.get("marker_build") or (f"baseball-dev-{required[:7]}" if required else "")
        live_ready = evaluate_cloud_binding_readiness(
            runtime_git_head_short=runtime_dom.get("runtime_git_head_short") or sha,
            marker_sha=runtime_dom.get("marker_sha") or "",
            marker_build=str(report["cloud_build"] or ""),
            deploy_pin=local_deploy_pin(),
            runtime_deploy_raw=runtime_dom.get("runtime_deploy_commit_raw") or "",
        )
        report["cloud_binding_readiness_at_run"] = live_ready
        if not live_ready.get("ok"):
            report["aborted"] = True
            report["abort_reason"] = "cloud_binding_readiness_lost_at_run"
            report["focused_p8_outcome"] = "INVALID_FIX_NOT_DEPLOYED"
            context.close()
            browser.close()
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            return report

        cleanup = ensure_fresh_setup_lobby(page)
        report["cleanup"] = cleanup
        if not cleanup.get("ok"):
            report["aborted"] = True
            report["abort_reason"] = "setup_lobby_blocked"
            context.close()
            browser.close()
            return report

        report["p8_ldr_surface"] = ensure_p8_ldr_setup_surface(page, setup_url=url)
        run_id = str(report.get("diagnostic_run_id") or "")
        report["screenshots"] = {
            "before_start": _screenshot(page, "before_start", run_id),
        }
        _persist_partial(report, phase="before_canonical_start")

        start_val = establish_single_solo_live_draft(
            page,
            context,
            setup_url=url,
            prior_room_id=str(cleanup.get("detected_room_id") or ""),
            fresh_lobby_cleanup=False,
            max_wait_s=90.0,
        )
        report["application_diagnostic_run_id"] = str(
            start_val.get("application_diagnostic_run_id") or start_val.get("diagnostic_run_id") or ""
        )
        from p8_room_latch_reconcile import build_room_timeline_rows, replay_artifact_latch

        report["room_latch_timeline"] = build_room_timeline_rows(
            full_rows=list((start_val.get("latch_ledger_export") or {}).get("rows") or []),
            filtered_rows=list((start_val.get("latch_ledger_export") or {}).get("rows") or []),
            timeline=list(start_val.get("room_state_timeline") or []),
            harness_run_id=report["harness_run_id"],
            application_diagnostic_run_id=report["application_diagnostic_run_id"],
            streamlit_session_id=str(start_val.get("streamlit_session_id") or ""),
            created_room_id=str(start_val.get("room_id") or ""),
        )
        report["screenshots"]["after_start"] = _screenshot(page, "after_start", run_id)
        report["production_setup"] = start_val
        report["harness_chain"] = start_val.get("canonical_chain")
        report["identity_timeline"] = start_val.get("identity_timeline")
        report["draft_start_workflow"] = {
            "helper_name": start_val.get("helper_name"),
            "click_count": start_val.get("click_count"),
            "room_id": start_val.get("room_id"),
            "room_latch_pass": start_val.get("room_latch_pass"),
            "start_click": start_val.get("start_click"),
            "start_click_transport": start_val.get("start_click_transport"),
        }
        report["setup_stage_diagnostics"] = collect_setup_stage_diagnostics(
            page, draft=report["draft_start_workflow"], auth_preflight=pre
        )
        report["setup_stage_timeline"] = start_val.get("room_state_timeline") or []
        report["draft_start_validation"] = start_val
        _persist_partial(report, phase="after_canonical_start")

        if not start_val.get("valid"):
            setup_cls = classify_focused_setup_boundary(start_result=start_val)
            report["focused_setup_classification"] = setup_cls
            report["artifact_latch_replay"] = replay_artifact_latch({**report, "production_setup": start_val})
            report["aborted"] = True
            report["abort_reason"] = setup_cls.get("focused_p8_outcome") or FOCUSED_SETUP_TRACE
            report["focused_p8_outcome"] = setup_cls.get("focused_p8_outcome") or FOCUSED_SETUP_TRACE
            report["failure_boundary"] = setup_cls.get("classification") or "LATCHREC8"
            report["setup_abort_reason"] = setup_cls.get("reason")
            report["accepted_run_label"] = (
                "ROOM_CREATED — ROOM_LATCH_RECONCILIATION_REQUIRED"
                if report["focused_p8_outcome"] == "ROOM_CREATED — ROOM_LATCH_RECONCILIATION_REQUIRED"
                else ""
            )
            report["setup_trace_note"] = (
                "Start transition not authoritatively observed; "
                "not classified as callback-handoff or application room-not-created defect."
            )
            if report["artifact_latch_replay"].get("room_latch_pass_reconciled"):
                report["room_latch_pass_reconciled"] = True
                report["failure_boundary"] = report["artifact_latch_replay"]["latch_reconciliation"].get(
                    "classification", "LATCHREC1"
                )
            context.close()
            browser.close()
            _persist_partial(report, phase="aborted_setup_trace")
            return report

        pre_cap = capture_all_ledger_sources(page)
        latch_export = list((start_val.get("latch_ledger_export") or {}).get("rows") or [])
        if latch_export:
            merged_pre = list(pre_cap.get("merged_incoming") or [])
            seen = {json.dumps(r, sort_keys=True, default=str) for r in merged_pre if isinstance(r, dict)}
            for row in latch_export:
                if not isinstance(row, dict):
                    continue
                key = json.dumps(row, sort_keys=True, default=str)
                if key not in seen:
                    merged_pre.append(row)
                    seen.add(key)
            pre_cap["merged_incoming"] = merged_pre
            pre_cap["latch_ledger_rows_merged"] = len(latch_export)
        collector.absorb_capture(pre_cap, label="pre_expiration_setup")
        write_checkpoint(
            OUT_PRE,
            {
                "capture": pre_cap,
                "collector_peak": len(collector.peak_rows()),
                "room_id": start_val.get("latched_room_id"),
                "cloud_sha": sha,
            },
        )

        page.wait_for_timeout(8000)
        exp = wait_one_expiration(page, timeout_s=95.0, parent_sink=parent_sink)
        enrich_expiration_ledger(page, exp, collector, label="post_expiration_enrich")
        write_checkpoint(
            OUT_AFTER_SEND,
            {
                "collector_peak": len(collector.peak_rows()),
                "ledger_meta": exp.get("ledger_meta"),
                "merged_count": len(exp.get("merged_server_ledger") or []),
            },
        )
        exp["cloud_sha"] = sha
        exp["room_id"] = start_val.get("latched_room_id")
        cloud_build = report.get("cloud_build") or ""
        rv = build_return_value_chain_report(
            page,
            exp,
            start_val=start_val,
            queue_meta={"queue_independence": "NOT EXERCISED — EMPTY QUEUE"},
            cloud_sha=sha,
            cloud_build=cloud_build,
        )
        exp["double_production_send_analysis"] = (rv.get("browser") or {}).get(
            "double_production_send_analysis"
        )
        exp["stage1_audit"] = exp.get("stage1_audit") or exp.get("audit")
        unfiltered = _ledger_rows(exp)
        if not unfiltered:
            meta = exp.get("ledger_meta") or {}
            unfiltered = list(meta.get("merged_server_ledger") or [])
        room_latched = str(start_val.get("latched_room_id") or "")
        token_for_filter = str(
            exp.get("token_sent")
            or rv.get("browser", {}).get("exact_expiration_token")
            or (start_val.get("authoritative_state") or {}).get("production_token")
            or ""
        ).strip()
        run_id = _infer_run_id(unfiltered, room_latched)
        app_run = str(start_val.get("application_diagnostic_run_id") or run_id or "")
        if app_run:
            run_id = app_run
        from stage1_ledger_run_filter import filter_ledger_rows_for_diagnostic_run

        filtered_meta = filter_ledger_rows_for_diagnostic_run(
            unfiltered,
            run_id=run_id,
            room_id=room_latched,
            deployment_sha=sha,
            exact_token=token_for_filter,
        )
        reject_summary = summarize_filter_rejections(filtered_meta)
        obs_sources = dict(exp.get("observability_sources") or {})
        lm = dict(exp.get("ledger_meta") or {})
        obs_loop_count = int(
            lm.get("observation_loop_ledger_row_count")
            or len(exp.get("merged_server_ledger") or [])
            or 0
        )
        report["observability_evidence"] = {
            "raw_dom_rows_before_filter": int(
                obs_sources.get("raw_dom_rows_before_filter") or lm.get("raw_dom_ledger_row_count") or 0
            ),
            "durable_store_rows_before_filter": int(
                obs_sources.get("durable_store_rows_before_filter") or lm.get("durable_ledger_row_count") or 0
            ),
            "observation_loop_rows_before_filter": obs_loop_count,
            "callback_audit_rows_before_filter": int(
                obs_sources.get("callback_audit_rows_before_filter") or lm.get("callback_audit_row_count") or 0
            ),
            "server_log_rows_found": 0,
            "total_rows_before_filter": filtered_meta.get("rows_before"),
            "total_rows_after_filter": filtered_meta.get("rows_after"),
            **reject_summary,
            "harness_run_id": run_id,
            "application_ledger_run_id": exp.get("application_ledger_run_id") or "",
            "ledger_probe_found": obs_sources.get("ledger_probe_found_any_frame"),
            "durable_store_max_rows": obs_sources.get("durable_store_max_rows"),
        }
        browser_send_ok = bool(
            (exp.get("client_stages") or [])
            or (exp.get("parent_event_sink") or {}).get("logical")
        )
        validity = observability_validity_gate(
            setup_valid=True,
            browser_send_ok=True,
            collector=collector,
            unfiltered_rows=unfiltered,
            filter_meta=filtered_meta,
        )
        report["observability_validity"] = validity
        if not validity.get("valid"):
            obs_class = classify_observability_failure(
                capture_final=pre_cap,
                filter_meta=filtered_meta,
                exp=exp,
                harness_run_id=run_id,
                app_run_id=str(exp.get("application_ledger_run_id") or ""),
            )
            report["aborted"] = True
            report["abort_reason"] = "INVALID_DIAGNOSTIC_OBSERVABILITY_EMPTY"
            report["failure_boundary"] = "OBS1 — PRODUCTION_LEDGER_NOT_CAPTURED"
            report["observability_classification"] = obs_class
            report["focused_p8_outcome"] = "INVALID_DIAGNOSTIC_OBSERVABILITY_EMPTY"
            write_checkpoint(
                OUT_FINAL,
                {
                    "observability_evidence": report["observability_evidence"],
                    "observability_classification": obs_class,
                    "filtered_meta": filtered_meta,
                    "collector_log": collector.capture_log,
                },
            )
            context.close()
            browser.close()
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            return report
        exp["filtered_ledger_rows"] = filtered_meta.get("filtered_rows") or []
        exp["ledger_filter"] = filtered_meta
        gate_rows = [
            r
            for r in exp["filtered_ledger_rows"]
            if str(r.get("event") or "") == "production_stage1_bound_token_gate"
        ]
        token_sent = str(exp.get("token_sent") or rv.get("browser", {}).get("exact_expiration_token") or "")
        pbv = build_parent_boundary_validation(exp, token_sent=token_sent)
        exp["parent_boundary_validation"] = pbv
        ladder = evaluate_p8_ladder(exp, rv, start_val=start_val)
        ladder["ledger_filter"] = filtered_meta
        ladder["contradiction_root_cause"] = classify_contradiction_root_cause(
            unfiltered_rows=unfiltered,
            filtered_meta=filtered_meta,
            python_chain=ladder.get("python_binding_chain") or {},
            gate_rows=gate_rows,
        )
        ladder["bound_token_gate_events"] = gate_rows
        ladder["bound_token_gate_score"] = score_bound_token_gate_rows(
            gate_rows, str(ladder.get("exact_token") or token_for_filter)
        )
        ladder["focused_p8_outcome"] = classify_focused_p8_outcome(
            setup_valid=True,
            setup_abort_reason="",
            python_chain=ladder.get("python_binding_chain") or {},
            gate_rows=gate_rows,
            browser_send=ladder.get("production_countdown_send") or {},
            filtered_meta=filtered_meta,
            observability_valid=bool((report.get("observability_validity") or {}).get("valid")),
        )
        try:
            from p8_binding_align_classify import replay_artifact

            bindalign = replay_artifact({**report, "p8_ladder": ladder})
            report["bindalign_replay"] = bindalign
            report["bindalign_classification"] = bindalign.get("bindalign_classification")
            rows_for_inv = (filtered_meta.get("filtered_rows") or []) if isinstance(filtered_meta, dict) else []
            try:
                from p8_binding_align_classify import build_focused_invariant_report

                report["focused_mode_invariants"] = build_focused_invariant_report(
                    rows_for_inv,
                    frozen_pick0_token=str(ladder.get("exact_token") or ""),
                    room_id=str(ladder.get("room_id") or ""),
                )
            except ImportError:
                pass
            if str(bindalign.get("bindalign_classification") or "").startswith("BINDALIGN4"):
                ladder["focused_p8_outcome"] = "BINDALIGN4 — FOCUSED MODE ALLOWED OWNERSHIP CLAIM OR PICK COMMIT"
        except ImportError:
            pass
        report["focused_p8_outcome"] = ladder["focused_p8_outcome"]
        report["ledger_integrity"] = {
            "rows_before_filtering": filtered_meta.get("rows_before"),
            "rows_retained": filtered_meta.get("rows_after"),
            "rows_rejected": filtered_meta.get("rejected_count"),
            "rejection_sample": filtered_meta.get("rejected"),
            "rejection_reasons": filtered_meta.get("rejection_reasons"),
            **report.get("observability_evidence", {}),
            "filter_run_id": filtered_meta.get("filter_run_id"),
            "filter_room_id": filtered_meta.get("filter_room_id"),
            "filter_deployment_sha": filtered_meta.get("filter_deployment_sha"),
            "merged_row_count": len(filtered_meta.get("filtered_rows") or []),
            "ledger_source_used": (exp.get("ledger_meta") or {}).get("ledger_source_used"),
            "durable_source": (exp.get("ledger_meta") or {}).get("durable_ledger_row_count"),
            "callback_audit_source": (exp.get("ledger_meta") or {}).get("callback_audit_row_count"),
        }
        write_checkpoint(
            OUT_FINAL,
            {
                "observability_evidence": report.get("observability_evidence"),
                "ledger_integrity": report["ledger_integrity"],
                "filtered_rows": filtered_meta.get("filtered_rows"),
            },
        )
        report["focused_p8_outcome"] = ladder["focused_p8_outcome"]
        baseline = load_baseline_summary()
        ladder["comparison_notes"] = compare_traces(ladder, baseline)
        py_chain = ladder.get("python_binding_chain") or {}
        report["expiration"] = {
            "token_sent": token_sent,
            "client_stages": exp.get("client_stages"),
            "callback_count": len((exp.get("audit") or {}).get("callbacks") or []),
            "pick_commits": int(py_chain.get("ledger_committed_picks") or 0),
            "commits_delta": exp.get("commits_delta"),
            "ledger_accepted_claims": int(py_chain.get("ledger_accepted_claims") or 0),
            "ledger_try_claim_calls": int(py_chain.get("ledger_try_claim_calls") or 0),
            "ledger_autopick_entries": int(py_chain.get("ledger_autopick_entries") or 0),
        }
        report["return_value_chain_summary"] = {
            "component_value_sent": rv.get("browser", {}).get("component_value_sent"),
            "LEVEL_5": (rv.get("browser", {}).get("authoritative_receipt_levels") or {}).get(
                "LEVEL_5_PYTHON_VALUE_BOUND"
            ),
        }
        report["p8_ladder"] = ladder
        report["baseline_4fa3d42"] = baseline
        report["finished_at"] = time.time()
        context.close()
        browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def focused_only_mode_enabled(argv: list[str] | None = None) -> bool:
    import sys

    args = list(argv if argv is not None else sys.argv[1:])
    if "--focused-only" in args:
        return True
    return str(os.environ.get("P8_FOCUSED_ONLY") or "").strip().lower() in ("1", "true", "yes", "on")


def main(argv: list[str] | None = None) -> int:
    os.environ.pop("REQUIRED_CLOUD_SHA", None)
    focused_only = focused_only_mode_enabled(argv)
    try:
        report = run_diagnostic()
    finally:
        try:
            from p8_focused_diagnostic_lock import release_focused_diagnostic_lock

            release_focused_diagnostic_lock()
        except ImportError:
            pass
    outcome = report.get("focused_p8_outcome") or report.get("abort_reason") or ""
    payload = report.get("p8_ladder") or report
    print(json.dumps(payload, indent=2, default=str))
    print(f"artifact={OUT}")
    print(f"focused_p8_outcome={outcome}")
    if report.get("aborted"):
        return 1
    if report.get("focused_p8_outcome") == "INVALID_DIAGNOSTIC_OBSERVABILITY_EMPTY":
        return 1
    if report.get("focused_p8_outcome") != "FOCUSED_P8_BINDING_PASS":
        return 1
    if focused_only:
        print("FOCUSED_P8_BINDING_PASS — focused-only mode; Stage 1A-CORE not chained")
        return 0
    required = report.get("required_cloud_sha") or resolve_required_sha()
    os.environ["REQUIRED_CLOUD_SHA"] = str(required)[:7]
    os.environ["STAGE1A_MODE"] = "CORE"
    print(f"FOCUSED_P8_BINDING_PASS — running exactly one Stage 1A-CORE on build {required}")
    from run_production_stage1_authenticated import main as stage1_main

    return int(stage1_main())


if __name__ == "__main__":
    raise SystemExit(main())
