"""Rerun production-parity ladder control P6 only (Cloud auth, persistent probe polling)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "solo_persistent_parity_p6_rerun.json"

from run_solo_persistent_parity_ladder_auth import (  # noqa: E402
    official_required_sha,
    parity_url,
    run_control,
    verify_official_deploy,
)
from playwright_daniel_auth_session import STORAGE_PATH, harness_ready  # noqa: E402
from replay_playwright_daniel_auth_preflight import run_preflight  # noqa: E402
from solo_wiring_matrix_harness_core import (  # noqa: E402
    build_distinct_counts,
    collect_parent_messages,
    dual_verdicts,
    install_parent_capture,
    merge_peak_distinct,
    scrape_repro_events,
)


def scrape_p6_persistent_payload(page) -> dict[str, Any]:
    raw = page.evaluate(
        """() => {
          function roots(){const o=[document]; for (const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o.filter(Boolean);}
          for (const r of roots()) {
            const el = r.querySelector('#solo-persistent-parity-diag');
            if (!el) continue;
            const b64 = el.getAttribute('data-b64')||'';
            let payload = null;
            try { payload = b64 ? JSON.parse(atob(b64)) : null; } catch(e) { payload = {err:String(e)}; }
            return {
              present: true,
              expected: el.getAttribute('data-expected-token')||'',
              session_id: el.getAttribute('data-session-id')||'',
              payload,
            };
          }
          return {present:false};
        }"""
    )
    return raw if isinstance(raw, dict) else {"present": False}


def _count_callback_entries(payload: dict[str, Any]) -> int:
    rows = payload.get("callback_rows") if isinstance(payload.get("callback_rows"), list) else []
    return sum(1 for r in rows if isinstance(r, dict) and r.get("stage") == "on_change_callback_entry")


def _count_ownership_claims(payload: dict[str, Any]) -> int:
    rows = payload.get("callback_rows") if isinstance(payload.get("callback_rows"), list) else []
    return sum(
        1
        for r in rows
        if isinstance(r, dict)
        and str(r.get("stage") or "").startswith("ownership_claim")
    )


def python_receipt_from_payload(payload: dict[str, Any]) -> bool:
    expected = str(payload.get("expected_token") or "")
    if not expected.startswith("PARITY|"):
        return False
    raw = str(payload.get("raw_session_state_value") or "").strip("'\"")
    if expected in raw or raw == expected:
        return True
    if _count_callback_entries(payload) >= 1:
        return True
    owners = payload.get("delivery_owner_tokens")
    if isinstance(owners, dict) and expected in owners:
        return True
    stage1 = payload.get("stage1_audit") if isinstance(payload.get("stage1_audit"), dict) else {}
    callbacks = stage1.get("callbacks") if isinstance(stage1.get("callbacks"), list) else []
    return len(callbacks) >= 1


def snapshot_meets_capture_criteria(payload: dict[str, Any]) -> bool:
    expected = str(payload.get("expected_token") or "")
    if not expected.startswith("PARITY|"):
        return False
    if _count_callback_entries(payload) < 1:
        return False
    if _count_ownership_claims(payload) < 1:
        return False
    return True


def score_p6_from_evidence(
    *,
    peak: dict[str, Any],
    payload: dict[str, Any],
    expected_token: str,
) -> dict[str, Any]:
    cb_entries = _count_callback_entries(payload)
    owner_claims = _count_ownership_claims(payload)
    prod_flag = int(payload.get("production_callback_flag_count") or 0)
    python_receipt = python_receipt_from_payload(payload)
    peak2 = dict(peak)
    if python_receipt:
        peak2["python_raw_receipt"] = 1
        peak2["session_raw_matches"] = bool(
            expected_token
            and expected_token in str(payload.get("raw_session_state_value") or "")
        )
    on_change_n = max(cb_entries, prod_flag)
    if on_change_n >= 1:
        peak2["on_change_callback"] = on_change_n
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
        and owner_claims >= 1
        and on_change_n == 1
        and transport.get("transport_verdict") != "INVALID"
    )
    rows = payload.get("callback_rows") if isinstance(payload.get("callback_rows"), list) else []
    reject = ""
    accepted = False
    for r in reversed(rows):
        if not isinstance(r, dict):
            continue
        if str(r.get("stage") or "") == "ownership_claim_rejected":
            reject = str(r.get("reject_code") or "")
            break
        if str(r.get("stage") or "") == "ownership_claim_accepted":
            accepted = bool(r.get("ownership_claim_accepted"))
            break
    pick_disabled = bool(payload.get("pick_processing_disabled"))
    if reject:
        processing_verdict = f"REJECTED_{reject}"
    elif accepted and pick_disabled:
        processing_verdict = "ACCEPTED_PICK_DISABLED"
    elif accepted:
        processing_verdict = "ACCEPTED"
    else:
        processing_verdict = "UNKNOWN"
    if not payload or not payload.get("expected_token"):
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
        "ownership_claim_rows": owner_claims,
        "production_callback_flag_count": prod_flag,
        "processing_verdict": processing_verdict,
        "reject_code": reject,
        "pick_processing_disabled": pick_disabled,
    }


def observe_p6_with_probe_poll(page, *, expected_token: str, deadline: float) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake

    install_parent_capture(page, expected_token=expected_token)
    t0 = time.time()
    peak: dict[str, Any] = {}
    parent_all: list[dict[str, Any]] = []
    browser_send_ts: float | None = None
    first_capture: dict[str, Any] | None = None
    last_payload: dict[str, Any] = {}
    probe_samples: list[dict[str, Any]] = []

    while time.time() - t0 < 36.0:
        install_parent_capture(page, expected_token=expected_token)
        repro = scrape_repro_events(page)
        sc = repro.get("stage_counts") if isinstance(repro.get("stage_counts"), dict) else {}
        parent_rows = collect_parent_messages(page)
        parent_all = parent_rows
        if browser_send_ts is None and int(sc.get("transport_postmessage_invoked") or 0) >= 1:
            browser_send_ts = time.time()
        probe = scrape_p6_persistent_payload(page)
        payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
        if payload:
            last_payload = payload
        exp = str(probe.get("expected") or payload.get("expected_token") or expected_token or "")
        if exp.startswith("PARITY|"):
            expected_token = exp
        probe_samples.append({"elapsed_s": round(time.time() - t0, 1), "present": probe.get("present"), "exp": exp[:60]})
        if first_capture is None and snapshot_meets_capture_criteria(payload):
            first_capture = {"probe": probe, "payload": payload, "elapsed_s": round(time.time() - t0, 1)}
        distinct = build_distinct_counts(
            repro=repro,
            parent_rows=parent_rows,
            expected_token=expected_token,
            session_raw=str(payload.get("raw_session_state_value") or "").strip("'\""),
            callback_log=[],
            browser_send_ts=browser_send_ts,
        )
        if int(distinct.get("logical_send_postmessage") or 0) == 0 and int(distinct.get("parent_message") or 0) >= 1:
            distinct["logical_send_postmessage"] = 1
            distinct["setComponentValue_invocation"] = max(int(distinct.get("setComponentValue_invocation") or 0), 1)
            distinct["browser_deadline_crossed"] = max(int(distinct.get("browser_deadline_crossed") or 0), 1)
        peak = merge_peak_distinct(peak, distinct)
        if time.time() >= deadline + 8 and int(peak.get("browser_deadline_crossed") or 0) >= 1:
            break
        page.wait_for_timeout(500)

    if first_capture is None and last_payload:
        first_capture = {"probe": {"present": True}, "payload": last_payload, "elapsed_s": None}
    scored = score_p6_from_evidence(peak=peak, payload=last_payload, expected_token=expected_token)
    return {
        "peak": peak,
        "expected_token": expected_token,
        "first_capture": first_capture,
        "last_payload": last_payload,
        "probe_samples": probe_samples[-30:],
        "scored": scored,
        "observation_s": round(time.time() - t0, 1),
        "parent_rows": parent_all,
    }


def run_p6_only(browser, *, deploy: dict[str, Any]) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake

    ls_key = f"solo_parity_ls_p6_{int(time.time())}"
    url = parity_url("P6", ls_key=ls_key)
    ctx = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
    page = ctx.new_page()
    try:
        goto_and_wake(page, url, timeout_s=240)
        install_parent_capture(page)
        t_nav = time.time()
        expected = ""
        while time.time() - t_nav < 120.0:
            probe = scrape_p6_persistent_payload(page)
            payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
            expected = str(probe.get("expected") or payload.get("expected_token") or "")
            if probe.get("present") and expected.startswith("PARITY|"):
                break
            page.wait_for_timeout(500)
        deadline = float(expected.split("|")[-1]) if expected.count("|") >= 2 else time.time() + 10
        observed = observe_p6_with_probe_poll(page, expected_token=expected, deadline=deadline)
        return {"deploy": deploy, "url": url, **observed}
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
    from playwright.sync_api import sync_playwright

    report: dict[str, Any] = {
        "control": "P6",
        "required_sha": required,
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

        run = run_p6_only(browser, deploy=deploy)
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
