"""P6 same-writer-session stale-key test — poll #solo-p6-writer-probe on authenticated LDR page."""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "solo_persistent_parity_p6_rerun.json"

from run_solo_persistent_parity_ladder_auth import (  # noqa: E402
    BASE,
    official_required_sha,
    verify_official_deploy,
)
from playwright_daniel_auth_session import (  # noqa: E402
    STORAGE_PATH,
    append_suite_sid_to_url,
    harness_ready,
)
from replay_playwright_daniel_auth_preflight import run_preflight  # noqa: E402
from solo_wiring_matrix_harness_core import (  # noqa: E402
    build_distinct_counts,
    collect_p6_browser_peak,
    collect_p6_parent_messages,
    dedupe_parent_rows_by_fingerprint,
    dual_verdicts,
    install_p6_harness_init,
    merge_browser_peak_into_repro,
    merge_peak_distinct,
    scrape_repro_events,
)


def p6_writer_url(*, run_id: str, ls_key: str) -> str:
    q = {
        "active_page": "Live Draft Room",
        "solo_delivery_diag": "1",
        "solo_persistent_parity": "P6",
        "solo_transport_probe": "1",
        "solo_p6_run_id": run_id,
        "solo_parity_ls_key": ls_key,
    }
    return append_suite_sid_to_url(f"{BASE}/?{urlencode(q)}")


def scrape_p6_writer_probe(page) -> dict[str, Any]:
    raw = page.evaluate(
        """() => {
          function roots(){const o=[document]; for (const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o.filter(Boolean);}
          for (const r of roots()) {
            const el = r.querySelector('#solo-p6-writer-probe');
            if (!el) continue;
            const b64 = el.getAttribute('data-b64')||'';
            let payload = null;
            try { payload = b64 ? JSON.parse(atob(b64)) : null; } catch(e) { payload = {err:String(e)}; }
            return {
              present: true,
              run_id: el.getAttribute('data-run-id')||'',
              expected: el.getAttribute('data-expected-token')||'',
              row_count: el.getAttribute('data-row-count')||'',
              payload,
            };
          }
          return {present:false};
        }"""
    )
    return raw if isinstance(raw, dict) else {"present": False}


def _count_stage_rows(rows: list[dict[str, Any]], *stages: str) -> int:
    allowed = set(stages)
    return sum(1 for r in rows if isinstance(r, dict) and r.get("stage") in allowed)


def _first_reject_code(rows: list[dict[str, Any]]) -> str:
    for r in reversed(rows):
        if not isinstance(r, dict):
            continue
        if r.get("stage") == "ownership_claim_rejected":
            return str(r.get("rejection_code") or r.get("reject_code") or "")
    return ""


