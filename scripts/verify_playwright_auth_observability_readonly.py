"""Read-only headed/headless verify: Start enabled + session/ledger identity binding (no Start click)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "playwright_auth_observability_readonly_verify.json"


def _capture_url(suite_sid: str) -> str:
    base = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
    return (
        f"{base}/?active_page=Live+Draft+Room"
        f"&solo_component_diag=1&solo_stage1_parent_boundary=1&suite_sid={suite_sid}"
    )


def run_verify(*, headed: bool | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    from cloud_streamlit_wake import goto_and_wake
    from playwright_auth_observability import AUTH_OBSERVABILITY1, gather_page_observability
    from playwright_daniel_auth_session import STORAGE_PATH, harness_ready, load_suite_sid
    from queueui_audit_protocol import scrape_deploy_marker_from_page

    if headed is None:
        headed = os.environ.get("PLAYWRIGHT_HEADED", "").strip() in ("1", "true", "yes")

    result: dict = {
        "harness_ready": harness_ready(),
        "headed": headed,
        "failure": "",
        "pass": False,
    }
    if not harness_ready():
        result["failure"] = "harness_files_incomplete"
        return result

    suite_sid = load_suite_sid()
    result["suite_sid_prefix"] = suite_sid[:8] if suite_sid else ""
    url = _capture_url(suite_sid)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(
            storage_state=str(STORAGE_PATH),
            viewport={"width": 1440, "height": 1400},
        )
        page = context.new_page()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(28000)
        deploy_sha, _ = scrape_deploy_marker_from_page(page)
        obs = gather_page_observability(page, harness_sid=suite_sid, strict_failure="streamlit_auth_incomplete")
        cp = obs.get("checkpoint") or {}
        binding = obs.get("binding") or {}
        ss = obs.get("start_surface") or {}
        result.update(
            {
                "cloud_deploy_sha": deploy_sha or cp.get("deploy_sha"),
                "page_url": ss.get("page_url"),
                "start_enabled": bool(cp.get("start_enabled")),
                "start_visible": bool(cp.get("start_visible")),
                "start_frame_index": cp.get("start_frame_index"),
                "streamlit_session_id": cp.get("streamlit_session_id"),
                "diagnostic_run_id": cp.get("diagnostic_run_id"),
                "diagnostic_query_flags": cp.get("diagnostic_query_flags"),
                "ledger_row_count": binding.get("ledger_row_count"),
                "auth_hydration_row_count": binding.get("auth_hydration_row_count"),
                "url_suite_sid_match": binding.get("url_suite_sid_match"),
                "ui_ledger_streamlit_session_match": binding.get("ui_ledger_streamlit_session_match"),
                "ui_ledger_run_match": binding.get("ui_ledger_run_match"),
                "ledger_same_frame_as_start": binding.get("ledger_same_frame_as_start"),
                "is_authenticated_observed": cp.get("is_authenticated"),
                "auth_session_complete_observed": cp.get("auth_session_complete"),
                "session_flag_present_observed": cp.get("session_flag_present"),
                "auth_observability_classification": obs.get("auth_observability_classification"),
                "auth_observability_detail": obs.get("auth_observability_detail"),
                "auth_hydration_source": cp.get("auth_hydration_source"),
                "bridge_lookup_status": cp.get("bridge_lookup_status"),
                "current_auth_dom": cp.get("current_auth_dom"),
                "session_binding_failure": obs.get("session_binding_failure"),
            }
        )
        context.close()
        browser.close()

    ok = (
        result.get("start_enabled")
        and result.get("url_suite_sid_match")
        and not result.get("session_binding_failure")
        and cp.get("is_authenticated") is True
        and cp.get("auth_session_complete") is True
        and cp.get("session_flag_present") is True
        and not str(cp.get("restore_blocked_reason") or "").strip()
    )
    if ok:
        result["pass"] = True
        result["auth_observability_classification"] = ""
    elif result.get("start_enabled") and not result.get("auth_hydration_row_count"):
        result["auth_observability_classification"] = result.get("auth_observability_classification") or AUTH_OBSERVABILITY1
        result["failure"] = obs.get("override_failure") or "ledger_unavailable"
    else:
        result["failure"] = result.get("session_binding_failure") or "binding_or_auth_not_proven"
    return result


def main() -> int:
    result = run_verify()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({**result, "artifact": str(OUT)}, default=str))
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
