"""Headless replay preflight for Daniel auth harness (storage + suite_sid)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "solo_auth_storage_replay_preflight.json"

from playwright_daniel_auth_session import (  # noqa: E402
    STORAGE_PATH,
    append_suite_sid_to_url,
    harness_ready,
    load_suite_sid,
)

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
START_URL = (
    f"{BASE}/?active_page=Live%20Draft%20Room"
    f"&solo_component_diag=1&solo_diag_timer=10"
)


def _body_text(page) -> str:
    return page.evaluate(
        """() => {
      const roots = [document];
      for (const f of document.querySelectorAll('iframe')) {
        try { if (f.contentDocument) roots.push(f.contentDocument); } catch (e) {}
      }
      return roots.map(r => (r.body && r.body.innerText) || '').join('\\n');
    }"""
    )


def run_preflight() -> dict:
    from playwright.sync_api import sync_playwright

    from cloud_streamlit_wake import goto_and_wake
    from p8_production_start_harness import scrape_stage1_ledger_rows
    from playwright_auth_preflight_strict import strict_preflight_from_page
    from run_solo_clean_verification import scrape_live_sha
    from verify_cloud_deploy_playwright import scrape_deploy

    result: dict = {
        "harness_ready": harness_ready(),
        "storage_file_exists": STORAGE_PATH.is_file(),
        "suite_sid_captured": bool(load_suite_sid()),
        "cloud_sha": "",
        "signed_in_display": False,
        "authenticated_app": False,
        "authenticated_restored": False,
        "failure": "",
        "strict": {},
    }
    if not result["harness_ready"]:
        result["failure"] = "harness_files_incomplete"
        return result

    harness_sid = load_suite_sid()
    url = append_suite_sid_to_url(START_URL)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=str(STORAGE_PATH),
            viewport={"width": 1440, "height": 1400},
        )
        page = context.new_page()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(25000)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(3000)
        except Exception:
            pass
        probe = scrape_deploy(page)
        result["cloud_sha"] = scrape_live_sha(page) or probe.get("sha") or ""
        text = _body_text(page)
        result["signed_in_display"] = "Signed in as" in text
        ledger = scrape_stage1_ledger_rows(page) or []
        strict = strict_preflight_from_page(page, harness_sid=harness_sid, ledger_rows=ledger)
        result["strict"] = strict
        result["authenticated_app"] = bool(strict.get("streamlit_auth_complete"))
        result["authenticated_restored"] = bool(strict.get("authenticated_restored"))
        result["failure"] = str(strict.get("failure") or "")
        if result["authenticated_restored"] and not result["signed_in_display"]:
            result["signed_in_display_note"] = "strict_preflight_ok_ui_caption_not_in_scrape"
        context.close()
        browser.close()
    return result


def main() -> int:
    result = run_preflight()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    safe = {k: v for k, v in result.items() if k != "suite_sid"}
    OUT.write_text(json.dumps(safe, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "preflight_pass": not result.get("failure"),
                "failure": result.get("failure") or None,
                "cloud_sha": result.get("cloud_sha"),
                "signed_in_display": result.get("signed_in_display"),
                "authenticated_app": result.get("authenticated_app"),
                "authenticated_restored": result.get("authenticated_restored"),
                "artifact": str(OUT),
            }
        )
    )
    return 0 if result.get("authenticated_restored") else 1


if __name__ == "__main__":
    raise SystemExit(main())
