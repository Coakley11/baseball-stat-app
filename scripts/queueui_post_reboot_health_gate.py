"""Post-reboot Cloud health gate before auth-snapshot audit."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "queueui_post_reboot_health_gate.json"
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
AUTH_EVENTS = (
    "production_stage1_auth_state_before_start_control",
    "production_stage1_auth_snapshot_capture",
    "production_stage1_auth_prestart_hydration",
)


def main() -> int:
    from probe_live_deploy import backend_health_ok, fetch_body

    pin = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0].split("#", 1)[0].strip()[:7]
    target_app_sha = pin
    target_build = f"baseball-dev-{pin}"
    try:
        subprocess.run(["git", "fetch", "origin", "dev"], cwd=ROOT, capture_output=True, timeout=60)
        origin_dev = subprocess.check_output(
            ["git", "rev-parse", "--short", "origin/dev"], cwd=ROOT, text=True
        ).strip()
        ancestor_ok = (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", pin, "origin/dev"],
                cwd=ROOT,
                capture_output=True,
            ).returncode
            == 0
        )
    except Exception as exc:
        origin_dev = ""
        ancestor_ok = False
        fetch_err = str(exc)
    else:
        fetch_err = ""

    health_ok, health_body = backend_health_ok(BASE)
    embed_status, embed_body = fetch_body(BASE + "/?embed=true", max_bytes=50000)
    gzip_in_body = "thread_minimum_size" in embed_body or "GZipResponder" in embed_body
    http500 = "Internal Server Error" in embed_body or embed_status >= 500
    health_signal_ok = health_ok or (embed_status == 200 and not http500 and not gzip_in_body)

    report: dict = {
        "ts": time.time(),
        "deploy_commit_txt_pin": pin,
        "target_app_sha": target_app_sha,
        "target_marker_sha": pin,
        "target_build": target_build,
        "origin_dev_short": origin_dev,
        "origin_dev_is_marker_or_descendant": ancestor_ok,
        "git_fetch_error": fetch_err,
        "backend_stcore_health_ok": health_ok,
        "health_signal_ok": health_signal_ok,
        "backend_stcore_health_body": health_body,
        "embed_probe_status": embed_status,
        "embed_gzip_traceback_in_html": gzip_in_body,
        "embed_http500_signal": http500,
        "branch_required": "dev",
    }

    playwright: dict = {"ok": False, "reason": "not_run"}
    if not health_signal_ok:
        report["playwright"] = playwright
        report["gate_pass"] = False
        report["stop_reason"] = "backend_health_or_http500"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    from cloud_streamlit_wake import all_frames_text, goto_and_wake
    from playwright.sync_api import sync_playwright
    from playwright_daniel_auth_session import STORAGE_PATH, append_suite_sid_to_url, harness_ready
    from stage1_ledger_browser_extract import extract_stage1_ledger_from_page
    from verify_cloud_deploy_playwright import scrape_deploy

    if not harness_ready():
        playwright = {"ok": False, "reason": "auth_harness_incomplete"}
        report["playwright"] = playwright
        report["gate_pass"] = False
        report["stop_reason"] = "harness"
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 2

    url = append_suite_sid_to_url(
        f"{BASE}/?active_page=Live%20Draft%20Room&solo_component_diag=1&solo_diag_timer=10"
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=str(STORAGE_PATH),
            viewport={"width": 1440, "height": 1600},
        )
        page = context.new_page()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(35000)
        deploy = scrape_deploy(page)
        text = all_frames_text(page).lower()
        html = page.content().lower()
        rows = extract_stage1_ledger_from_page(page) or []
        events = {str(r.get("event") or "") for r in rows if isinstance(r, dict)}
        sha = str(deploy.get("sha") or "")[:7].lower()
        build = str(deploy.get("build") or "")
        auth_avail = sha == target_app_sha or any(
            "production_stage1_auth_" in e for e in events
        )
        fs_git = ""
        for fr in page.frames:
            try:
                fs_git = fr.evaluate(
                    """() => {
                      const el = document.querySelector('#solo-cloud-fs-probe');
                      return el ? (el.getAttribute('data-git-head-short') || '') : '';
                    }"""
                ) or fs_git
            except Exception:
                pass
        starlette_req = ""
        for fr in page.frames:
            try:
                starlette_req = fr.evaluate(
                    """() => {
                      const el = document.querySelector('#solo-cloud-fs-probe');
                      if (!el) return '';
                      const raw = el.getAttribute('data-deploy-commit-raw') || '';
                      return raw;
                    }"""
                ) or starlette_req
            except Exception:
                pass
        page_ok = "start new live draft" in text and "internal server error" not in text
        gzip_err = "thread_minimum_size" in html or "gzipresponder" in html
        playwright = {
            "ok": True,
            "visible_sha": sha,
            "visible_build": build,
            "fs_probe_git_head_short": fs_git,
            "page_load_ok": page_ok,
            "gzip_error_in_dom": gzip_err,
            "ledger_row_count": len(rows),
            "auth_diag_events_present": sorted(e for e in events if "auth_snapshot" in e or "auth_state_before" in e),
            "auth_diag_available": auth_avail,
            "streamlit_version_note": "1.59.1 required (pinned requirements.txt)",
            "starlette_version_note": "0.52.1 required (pinned requirements.txt; install inferred from healthy gzip)",
        }
        browser.close()

    report["playwright"] = playwright
    sha_ok = sha == target_app_sha
    build_ok = build == target_build or build.endswith(target_app_sha)
    report["gate_pass"] = bool(
        ancestor_ok
        and pin == target_app_sha
        and health_signal_ok
        and not gzip_in_body
        and sha_ok
        and build_ok
        and playwright.get("page_load_ok")
        and not playwright.get("gzip_error_in_dom")
        and playwright.get("auth_diag_available")
    )
    report["checks"] = {
        "pin_matches": pin == target_app_sha,
        "visible_sha_matches": sha_ok,
        "visible_build_matches": build_ok,
        "health_ok": health_signal_ok,
        "page_load_ok": playwright.get("page_load_ok"),
        "auth_diag_ok": playwright.get("auth_diag_available"),
    }
    if not report["gate_pass"]:
        report["stop_reason"] = "gate_checks_failed"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"gate_pass": report["gate_pass"], "visible_sha": sha, "build": build}, indent=2))
    return 0 if report["gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
