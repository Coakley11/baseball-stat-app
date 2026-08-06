"""Poll Cloud until deploy_commit pin is live; probe auth observability DOM markers."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "auth_observability_deploy_gate.json"
TARGET = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0].split("#", 1)[0].strip()[:7]
TARGET_BUILD = f"baseball-dev-{TARGET}"

_MARKERS_JS = """
() => {
  function count(root, id) {
    return root.getElementById(id) ? 1 : 0;
  }
  const roots = [document];
  for (const f of document.querySelectorAll('iframe')) {
    try { if (f.contentDocument) roots.push(f.contentDocument); } catch (e) {}
  }
  let current = 0, transition = 0;
  for (const r of roots) {
    current += count(r, 'solo-stage1-current-auth-state');
    transition += count(r, 'solo-stage1-auth-transition-snapshot');
  }
  return { current_auth_probe_count: current, auth_transition_probe_count: transition };
}
"""


def main() -> int:
    from cloud_streamlit_wake import all_frames_text, goto_and_wake
    from playwright.sync_api import sync_playwright
    from playwright_daniel_auth_session import STORAGE_PATH, append_suite_sid_to_url, harness_ready
    from verify_cloud_deploy_playwright import scrape_deploy

    report: dict = {
        "target_sha": TARGET,
        "target_build": TARGET_BUILD,
        "expected_branch": "dev",
        "attempts": [],
        "deploy_matched": False,
    }
    url = append_suite_sid_to_url(
        "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
        "?active_page=Live%20Draft%20Room&solo_component_diag=1&solo_stage1_parent_boundary=1"
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=str(STORAGE_PATH) if STORAGE_PATH.is_file() else None,
            viewport={"width": 1440, "height": 1600},
        )
        page = context.new_page()
        for attempt in range(24):
            t0 = time.time()
            goto_and_wake(page, url, timeout_s=240)
            page.wait_for_timeout(30000)
            deploy = scrape_deploy(page)
            sha = str(deploy.get("sha") or "")[:7]
            build = str(deploy.get("build") or "")
            markers = page.evaluate(_MARKERS_JS)
            text = all_frames_text(page)
            http500 = "HTTP status code: 500" in text or "Internal Server Error" in text
            row = {
                "attempt": attempt + 1,
                "elapsed_s": round(time.time() - t0, 1),
                "deploy_sha": sha,
                "deploy_build": build,
                "markers": markers,
                "page_healthy": not http500 and "Live Draft Room" in text,
                "gzip_regression_hint": "gzip" in text.lower() and "error" in text.lower(),
            }
            report["attempts"].append(row)
            if sha == TARGET and row["page_healthy"] and markers.get("current_auth_probe_count", 0) > 0:
                report["deploy_matched"] = True
                report["final"] = row
                break
            if sha == TARGET and row["page_healthy"]:
                report["deploy_sha_matched_checkpoints_pending"] = True
                report["final"] = row
            time.sleep(45)
        else:
            report["final"] = report["attempts"][-1] if report["attempts"] else {}
        context.close()
        browser.close()
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({**report, "artifact": str(OUT)}, indent=2))
    return 0 if report.get("deploy_matched") else 1


if __name__ == "__main__":
    raise SystemExit(main())
