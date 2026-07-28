"""One-shot RV3 Cloud page observation (no delivery grading)."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "rv3_page_observation.json"
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from playwright_daniel_auth_session import STORAGE_PATH, append_suite_sid_to_url
    from replay_playwright_daniel_auth_preflight import run_preflight

    from run_solo_rv_binding_ladder_auth import (
        attach_page_diagnostics,
        redact_url,
        scrape_control_probe,
        scrape_page_dom_snapshot,
        scrape_visible_page_text,
        state_ledger_rows_for_run,
    )
    from solo_rv_ladder_runner_state import classify_page_shell

    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        print(json.dumps({"ok": False, "reason": "auth_preflight_failed"}))
        return 1

    run_id = str(uuid.uuid4())
    q = urlencode(
        {
            "solo_rv_ladder": "RV3",
            "solo_rv_run_id": run_id,
            "solo_delivery_diag": "1",
            "solo_component_diag": "1",
            "solo_diag_timer": "10",
            "active_page": "Live Draft Room",
        }
    )
    url = append_suite_sid_to_url(f"{BASE}/?{q}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=str(STORAGE_PATH),
            viewport={"width": 1440, "height": 1400},
        )
        page = context.new_page()
        diagnostics = attach_page_diagnostics(page)
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(45000)
        text = scrape_visible_page_text(page)
        dom = scrape_page_dom_snapshot(page)
        probe = scrape_control_probe(page)
        rows = state_ledger_rows_for_run(probe, run_id)
        page_state = classify_page_shell(page_text=text, dom=dom, rows=rows, probe=probe)
        shot = OUT.with_suffix(".png")
        try:
            page.screenshot(path=str(shot), full_page=True)
        except Exception as exc:
            shot = None
            screenshot_error = str(exc)
        else:
            screenshot_error = ""
        exception_text = ""
        try:
            exception_text = page.evaluate(
                """() => {
                  const el = document.querySelector('.stException, [data-testid="stException"]');
                  return el ? el.innerText : '';
                }"""
            )
        except Exception:
            pass
        result = {
            "run_id": run_id,
            "final_url": redact_url(page.url),
            "page_title": page.title(),
            "page_state": page_state,
            "dom": dom,
            "probe_parse": dict(probe.get("_probe_parse") or {}),
            "ledger_row_count_all": len(probe.get("rows") or []),
            "ledger_row_count_run": len(rows),
            "has_ledger_prefix_in_text": "SOLO_RV_CONTROL_LEDGER_B64:" in text,
            "visible_text_len": len(text),
            "visible_text": text[:80000],
            "streamlit_exception_text": str(exception_text or "")[:12000],
            "console_errors": [c for c in diagnostics.get("console") or [] if c.get("type") == "error"][-30:],
            "pageerrors": list(diagnostics.get("pageerrors") or [])[-20:],
            "request_failed": list(diagnostics.get("request_failed") or [])[-30:],
            "screenshot_path": str(shot) if shot else "",
            "screenshot_error": screenshot_error,
            "has_streamlit_app_root": bool(dom.get("has_streamlit_app")),
        }
        browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: result[k] for k in result if k != "visible_text"}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
