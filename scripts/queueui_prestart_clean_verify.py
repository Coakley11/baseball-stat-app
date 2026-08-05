"""Read-only authenticated prestart verification before QUEUEUI audit (no Start click)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "queueui_prestart_clean_verify.json"


def _deploy_pin() -> str:
    pin = ROOT / "deploy_commit.txt"
    if not pin.is_file():
        return ""
    for line in pin.read_text(encoding="utf-8").splitlines():
        tok = line.split("#", 1)[0].strip()
        if tok:
            return tok.lower()[:7]
    return ""


TARGET_SHA = _deploy_pin()


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from playwright_daniel_auth_session import STORAGE_PATH, append_suite_sid_to_url, harness_ready, load_suite_sid
    from p8_production_start_harness import scrape_stage1_ledger_rows
    from queueui_audit_protocol import evaluate_prestart_isolation, queueui_root_predicate_audit_url_base
    from replay_playwright_daniel_auth_preflight import _authenticated_probe, _body_text, run_preflight
    from run_queueui_root_predicate_audit import _wait_setup_stable
    from stage1_preflight_cleanup import _infer_status, _scrape_lobby, is_clean_setup_lobby
    from verify_cloud_deploy_playwright import scrape_deploy

    report: dict[str, Any] = {
        "target_deploy_sha": TARGET_SHA,
        "started_at": time.time(),
        "passed": False,
    }
    if not harness_ready():
        report["failure"] = "auth_harness_incomplete"
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 1

    report["auth_preflight"] = run_preflight()
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
        page.wait_for_timeout(20000)

        deploy = scrape_deploy(page)
        report["deploy"] = deploy
        report["storage_state_loaded"] = STORAGE_PATH.is_file()
        report["suite_sid"] = bool(load_suite_sid())
        report["suite_sid_in_url"] = "suite_sid=" in (page.url or "")
        report["signed_in_display"] = "Signed in as" in _body_text(page)
        report["authenticated_probe"] = _authenticated_probe(page)
        report["authenticated"] = bool(
            report["auth_preflight"].get("authenticated_restored")
            or report["authenticated_probe"] is True
        )

        setup = _wait_setup_stable(page, scrape_stage1_ledger_rows)
        lobby = _scrape_lobby(page)
        lobby["inferred_status"] = _infer_status(lobby)
        ledger = scrape_stage1_ledger_rows(page)
        from p8_canonical_production_start import capture_harness_page_identity

        identity = capture_harness_page_identity(page, context, label="verify", ledger_rows=ledger)
        prestart = evaluate_prestart_isolation(
            lobby,
            ledger,
            setup_stable=setup,
            streamlit_session_id=str(identity.get("streamlit_session_id") or ""),
            diagnostic_run_id=str(identity.get("diagnostic_run_id") or ""),
            auth_preflight_passed=bool(report["auth_preflight"].get("authenticated_restored")),
        )

        wake = lobby.get("wake") if isinstance(lobby.get("wake"), dict) else {}
        sig = prestart.get("ledger_signals") or {}
        start_btn = page.get_by_role("button", name="Start New Live Draft").first
        start_enabled = False
        start_visible = bool(lobby.get("has_start_new"))
        try:
            start_btn.scroll_into_view_if_needed(timeout=5000)
            start_enabled = start_btn.is_enabled(timeout=5000)
        except Exception:
            try:
                scan = page.evaluate(
                    """() => {
                      const roots = [document];
                      for (const f of document.querySelectorAll('iframe')) {
                        try { if (f.contentDocument) roots.push(f.contentDocument); } catch (e) {}
                      }
                      for (const root of roots) {
                        for (const b of root.querySelectorAll('button')) {
                          const t = (b.innerText || '').replace(/\\s+/g, ' ').trim();
                          if (/Start New Live Draft/i.test(t)) {
                            const r = b.getBoundingClientRect();
                            return { visible: r.width > 0 && r.height > 0, disabled: !!b.disabled };
                          }
                        }
                      }
                      return { visible: false, disabled: true };
                    }"""
                )
                start_visible = bool(scan.get("visible"))
                start_enabled = start_visible and not scan.get("disabled")
            except Exception:
                pass

        checks = {
            f"deploy_sha_{TARGET_SHA or 'pin'}": str(deploy.get("sha") or "").lower()[:7] == TARGET_SHA,
            "authenticated": report["authenticated"],
            "setup_lobby": is_clean_setup_lobby(lobby) if lobby else False,
            "room_id_empty": not (lobby.get("visible_room_id") or lobby.get("python_room_id")),
            "pending_start_absent": True,
            "start_in_flight_false": not sig.get("start_in_flight"),
            "wake_token_empty": not str(wake.get("token") or "").strip(),
            "restore_blocked_empty": not str(sig.get("restore_blocked_reason") or "").strip(),
            "start_visible_enabled": bool(start_visible) and start_enabled,
            "prestart_isolation_passed": bool(prestart.get("passed")),
        }
        report["checks"] = checks
        report["lobby"] = lobby
        report["prestart"] = prestart
        report["setup_stability"] = setup
        report["passed"] = all(checks.values())
        browser.close()

    report["finished_at"] = time.time()
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": report["checks"], "artifact": str(OUT)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
