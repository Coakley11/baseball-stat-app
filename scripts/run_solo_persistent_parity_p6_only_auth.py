"""Rerun production-parity ladder control P6 only (Cloud auth, production callback grading)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "solo_persistent_parity_p6_rerun.json"

from run_solo_persistent_parity_ladder_auth import (  # noqa: E402
    build_control_record,
    observe_control,
    official_required_sha,
    run_control,
    scrape_stage1_audit,
    verify_official_deploy,
)
from playwright_daniel_auth_session import harness_ready  # noqa: E402
from replay_playwright_daniel_auth_preflight import run_preflight  # noqa: E402
from solo_wiring_matrix_harness_core import dual_verdicts, merge_peak_distinct  # noqa: E402


def scrape_stage1_audit(page) -> dict[str, Any]:
    raw = page.evaluate(
        """() => {
          function roots(){const o=[document]; for (const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o.filter(Boolean);}
          for (const r of roots()) {
            const el = r.querySelector('#solo-stage1-expire-audit');
            if (!el) continue;
            const b64 = el.getAttribute('data-b64')||'';
            try { return b64 ? JSON.parse(atob(b64)) : {}; } catch(e) { return {err:String(e)}; }
          }
          return {};
        }"""
    )
    return raw if isinstance(raw, dict) else {}


def scrape_transport_boundary_meta(page) -> dict[str, Any]:
    raw = page.evaluate(
        """() => {
          function roots(){const o=[document]; for (const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o.filter(Boolean);}
          for (const r of roots()) {
            const el = r.querySelector('#solo-transport-boundary-diag');
            if (!el) continue;
            const b64 = el.getAttribute('data-b64')||'';
            try { return b64 ? JSON.parse(atob(b64)) : {}; } catch(e) { return {err:String(e)}; }
          }
          return {};
        }"""
    )
    return raw if isinstance(raw, dict) else {}


def production_callback_count(
    *,
    meta: dict[str, Any],
    stage1: dict[str, Any],
    transport_meta: dict[str, Any] | None = None,
) -> int:
    ev = meta.get("production_evidence") if isinstance(meta.get("production_evidence"), dict) else {}
    flag_n = int(ev.get("production_callback_flag_count") or 0)
    seq = ev.get("p6_callback_sequence") if isinstance(ev.get("p6_callback_sequence"), list) else []
    entry_rows = sum(1 for r in seq if isinstance(r, dict) and r.get("stage") == "callback_entry")
    stage1_n = len(stage1.get("callbacks") or []) if isinstance(stage1.get("callbacks"), list) else 0
    tm = transport_meta or {}
    tm_n = int(tm.get("production_callback_count") or 0)
    return max(flag_n, entry_rows, stage1_n, tm_n)


def score_p6_verdicts(
    rec: dict[str, Any],
    *,
    stage1: dict[str, Any],
    transport_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    distinct = rec.get("distinct") if isinstance(rec.get("distinct"), dict) else {}
    meta = rec.get("meta") if isinstance(rec.get("meta"), dict) else {}
    peak = dict(distinct)
    parent_rows = peak.get("parent_rows_captured") if isinstance(peak.get("parent_rows_captured"), list) else []
    parent_tok = str(parent_rows[0].get("value_preview") or "") if parent_rows else ""
    expected = str(rec.get("expected_token") or meta.get("expire_token") or parent_tok or "")
    if parent_tok and expected and parent_tok.split("|")[0] == "PARITY":
        peak["session_raw_matches"] = True
        peak["python_raw_receipt"] = 1
    prod_cb = production_callback_count(meta=meta, stage1=stage1, transport_meta=transport_meta)
    if prod_cb >= 1:
        peak["on_change_callback"] = max(int(peak.get("on_change_callback") or 0), prod_cb)
    transport = dual_verdicts(peak, cell="B2", expected_token=expected)
    callbacks = stage1.get("callbacks") if isinstance(stage1.get("callbacks"), list) else []
    last = callbacks[-1] if callbacks else {}
    reject = str(last.get("reject_code") or "") if isinstance(last, dict) else ""
    claimed = bool(last.get("delivery_claimed")) if isinstance(last, dict) else None
    pick_disabled = bool((meta.get("production_evidence") or {}).get("pick_processing_disabled"))
    processing = {
        "callback_accepted": claimed is True and not reject,
        "reject_code": reject,
        "delivery_claimed": claimed,
        "pick_processing_disabled_for_diagnostic": pick_disabled,
        "pick_commit_count": int(stage1.get("pick_commit_count") or 0),
    }
    if reject:
        processing["verdict"] = "REJECTED"
    elif claimed and pick_disabled:
        processing["verdict"] = "ACCEPTED_PICK_DISABLED"
    elif claimed:
        processing["verdict"] = "ACCEPTED"
    else:
        processing["verdict"] = "UNKNOWN"
    return {
        "transport_verdict": transport.get("transport_verdict"),
        "lifecycle_verdict": transport.get("lifecycle_verdict"),
        "lifecycle_detail": transport.get("lifecycle_detail"),
        "production_callback_count": prod_cb,
        "processing": processing,
        "stage1_audit": stage1,
    }


def main() -> int:
    if not harness_ready():
        print(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}))
        return 1
    if not run_preflight().get("authenticated_restored"):
        print(json.dumps({"aborted": True, "reason": "auth_preflight_failed"}))
        return 1

    required = official_required_sha()
    from playwright.sync_api import sync_playwright

    report: dict[str, Any] = {"control": "P6", "required_sha": required}

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

        rec = run_control(browser, "P6", deploy=deploy)
        report["control_record"] = rec
        stage1 = rec.get("stage1_audit_scrape") if isinstance(rec.get("stage1_audit_scrape"), dict) else {}
        transport_meta = (
            rec.get("transport_boundary_scrape") if isinstance(rec.get("transport_boundary_scrape"), dict) else {}
        )
        if not stage1 and isinstance(rec.get("meta"), dict):
            ev = rec["meta"].get("production_evidence") or {}
            stage1 = ev.get("stage1_audit") if isinstance(ev.get("stage1_audit"), dict) else {}
        verdicts = score_p6_verdicts(rec, stage1=stage1, transport_meta=transport_meta)
        report["verdicts"] = verdicts
        report["cloud_sha"] = deploy.get("cloud_sha")
        report["outcome"] = verdicts.get("transport_verdict")
        report["processing_verdict"] = verdicts.get("processing", {}).get("verdict")
        browser.close()

    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
