"""Read-only bridge + pre-start auth verification (no Start click)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "queueui_bridge_verify.json"


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from playwright_auth_preflight_strict import inspect_start_control, strict_preflight_from_page, suite_sid_from_url
    from playwright_daniel_auth_session import STORAGE_PATH, append_suite_sid_to_url, harness_ready, load_suite_sid
    from p8_production_start_harness import scrape_stage1_ledger_rows
    from queueui_audit_protocol import queueui_root_predicate_audit_url_base
    from run_queueui_root_predicate_audit import _wait_setup_stable
    from stage1_preflight_cleanup import _scrape_lobby

    report: dict[str, Any] = {"started_at": time.time(), "passed": False}
    if not harness_ready():
        report["failure"] = "harness_files_incomplete"
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 1

    harness_sid = load_suite_sid()
    report["bridge_sid_harness"] = harness_sid[:8] + "…" if harness_sid else ""
    report["bridge_lookup"] = "not_checked_locally"
    if harness_sid:
        try:
            from suite_storage_supabase import load_browser_auth_session

            row = load_browser_auth_session(harness_sid)
            if row and row.get("access_token") and row.get("refresh_token"):
                report["bridge_lookup"] = "record_found"
                report["bridge_record_complete"] = True
            elif row:
                report["bridge_lookup"] = "record_incomplete"
                report["bridge_record_complete"] = False
            else:
                report["bridge_lookup"] = "record_missing"
                report["bridge_record_complete"] = False
        except Exception as exc:
            report["bridge_lookup"] = f"lookup_error:{type(exc).__name__}"
            report["bridge_record_complete"] = False

    url = append_suite_sid_to_url(queueui_root_predicate_audit_url_base())
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(15000)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(3000)
        except Exception:
            pass
        page.wait_for_timeout(25000)
        url_sid = suite_sid_from_url(page.url or "")
        report["bridge_sid_url"] = url_sid[:8] + "…" if url_sid else ""
        report["sid_consistent"] = bool(harness_sid and url_sid and harness_sid == url_sid)
        report["storage_state_loaded"] = STORAGE_PATH.is_file()

        ledger = scrape_stage1_ledger_rows(page) or []
        report["ledger_row_count"] = len(ledger)
        strict = strict_preflight_from_page(page, harness_sid=harness_sid, ledger_rows=ledger)
        report["strict_preflight"] = strict
        lobby = _scrape_lobby(page)
        start = inspect_start_control(page)
        setup = _wait_setup_stable(page, scrape_stage1_ledger_rows)
        sig = {}
        for row in reversed(ledger):
            if str(row.get("event") or "") == "production_stage1_queueui_predicate_audit":
                sig = row
                break
        report["streamlit_session_id"] = str(sig.get("streamlit_session_id") or "")[:36]
        report["suite_sid_present"] = bool(harness_sid and url_sid)
        report["hydration_source"] = strict.get("hydration_source") or ""
        report["apply_authenticated_user_ok"] = bool(strict.get("apply_authenticated_user_ok"))
        report["is_authenticated"] = bool(strict.get("streamlit_auth_complete"))
        report["auth_session_complete"] = bool(strict.get("streamlit_auth_complete"))
        report["start_visible"] = bool(start.get("visible") or lobby.get("has_start_new"))
        report["start_enabled"] = bool(start.get("enabled"))
        report["restore_blocked_reason"] = str(sig.get("restore_blocked_reason") or "").strip()
        report["setup_stable"] = setup
        browser.close()

    report["passed"] = bool(
        report.get("sid_consistent")
        and strict.get("authenticated_restored")
        and report.get("start_enabled")
        and not report.get("restore_blocked_reason")
    )
    report["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "artifact": str(OUT), "failure": strict.get("failure")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