def _ordered_ledger(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = [
        "script_begin",
        "diagnostic_entrypoint_entered",
        "initial_widget_state",
        "widget_state_before_clear",
        "widget_state_after_clear",
        "production_token_latched",
        "component_declaration_attempted",
        "component_declared",
        "callback_entry",
        "on_change_callback_entry",
        "raw_widget_value",
        "ownership_attempted",
        "ownership_claim_attempted",
        "ownership_claim_accepted",
        "ownership_claim_rejected",
        "callback_return",
        "pick_processing_skipped",
        "post_delivery_script_run",
    ]
    rank = {s: i for i, s in enumerate(order)}
    filtered = [r for r in rows if isinstance(r, dict) and r.get("stage") in rank]
    return sorted(filtered, key=lambda r: (rank.get(str(r.get("stage")), 99), float(r.get("ts") or 0)))


def python_receipt_from_ledger(payload: dict[str, Any]) -> bool:
    from live_draft_solo_parity_p6_persistent_diag import python_receipt_from_payload

    return python_receipt_from_payload(payload)


def compute_pre_send_from_ledger(payload: dict[str, Any], *, browser_send_ts: float | None) -> bool:
    stale = payload.get("stale_state") if isinstance(payload.get("stale_state"), dict) else {}
    if stale.get("initial_equals_expected"):
        return True
    rows = payload.get("ledger_rows") if isinstance(payload.get("ledger_rows"), list) else []
    expected = str(payload.get("expected_token") or "")
    if not expected:
        return False
    for r in rows:
        if not isinstance(r, dict):
            continue
        stage = str(r.get("stage") or "")
        if stage in ("production_token_latched", "component_declared"):
            ts = float(r.get("ts") or 0)
            if browser_send_ts and ts < browser_send_ts - 0.05:
                act = str(r.get("actual_token") or "")
                if act == expected or expected in act:
                    return True
        if stage == "widget_state_before_clear":
            act = str(r.get("actual_token") or "").strip("'\"")
            if act == expected:
                return True
    widget_raw = str(payload.get("current_widget_raw") or "").strip("'\"")
    if browser_send_ts and widget_raw == expected:
        return True
    return False


def _collect_streamlit_session_ids(payload: dict[str, Any], rows: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    sid = str(payload.get("streamlit_session_id") or "").strip()
    if sid:
        ids.add(sid)
    for r in rows:
        if isinstance(r, dict):
            s = str(r.get("streamlit_session_id") or "").strip()
            if s:
                ids.add(s)
    return ids


def _session_replaced_invalid(
    *,
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    run_id: str,
    had_mount_rows: bool,
) -> bool:
    ids = _collect_streamlit_session_ids(payload, rows)
    if len(ids) <= 1:
        return False
    if not had_mount_rows:
        return False
    cb = _has_stage(rows, "on_change_callback_entry") or _has_stage(rows, "callback_entry")
    if cb:
        return False
    return True


def _pre_expiration_mount_stages_ok(rows: list[dict[str, Any]]) -> bool:
    required = (
        "script_begin",
        "diagnostic_entrypoint_entered",
        "initial_widget_state",
        "widget_state_before_clear",
        "widget_state_after_clear",
        "production_token_latched",
        "component_declaration_attempted",
        "component_declared",
    )
    return all(_has_stage(rows, s) for s in required)


def _score_p6_entrypoint_gate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not _has_stage(rows, "diagnostic_entrypoint_entered"):
        return {
            "overall": "INVALID_P6_ENTRYPOINT_SKIPPED",
            "transport_verdict": "INVALID_P6_ENTRYPOINT_SKIPPED",
            "lifecycle_verdict": "INVALID",
            "lifecycle_detail": {"reason": "diagnostic_entrypoint_entered missing"},
            "python_receipt": False,
            "production_callback_entries": 0,
            "ownership_attempt_rows": 0,
            "ownership_claim_rows": 0,
            "processing_verdict": "UNKNOWN",
            "reject_code": "",
            "mount_path_note": "Do not grade transport",
        }
    if not _has_stage(rows, "component_declared"):
        return {
            "overall": "INVALID_P6_COMPONENT_NOT_DECLARED",
            "transport_verdict": "INVALID_P6_COMPONENT_NOT_DECLARED",
            "lifecycle_verdict": "INVALID",
            "lifecycle_detail": {"reason": "entrypoint ran but component_declared missing"},
            "python_receipt": False,
            "production_callback_entries": _count_stage_rows(rows, "callback_entry", "on_change_callback_entry"),
            "ownership_attempt_rows": 0,
            "ownership_claim_rows": 0,
            "processing_verdict": "UNKNOWN",
            "reject_code": "",
            "mount_path_note": "Do not grade transport",
        }
    return None


def _post_expiration_rows_present(rows: list[dict[str, Any]]) -> dict[str, bool]:
    return {
        "on_change_callback_entry": _has_stage(rows, "on_change_callback_entry", "callback_entry"),
        "raw_widget_value": _has_stage(rows, "raw_widget_value"),
        "ownership_claim_attempted": _has_stage(rows, "ownership_claim_attempted", "ownership_attempted"),
        "ownership_outcome": _has_stage(
            rows, "ownership_claim_accepted", "ownership_claim_rejected"
        ),
        "rejection_code": any(
            isinstance(r, dict) and r.get("rejection_code") or r.get("reject_code")
            for r in rows
            if isinstance(r, dict) and r.get("stage") in ("ownership_claim_rejected", "ownership_claim_accepted")
        ),
        "callback_return": _has_stage(rows, "callback_return"),
        "pick_processing_skipped": _has_stage(rows, "pick_processing_skipped"),
        "post_delivery_script_run": _has_stage(rows, "post_delivery_script_run"),
    }


def _has_stage(rows: list[dict[str, Any]], *stages: str) -> bool:
    allowed = set(stages)
    return any(isinstance(r, dict) and r.get("stage") in allowed for r in rows)


def build_browser_unique_event_table(*, peak: dict[str, Any], browser_peak: dict[str, Any]) -> dict[str, Any]:
    sc = dict(peak.get("stage_counts") or browser_peak.get("stage_counts") or {})
    lifecycle = peak.get("lifecycle") if isinstance(peak.get("lifecycle"), dict) else {}
    return {
        "production_iframe_instances": int(
            peak.get("unique_iframe_instances") or browser_peak.get("unique_iframe_instances") or 0
        ),
        "unique_timer_armed": int(sc.get("timer_armed") or 0),
        "unique_deadline_crossed": int(sc.get("browser_deadline_crossed") or 0),
        "unique_setComponentValue": int(sc.get("setComponentValue_invoked") or 0),
        "unique_transport_postMessage": int(sc.get("transport_postmessage_invoked") or 0),
        "deduped_parent_receipt": int(peak.get("parent_message") or 0),
        "iframe_remounts_lifecycle_warning": int(sc.get("iframe_remount") or lifecycle.get("iframe_remount_count") or 0),
        "tick_cancelled_lifecycle_warning": int(sc.get("tick_cancelled") or lifecycle.get("tick_cancelled_count") or 0),
    }


def _filter_run_matched_parent_rows(
    rows: list[dict[str, Any]], *, run_id: str, expected_token: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pr in rows:
        if not isinstance(pr, dict):
            continue
        pr_run = str(pr.get("solo_p6_run_id") or "").strip()
        if pr_run and pr_run != run_id:
            continue
        val = str(pr.get("value_preview") or "")
        if expected_token and val != expected_token:
            continue
        if expected_token and pr_run and pr_run != run_id:
            continue
        out.append(pr)
    return out


def _declare_session_ids(rows: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for r in rows:
        if isinstance(r, dict) and r.get("stage") == "component_declared":
            s = str(r.get("streamlit_session_id") or "").strip()
            if s:
                ids.add(s)
    return ids


def score_p6_from_evidence(
    *,
    peak: dict[str, Any],
    payload: dict[str, Any],
    expected_token: str,
    writer_present: bool,
    browser_send_ts: float | None,
    run_id: str = "",
    session_ids: set[str] | None = None,
    mount_invalid_timer: bool = False,
) -> dict[str, Any]:
    rows = payload.get("ledger_rows") if isinstance(payload.get("ledger_rows"), list) else []
    gate = _score_p6_entrypoint_gate(rows)
    if gate is not None:
        gate.update(
            {
                "pick_processing_disabled": bool(payload.get("pick_processing_disabled")),
                "pre_send_session_token": False,
                "stale_state_finding": payload.get("stale_state") if isinstance(payload.get("stale_state"), dict) else {},
                "pre_expiration_mount_complete": _pre_expiration_mount_stages_ok(rows),
                "post_expiration_rows": _post_expiration_rows_present(rows),
                "streamlit_session_ids": sorted(session_ids or []),
                "streamlit_session_changed": len(session_ids or set()) > 1,
            }
        )
        return gate
    had_mount = _has_stage(rows, "component_declaration_attempted") or _has_stage(rows, "component_declared")
    if mount_invalid_timer and not _has_stage(rows, "component_declared"):
        return {
            "overall": "INVALID_P6_MOUNT_PATH_SKIPPED",
            "transport_verdict": "INVALID_P6_MOUNT_PATH_SKIPPED",
            "lifecycle_verdict": "INVALID",
            "lifecycle_detail": {"reason": "timer_armed_before_component_declared"},
            "python_receipt": False,
            "production_callback_entries": 0,
            "ownership_attempt_rows": 0,
            "ownership_claim_rows": 0,
            "processing_verdict": "UNKNOWN",
            "reject_code": "",
            "pick_processing_disabled": bool(payload.get("pick_processing_disabled")),
            "pre_send_session_token": False,
            "stale_state_finding": {},
            "mount_path_note": "timer_armed before component_declared",
            "pre_expiration_mount_complete": _pre_expiration_mount_stages_ok(rows),
            "post_expiration_rows": _post_expiration_rows_present(rows),
            "streamlit_session_ids": sorted(session_ids or []),
            "streamlit_session_changed": len(session_ids or set()) > 1,
        }
    if _session_replaced_invalid(payload=payload, rows=rows, run_id=run_id, had_mount_rows=had_mount):
        return {
            "overall": "INVALID_P6_SESSION_REPLACED",
            "transport_verdict": "INVALID_P6_SESSION_REPLACED",
            "lifecycle_verdict": "INVALID",
            "lifecycle_detail": {"reason": "streamlit_session_id_changed_mount_lost"},
            "python_receipt": False,
            "production_callback_entries": _count_stage_rows(rows, "callback_entry", "on_change_callback_entry"),
            "ownership_attempt_rows": _count_stage_rows(rows, "ownership_attempted", "ownership_claim_attempted"),
            "ownership_claim_rows": _count_stage_rows(
                rows, "ownership_claim_accepted", "ownership_claim_rejected"
            ),
            "processing_verdict": "UNKNOWN",
            "reject_code": "",
            "pick_processing_disabled": bool(payload.get("pick_processing_disabled")),
            "pre_send_session_token": False,
            "stale_state_finding": payload.get("stale_state") if isinstance(payload.get("stale_state"), dict) else {},
            "mount_path_note": "Do not grade as callback failure — session replaced",
            "pre_expiration_mount_complete": _pre_expiration_mount_stages_ok(rows),
            "post_expiration_rows": _post_expiration_rows_present(rows),
            "streamlit_session_ids": sorted(session_ids or []),
            "streamlit_session_changed": True,
        }
    if not _has_stage(rows, "component_declared"):
        gate2 = _score_p6_entrypoint_gate(rows)
        if gate2 is not None:
            gate2.update(
                {
                    "pick_processing_disabled": bool(payload.get("pick_processing_disabled")),
                    "pre_send_session_token": compute_pre_send_from_ledger(payload, browser_send_ts=browser_send_ts),
                    "stale_state_finding": payload.get("stale_state") if isinstance(payload.get("stale_state"), dict) else {},
                    "pre_expiration_mount_complete": _pre_expiration_mount_stages_ok(rows),
                    "post_expiration_rows": _post_expiration_rows_present(rows),
                    "streamlit_session_ids": sorted(session_ids or []),
                    "streamlit_session_changed": len(session_ids or set()) > 1,
                }
            )
            return gate2
        return {
            "overall": "INVALID_P6_COMPONENT_NOT_DECLARED",
            "transport_verdict": "INVALID_P6_COMPONENT_NOT_DECLARED",
            "lifecycle_verdict": peak.get("lifecycle_verdict") if isinstance(peak.get("lifecycle_verdict"), str) else "UNKNOWN",
            "lifecycle_detail": peak.get("lifecycle_detail") or {},
            "python_receipt": False,
            "production_callback_entries": _count_stage_rows(rows, "callback_entry", "on_change_callback_entry"),
            "ownership_attempt_rows": _count_stage_rows(rows, "ownership_attempted", "ownership_claim_attempted"),
            "ownership_claim_rows": _count_stage_rows(
                rows, "ownership_claim_accepted", "ownership_claim_rejected"
            ),
            "processing_verdict": "UNKNOWN",
            "reject_code": "",
            "pick_processing_disabled": bool(payload.get("pick_processing_disabled")),
            "pre_send_session_token": compute_pre_send_from_ledger(payload, browser_send_ts=browser_send_ts),
            "stale_state_finding": payload.get("stale_state") if isinstance(payload.get("stale_state"), dict) else {},
            "mount_path_note": "component_declared missing before transport/callback grading",
            "pre_expiration_mount_complete": _pre_expiration_mount_stages_ok(rows),
            "post_expiration_rows": _post_expiration_rows_present(rows),
            "streamlit_session_ids": sorted(session_ids or []),
            "streamlit_session_changed": len(session_ids or set()) > 1,
        }
    cb_entries = _count_stage_rows(rows, "callback_entry", "on_change_callback_entry")
    owner_attempts = _count_stage_rows(rows, "ownership_attempted", "ownership_claim_attempted")
    owner_claims = _count_stage_rows(rows, "ownership_claim_accepted", "ownership_claim_rejected")
    python_receipt = python_receipt_from_ledger(payload)
    pre_send = compute_pre_send_from_ledger(payload, browser_send_ts=browser_send_ts)
    peak2 = dict(peak)
    peak2["pre_send_session_token"] = pre_send
    if python_receipt:
        peak2["python_raw_receipt"] = 1
    if cb_entries >= 1:
        peak2["on_change_callback"] = cb_entries
    reject = _first_reject_code(rows)
    accepted = any(isinstance(r, dict) and r.get("stage") == "ownership_claim_accepted" for r in rows)
    pick_disabled = bool(payload.get("pick_processing_disabled"))
    decl_sids = _declare_session_ids(rows)
    session_changed = len(session_ids or set()) > 1
    session_changed_after_decl = bool(decl_sids and session_ids and not session_ids.issubset(decl_sids))
    if session_changed_after_decl and cb_entries < 1:
        return {
            "overall": "INVALID_P6_SESSION_REPLACED",
            "transport_verdict": "INVALID_P6_SESSION_REPLACED",
            "lifecycle_verdict": "INVALID",
            "lifecycle_detail": {"reason": "streamlit_session_changed_after_component_declared"},
            "python_receipt": python_receipt,
            "production_callback_entries": cb_entries,
            "ownership_attempt_rows": owner_attempts,
            "ownership_claim_rows": owner_claims,
            "processing_verdict": "UNKNOWN",
            "reject_code": reject,
            "pick_processing_disabled": pick_disabled,
            "pre_send_session_token": pre_send,
            "stale_state_finding": payload.get("stale_state") if isinstance(payload.get("stale_state"), dict) else {},
            "pre_expiration_mount_complete": _pre_expiration_mount_stages_ok(rows),
            "post_expiration_rows": _post_expiration_rows_present(rows),
            "streamlit_session_ids": sorted(session_ids or []),
            "streamlit_session_changed": True,
            "declare_session_ids": sorted(decl_sids),
        }
    browser_table = build_browser_unique_event_table(peak=peak2, browser_peak={})
    browser_ok = (
        browser_table["production_iframe_instances"] == 1
        and browser_table["unique_timer_armed"] == 1
        and browser_table["unique_deadline_crossed"] == 1
        and browser_table["unique_setComponentValue"] == 1
        and browser_table["unique_transport_postMessage"] == 1
        and browser_table["deduped_parent_receipt"] == 1
        and not pre_send
    )
    transport_pass = (
        browser_ok
        and python_receipt
        and cb_entries == 1
        and accepted
        and owner_attempts >= 1
        and _pre_expiration_mount_stages_ok(rows)
        and bool(payload.get("clear_once_applied"))
        and not session_changed
    )
    if transport_pass:
        overall = "PASS"
        transport_verdict = "PASS"
        processing_verdict = "ACCEPTED_PICK_DISABLED" if pick_disabled else "ACCEPTED"
    elif (
        _pre_expiration_mount_stages_ok(rows)
        and browser_table["deduped_parent_receipt"] >= 1
        and not session_changed_after_decl
        and cb_entries < 1
    ):
        overall = "VALID_FAIL_CALLBACK_REGISTRATION"
        transport_verdict = "VALID_FAIL_CALLBACK_REGISTRATION"
        processing_verdict = "UNKNOWN"
    elif cb_entries >= 1 and reject:
        overall = f"VALID_FAIL_REJECTED_{reject}"
        transport_verdict = "VALID_FAIL"
        processing_verdict = f"REJECTED_{reject}"
    elif cb_entries >= 1 and not accepted and owner_attempts >= 1:
        overall = "VALID_FAIL_REJECTED_UNKNOWN"
        transport_verdict = "VALID_FAIL"
        processing_verdict = "UNKNOWN"
    else:
        overall = "VALID_FAIL"
        transport_verdict = "VALID_FAIL"
        processing_verdict = "UNKNOWN"
    stale = payload.get("stale_state") if isinstance(payload.get("stale_state"), dict) else {}
    return {
        "overall": overall,
        "transport_verdict": transport_verdict,
        "lifecycle_verdict": peak2.get("lifecycle_verdict") if isinstance(peak2.get("lifecycle_verdict"), str) else "UNKNOWN",
        "lifecycle_detail": peak2.get("lifecycle_detail") if isinstance(peak2.get("lifecycle_detail"), dict) else {},
        "python_receipt": python_receipt,
        "production_callback_entries": cb_entries,
        "ownership_attempt_rows": owner_attempts,
        "ownership_claim_rows": owner_claims,
        "processing_verdict": processing_verdict,
        "reject_code": reject,
        "pick_processing_disabled": pick_disabled,
        "pre_send_session_token": pre_send,
        "stale_state_finding": stale,
        "pre_expiration_mount_complete": _pre_expiration_mount_stages_ok(rows),
        "post_expiration_rows": _post_expiration_rows_present(rows),
        "streamlit_session_ids": sorted(session_ids or []),
        "streamlit_session_changed": session_changed,
        "declare_session_ids": sorted(decl_sids),
        "browser_unique_events": browser_table,
    }


def interpret_p6_scored(scored: dict[str, Any], *, peak: dict[str, Any]) -> str:
    overall = str(scored.get("overall") or "")
    if overall == "INVALID_P6_SESSION_REPLACED":
        return (
            "Streamlit session changed between declaration and expiration; "
            "same-session ledger lost — not a callback registration failure."
        )
    if overall == "INVALID_P6_ENTRYPOINT_SKIPPED":
        return "Dedicated P6 entrypoint did not execute; do not grade transport."
    if overall == "INVALID_P6_COMPONENT_NOT_DECLARED":
        return "Entrypoint ran but production try_solo_persistent_wake_ldr_entry did not record component_declared."
    if overall == "INVALID_P6_MOUNT_PATH_SKIPPED":
        return "P6 diagnostic routing still invalid; do not conclude production transport from this run."
    if overall == "PASS":
        return (
            "Full persistent-wake transport proven (mount ledger, single browser send, callback, ownership). "
            "Stop diagnostic work; proceed to one real authenticated Stage 1A with pick processing enabled."
        )
    mount_ok = bool(scored.get("pre_expiration_mount_complete"))
    cb = int(scored.get("production_callback_entries") or 0)
    parent = int(peak.get("parent_message") or 0)
    if overall == "VALID_FAIL_CALLBACK_REGISTRATION":
        return (
            "Mount ledger and run-matched parent delivery in same session, but no Python callback — "
            "callback registration on the exact persistent declaration is the remaining boundary."
        )
    if overall.startswith("VALID_FAIL_REJECTED_"):
        return f"Callback entered; ownership/validation rejected ({overall})."
    if mount_ok and cb >= 1:
        return "Mount and callback observed; transport/processing did not meet full PASS criteria — review post-expiration rows."
    return "Review ordered ledger, browser peak, and session continuity fields."


def _parity_expire_token(value: str) -> bool:
    s = str(value or "").strip()
    return s.startswith("PARITY|") or (s.startswith("PARITY_") and "|" in s)


def run_p6_writer_session(browser, *, deploy: dict[str, Any], run_id: str) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake

    ls_key = f"solo_parity_ls_p6_{int(time.time())}"
    writer_url = p6_writer_url(run_id=run_id, ls_key=ls_key)
    syn_prefix = f"PARITY_{run_id.replace('-', '')[:8]}|"
    ctx = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
    install_p6_harness_init(ctx)
    page = ctx.new_page()
    try:
        goto_and_wake(page, writer_url, timeout_s=240)
        t0 = time.time()
        peak: dict[str, Any] = {}
        expected = ""
        first_capture: dict[str, Any] | None = None
        last_payload: dict[str, Any] = {}
        writer_samples: list[dict[str, Any]] = []
        browser_send_ts: float | None = None
        session_ids_seen: set[str] = set()
        mount_invalid_timer = False
        deadline = time.time() + 46.0

        while time.time() - t0 < 42.0:
            probe = scrape_p6_writer_probe(page)
            payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
            probe_run = str(probe.get("run_id") or payload.get("solo_p6_run_id") or "")
            if probe_run and probe_run != run_id:
                payload = {}
            elif payload:
                last_payload = payload
            browser_peak = collect_p6_browser_peak(page)
            repro = merge_browser_peak_into_repro(scrape_repro_events(page), browser_peak)
            parent_all = _filter_run_matched_parent_rows(
                collect_p6_parent_messages(page), run_id=run_id, expected_token=expected
            )
            exp = str(probe.get("expected") or payload.get("expected_token") or expected or "")
            if _parity_expire_token(exp):
                expected = exp
            elif not expected:
                for pr in parent_all:
                    prev = str(pr.get("value_preview") or "")
                    if prev.startswith(syn_prefix) or _parity_expire_token(prev):
                        expected = prev
                        break
            if expected.count("|") >= 2:
                try:
                    deadline = float(expected.split("|")[-1])
                except ValueError:
                    pass
            parent_rows = _filter_run_matched_parent_rows(parent_all, run_id=run_id, expected_token=expected)
            parent_rows = dedupe_parent_rows_by_fingerprint(parent_rows, expected_token=expected)
            sc = repro.get("stage_counts") if isinstance(repro.get("stage_counts"), dict) else {}
            rows = payload.get("ledger_rows") if isinstance(payload.get("ledger_rows"), list) else []
            mount_complete = _has_stage(rows, "component_declared") and _has_stage(
                rows, "diagnostic_entrypoint_entered"
            )
            sid = str(payload.get("streamlit_session_id") or "").strip()
            if sid:
                session_ids_seen.add(sid)
            for r in rows:
                if isinstance(r, dict):
                    rs = str(r.get("streamlit_session_id") or "").strip()
                    if rs:
                        session_ids_seen.add(rs)
            if (
                expected
                and bool(probe.get("present"))
                and _has_stage(rows, "script_begin")
                and int(sc.get("timer_armed") or 0) >= 1
                and not _has_stage(rows, "component_declared")
            ):
                mount_invalid_timer = True
                break

            writer_samples.append(
                {
                    "elapsed_s": round(time.time() - t0, 1),
                    "writer_present": probe.get("present"),
                    "row_count": probe.get("row_count"),
                    "ledger_rows": len(payload.get("ledger_rows") or []) if payload else 0,
                }
            )
            cb_stages = {"callback_entry", "on_change_callback_entry"}
            if first_capture is None and any(
                isinstance(r, dict) and r.get("stage") in cb_stages for r in (payload.get("ledger_rows") or [])
            ):
                first_capture = {"probe": probe, "payload": payload, "elapsed_s": round(time.time() - t0, 1)}

            widget_raw = str(payload.get("current_widget_raw") or payload.get("raw_session_state_value") or "").strip(
                "'\""
            )
            if mount_complete:
                distinct = build_distinct_counts(
                    repro=repro,
                    parent_rows=parent_rows,
                    expected_token=expected,
                    session_raw=widget_raw,
                    callback_log=[
                        r
                        for r in (payload.get("ledger_rows") or [])
                        if isinstance(r, dict) and r.get("stage") in cb_stages
                    ],
                    browser_send_ts=browser_send_ts,
                )
                distinct["pre_send_session_token"] = compute_pre_send_from_ledger(
                    payload, browser_send_ts=browser_send_ts
                )
                peak = merge_peak_distinct(peak, distinct)
                if browser_send_ts is None and int(sc.get("transport_postmessage_invoked") or 0) >= 1:
                    browser_send_ts = time.time()
            if mount_complete and time.time() >= deadline + 8 and int(peak.get("browser_deadline_crossed") or 0) >= 1:
                break
            page.wait_for_timeout(400)

        writer_final = scrape_p6_writer_probe(page)
        if isinstance(writer_final.get("payload"), dict):
            last_payload = writer_final["payload"]
        scored = score_p6_from_evidence(
            peak=peak,
            payload=last_payload,
            expected_token=expected,
            writer_present=bool(writer_final.get("present")),
            browser_send_ts=browser_send_ts,
            run_id=run_id,
            session_ids=session_ids_seen,
            mount_invalid_timer=mount_invalid_timer,
        )
        rows = last_payload.get("ledger_rows") if isinstance(last_payload.get("ledger_rows"), list) else []
        browser_unique = build_browser_unique_event_table(peak=peak, browser_peak=collect_p6_browser_peak(page))
        marker_sha = official_required_sha()
        return {
            "deploy": deploy,
            "implementation_sha": deploy.get("cloud_sha"),
            "deploy_marker_sha": marker_sha,
            "cloud_build": deploy.get("cloud_build"),
            "run_id": run_id,
            "writer_url": writer_url,
            "mode": "p6_dedicated_entrypoint",
            "peak": peak,
            "expected_token": expected,
            "synthetic_room_id": f"PARITY_{run_id.replace('-', '')[:8]}",
            "first_capture": first_capture,
            "last_payload": last_payload,
            "ordered_ledger": _ordered_ledger(rows),
            "browser_unique_events": browser_unique,
            "writer_samples": writer_samples[-40:],
            "parent_rows_deduped": dedupe_parent_rows_by_fingerprint(
                _filter_run_matched_parent_rows(
                    collect_p6_parent_messages(page), run_id=run_id, expected_token=expected
                ),
                expected_token=expected,
            ),
            "scored": scored,
            "interpretation": interpret_p6_scored(scored, peak=peak),
            "mount_invalid_timer": mount_invalid_timer,
            "streamlit_session_ids": sorted(session_ids_seen),
            "session_continuity": {
                "streamlit_session_ids": sorted(session_ids_seen),
                "changed": len(session_ids_seen) > 1,
                "declare_session_ids": scored.get("declare_session_ids") if isinstance(scored, dict) else [],
            },
            "artifact_path": str(OUT),
            "observation_s": round(time.time() - t0, 1),
        }
    finally:
        ctx.close()


def main() -> int:
    if not harness_ready():
        print(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}))
        return 1
    if not run_preflight().get("authenticated_restored"):
        print(json.dumps({"aborted": True, "reason": "auth_preflight_failed"}))
        return 1

    required = official_required_sha()
    run_id = str(uuid.uuid4())
    from playwright.sync_api import sync_playwright

    report: dict[str, Any] = {
        "control": "P6",
        "required_sha": required,
        "run_id": run_id,
        "classification_note": "Same writer session; do not infer Python receipt from parent postMessage alone.",
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        deploy_page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        deploy = verify_official_deploy(deploy_page, required=required)
        report["deploy_probe"] = deploy
        deploy_page.context.close()
        if not deploy.get("deploy_ok"):
            report["outcome"] = "ABORTED"
            report["reason"] = "cloud_deploy_mismatch"
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(json.dumps(report, indent=2, default=str))
            browser.close()
            return 1

        run = run_p6_writer_session(browser, deploy=deploy, run_id=run_id)
        report.update(run)
        report["cloud_sha"] = deploy.get("cloud_sha")
        report["outcome"] = run.get("scored", {}).get("overall")
        report["transport_verdict"] = run.get("scored", {}).get("transport_verdict")
        report["processing_verdict"] = run.get("scored", {}).get("processing_verdict")
        report["stale_state_finding"] = run.get("scored", {}).get("stale_state_finding")
        browser.close()

    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
