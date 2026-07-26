"""Rerun production-parity control P6 only — dual-page observer + deduped parent capture."""

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
PRIOR_RUN_CLASSIFICATION = "INCONCLUSIVE_DIAGNOSTIC_OBSERVER_FAILURE"

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


def p6_observer_url(*, run_id: str) -> str:
    q = {"solo_p6_diag_observer": "1", "solo_p6_run_id": run_id}
    return f"{BASE}/?{urlencode(q)}"


def scrape_p6_observer_payload(page) -> dict[str, Any]:
    raw = page.evaluate(
        """() => {
          function roots(){const o=[document]; for (const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o.filter(Boolean);}
          for (const r of roots()) {
            const el = r.querySelector('#solo-p6-diag-observer');
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


def _count_stage_rows(rows: list[dict[str, Any]], stage: str) -> int:
    return sum(1 for r in rows if isinstance(r, dict) and r.get("stage") == stage)


def _first_reject_code(rows: list[dict[str, Any]]) -> str:
    for r in reversed(rows):
        if isinstance(r, dict) and r.get("stage") == "ownership_claim_rejected":
            return str(r.get("reject_code") or "")
    return ""


def python_receipt_from_ledger(payload: dict[str, Any]) -> bool:
    from live_draft_solo_parity_p6_persistent_diag import python_receipt_from_payload

    return python_receipt_from_payload(payload)


def snapshot_meets_capture_criteria(payload: dict[str, Any]) -> bool:
    from live_draft_solo_parity_p6_persistent_diag import first_nonempty_p6_snapshot_criteria

    return first_nonempty_p6_snapshot_criteria(payload)


def score_p6_from_evidence(
    *,
    peak: dict[str, Any],
    payload: dict[str, Any],
    expected_token: str,
    observer_present: bool,
) -> dict[str, Any]:
    rows = payload.get("ledger_rows") if isinstance(payload.get("ledger_rows"), list) else []
    cb_entries = _count_stage_rows(rows, "on_change_callback_entry")
    owner_attempts = _count_stage_rows(rows, "ownership_claim_attempted")
    owner_claims = sum(
        1
        for r in rows
        if isinstance(r, dict)
        and str(r.get("stage") or "") in ("ownership_claim_accepted", "ownership_claim_rejected")
    )
    python_receipt = python_receipt_from_ledger(payload)
    peak2 = dict(peak)
    if python_receipt:
        peak2["python_raw_receipt"] = 1
        raw = str(payload.get("raw_session_state_value") or "").strip("'\"")
        peak2["session_raw_matches"] = bool(expected_token and expected_token in raw)
    if cb_entries >= 1:
        peak2["on_change_callback"] = cb_entries
    transport = dual_verdicts(peak2, cell="B2", expected_token=expected_token)
    browser_ok = (
        int(peak2.get("logical_send_postmessage") or 0) >= 1
        and int(peak2.get("parent_message") or 0) >= 1
        and not peak2.get("pre_send_session_token")
    )
    transport_pass = (
        browser_ok
        and python_receipt
        and cb_entries == 1
        and owner_attempts >= 1
        and owner_claims >= 1
        and int(peak2.get("setComponentValue_invocation") or 0) == 1
        and int(peak2.get("logical_send_postmessage") or 0) == 1
        and int(peak2.get("parent_message") or 0) == 1
        and transport.get("transport_verdict") != "INVALID"
    )
    reject = _first_reject_code(rows)
    accepted = any(isinstance(r, dict) and r.get("stage") == "ownership_claim_accepted" for r in rows)
    pick_disabled = bool(payload.get("pick_processing_disabled"))
    if reject:
        processing_verdict = f"REJECTED_{reject}"
    elif accepted and pick_disabled:
        processing_verdict = "ACCEPTED_PICK_DISABLED"
    elif accepted:
        processing_verdict = "ACCEPTED"
    else:
        processing_verdict = "UNKNOWN"
    if not observer_present:
        overall = "INCONCLUSIVE_DIAGNOSTIC_OBSERVER_FAILURE"
    elif not payload.get("expected_token") and not expected_token:
        overall = "INCONCLUSIVE_DIAGNOSTIC_PROBE_MISSING"
    elif not python_receipt and browser_ok:
        overall = "INCONCLUSIVE_DIAGNOSTIC_PROBE_MISSING"
    elif transport_pass:
        overall = "PASS"
    elif transport.get("transport_verdict") == "INVALID":
        overall = "INVALID"
    else:
        overall = "VALID_FAIL"
    return {
        "overall": overall,
        "transport_verdict": "PASS" if transport_pass else transport.get("transport_verdict"),
        "lifecycle_verdict": transport.get("lifecycle_verdict"),
        "lifecycle_detail": transport.get("lifecycle_detail"),
        "python_receipt": python_receipt,
        "production_callback_entries": cb_entries,
        "ownership_attempt_rows": owner_attempts,
        "ownership_claim_rows": owner_claims,
        "processing_verdict": processing_verdict,
        "reject_code": reject,
        "pick_processing_disabled": pick_disabled,
    }


def run_p6_dual_page(browser, *, deploy: dict[str, Any], run_id: str) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake

    ls_key = f"solo_parity_ls_p6_{int(time.time())}"
    writer_url = p6_writer_url(run_id=run_id, ls_key=ls_key)
    observer_url = p6_observer_url(run_id=run_id)

    ctx_writer = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
    ctx_observer = browser.new_context(viewport={"width": 900, "height": 700})
    install_p6_harness_init(ctx_writer)
    install_p6_harness_init(ctx_observer)

    page_writer = ctx_writer.new_page()
    page_observer = ctx_observer.new_page()
    try:
        goto_and_wake(page_observer, observer_url, timeout_s=120)
        page_observer.wait_for_timeout(1500)
        goto_and_wake(page_writer, writer_url, timeout_s=240)

        t0 = time.time()
        peak: dict[str, Any] = {}
        expected = ""
        first_capture: dict[str, Any] | None = None
        last_payload: dict[str, Any] = {}
        observer_samples: list[dict[str, Any]] = []
        browser_send_ts: float | None = None
        deadline = time.time() + 46.0

        while time.time() - t0 < 40.0:
            probe = scrape_p6_observer_payload(page_observer)
            payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
            if payload:
                last_payload = payload
            browser_peak = collect_p6_browser_peak(page_writer)
            repro = merge_browser_peak_into_repro(scrape_repro_events(page_writer), browser_peak)
            parent_all = collect_p6_parent_messages(page_writer)
            parent_rows = dedupe_parent_rows_by_fingerprint(parent_all, expected_token=expected)
            exp = str(probe.get("expected") or payload.get("expected_token") or expected or "")
            if exp.startswith("PARITY|"):
                expected = exp
            elif not expected:
                for pr in parent_rows:
                    prev = str(pr.get("value_preview") or "")
                    if prev.startswith("PARITY|"):
                        expected = prev
                        break
            if expected.count("|") >= 2:
                try:
                    deadline = float(expected.split("|")[-1])
                except ValueError:
                    pass
            parent_rows = dedupe_parent_rows_by_fingerprint(parent_all, expected_token=expected)
            sc = repro.get("stage_counts") if isinstance(repro.get("stage_counts"), dict) else {}
            if browser_send_ts is None and int(sc.get("transport_postmessage_invoked") or 0) >= 1:
                browser_send_ts = time.time()

            observer_samples.append(
                {
                    "elapsed_s": round(time.time() - t0, 1),
                    "observer_present": probe.get("present"),
                    "row_count": probe.get("row_count"),
                    "ledger_rows": len(payload.get("ledger_rows") or []) if payload else 0,
                }
            )
            if first_capture is None and snapshot_meets_capture_criteria(payload):
                first_capture = {"probe": probe, "payload": payload, "elapsed_s": round(time.time() - t0, 1)}

            raw_widget = str(payload.get("raw_session_state_value") or "").strip("'\"")
            distinct = build_distinct_counts(
                repro=repro,
                parent_rows=parent_rows,
                expected_token=expected,
                session_raw=raw_widget,
                callback_log=[
                    r
                    for r in (payload.get("ledger_rows") or [])
                    if isinstance(r, dict) and r.get("stage") == "on_change_callback_entry"
                ],
                browser_send_ts=browser_send_ts,
            )
            peak = merge_peak_distinct(peak, distinct)
            if time.time() >= deadline + 8 and int(peak.get("browser_deadline_crossed") or 0) >= 1:
                break
            page_observer.wait_for_timeout(350)
            page_writer.wait_for_timeout(50)

        observer_final = scrape_p6_observer_payload(page_observer)
        if isinstance(observer_final.get("payload"), dict):
            last_payload = observer_final["payload"]
        scored = score_p6_from_evidence(
            peak=peak,
            payload=last_payload,
            expected_token=expected,
            observer_present=bool(observer_final.get("present")),
        )
        parent_deduped = dedupe_parent_rows_by_fingerprint(
            collect_p6_parent_messages(page_writer), expected_token=expected
        )
        return {
            "deploy": deploy,
            "run_id": run_id,
            "writer_url": writer_url,
            "observer_url": observer_url,
            "peak": peak,
            "expected_token": expected,
            "first_capture": first_capture,
            "last_payload": last_payload,
            "observer_samples": observer_samples[-40:],
            "parent_rows_deduped": parent_deduped,
            "parent_rows_raw_count": len(collect_p6_parent_messages(page_writer)),
            "scored": scored,
            "observation_s": round(time.time() - t0, 1),
        }
    finally:
        ctx_writer.close()
        ctx_observer.close()


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
        "prior_run_classification": PRIOR_RUN_CLASSIFICATION,
        "classification_note": "Do not infer Python receipt from parent postMessage alone.",
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

        run = run_p6_dual_page(browser, deploy=deploy, run_id=run_id)
        report.update(run)
        report["cloud_sha"] = deploy.get("cloud_sha")
        report["outcome"] = run.get("scored", {}).get("overall")
        report["transport_verdict"] = run.get("scored", {}).get("transport_verdict")
        report["processing_verdict"] = run.get("scored", {}).get("processing_verdict")
        browser.close()

    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
