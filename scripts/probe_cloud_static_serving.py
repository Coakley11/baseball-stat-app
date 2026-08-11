"""Standalone Cloud static-serving probe for repo-backed S3 OOB control file."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
OUT = ROOT / "data" / "cloud_static_serving_repo_probe.json"


def _harness_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
    except Exception:
        return ""


def main() -> int:
    from playwright.sync_api import sync_playwright

    from cloud_streamlit_wake import goto_and_wake
    from run_production_stage1_authenticated import resolve_required_cloud_sha
    from stage1_s3_static_serving_probe import (
        REPO_STATIC_PROBE_RELATIVE_PATH,
        classify_repo_static_probe_result,
        fetch_repo_static_probe_via_page,
    )
    from verify_cloud_deploy_playwright import scrape_deploy

    required = (resolve_required_cloud_sha() or os.environ.get("REQUIRED_CLOUD_SHA") or "").strip().lower()[:7]
    if not required:
        print(json.dumps({"ok": False, "classification": "ABORTED_REQUIRED_CLOUD_SHA_MISSING"}))
        return 1

    report: dict = {
        "mode": "cloud_static_serving_repo_probe",
        "harness_sha": _harness_sha(),
        "required_cloud_sha": required,
        "requested_path": REPO_STATIC_PROBE_RELATIVE_PATH,
        "uses_bridge": False,
        "uses_auth": False,
        "creates_draft_room": False,
        "started_at": time.time(),
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        goto_and_wake(page, BASE + "/", timeout_s=180)
        page.wait_for_timeout(6000)
        deploy = scrape_deploy(page)
        runtime_sha = str(deploy.get("sha") or "").strip().lower()[:7]
        report["application_runtime_sha"] = runtime_sha
        report["deploy_build"] = deploy.get("build")
        if runtime_sha != required:
            report["classification"] = "ABORTED_RUNTIME_SHA_MISMATCH"
            report["ok"] = False
            report["finished_at"] = time.time()
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(OUT)}))
            return 1

        fetch = fetch_repo_static_probe_via_page(page, cache_bust=True)
        classification, note, ok = classify_repo_static_probe_result(fetch)
        report["fetch"] = fetch
        report["classification"] = classification
        report["classification_note"] = note
        report["ok"] = ok
        report["finished_at"] = time.time()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        browser.close()

    print(json.dumps({"ok": report["ok"], "classification": report["classification"], "artifact": str(OUT)}))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
