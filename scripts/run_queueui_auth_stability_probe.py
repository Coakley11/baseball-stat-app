"""Headed read-only auth stability probe (no Start click)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "queueui_auth_stability_probe.json"
HARNESS_SID = "6d52dc9e-7808-4e64-a04c-aec8e3423de8"
TARGET_SHA = "967fb54"
MIN_SCRIPT_SEQ_OBSERVATIONS = 3


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from p8_production_start_harness import scrape_stage1_ledger_rows
    from playwright.sync_api import sync_playwright
    from playwright_auth_preflight_strict import inspect_start_control, paired_transition_authenticated
    from playwright_auth_strict_evidence import build_strict_auth_evidence, strict_preflight_from_page_scoped
    from playwright_daniel_auth_session import STORAGE_PATH, append_suite_sid_to_url, harness_ready, load_suite_sid
    from queueui_audit_protocol import distinct_global_script_run_seqs, queueui_root_predicate_audit_url_base, scrape_deploy_marker_from_page
    from p8_production_start_harness import scrape_stage1_ledger_rows as scrape_ledger

    report: dict[str, Any] = {
        "started_at": time.time(),
        "target_sha": TARGET_SHA,
        "harness_sid": load_suite_sid() or HARNESS_SID,
        "passed": False,
        "classification": "",
        "observations": [],
    }
    if not harness_ready():
        report["failure"] = "harness_files_incomplete"
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 1

    harness_sid = load_suite_sid()
    url = append_suite_sid_to_url(queueui_root_predicate_audit_url_base(), harness_sid)
    with sync_playwright() as p:
        headed = str(__import__("os").environ.get("HEADED", "1")).strip().lower() in ("1", "true", "yes")
        browser = p.chromium.launch(
            headless=not headed,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(15000)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(3000)
        except Exception:
            pass

        live_sha, _ = scrape_deploy_marker_from_page(page)
        report["live_sha"] = live_sha
        if live_sha != TARGET_SHA[:7]:
            report["failure"] = "runtime_sha_mismatch"
            browser.close()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            return 2

        deadline = time.time() + 240
        seen_seqs: set[int] = set()
        run_id = ""
        st_sid = ""
        last_ledger: list[dict[str, Any]] = []
        while time.time() < deadline and len(seen_seqs) < MIN_SCRIPT_SEQ_OBSERVATIONS:
            ledger = scrape_ledger(page) or []
            last_ledger = ledger
            seqs = distinct_global_script_run_seqs(ledger)
            for s in seqs:
                if s in seen_seqs:
                    continue
                for row in reversed(ledger):
                    if int(row.get("script_run_seq") or 0) == s:
                        run_id = str(row.get("run_id") or row.get("diagnostic_run_id") or run_id)
                        st_sid = str(row.get("streamlit_session_id") or st_sid)
                        break
                seen_seqs.add(s)
                start = inspect_start_control(page)
                paired = paired_transition_authenticated(page)
                strict = strict_preflight_from_page_scoped(
                    page,
                    harness_sid=harness_sid,
                    ledger_rows=ledger,
                    diagnostic_run_id=run_id,
                    streamlit_session_id=st_sid,
                )
                obs = build_strict_auth_evidence(
                    harness_sid=harness_sid,
                    url=page.url or "",
                    ledger_rows=ledger,
                    start_inspect=start,
                    paired_authenticated=paired,
                    diagnostic_run_id=run_id,
                    streamlit_session_id=st_sid,
                    evaluation=strict,
                )
                obs["script_run_seq"] = s
                obs["streamlit_session_id"] = st_sid
                obs["diagnostic_run_id"] = run_id
                obs["strict_pass"] = bool(strict.get("authenticated_restored"))
                report["observations"].append(obs)
            page.wait_for_timeout(5000)

        browser.close()

    report["streamlit_session_id"] = st_sid
    report["diagnostic_run_id"] = run_id
    report["script_run_seqs_observed"] = sorted(seen_seqs)
    obs = report["observations"]
    if len(seen_seqs) < MIN_SCRIPT_SEQ_OBSERVATIONS:
        report["classification"] = "AUTH_STABILITY8"
        report["failure"] = "insufficient_script_run_observations"
    elif len({o.get("streamlit_session_id") for o in obs}) > 1:
        report["classification"] = "AUTH_STABILITY6"
        report["failure"] = "multiple_streamlit_sessions"
    elif not all(o.get("strict_pass") for o in obs):
        report["classification"] = "AUTH_STABILITY4"
        report["failure"] = "auth_not_stable_across_reruns"
    else:
        report["passed"] = True
        report["classification"] = "AUTH_STABILITY1"
    report["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "classification": report["classification"], "artifact": str(OUT)}))
    return 0 if report["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
