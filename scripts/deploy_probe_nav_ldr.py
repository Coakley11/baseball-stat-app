"""Navigate to Live Draft Room then scrape deploy SHA."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
ROOT = _SCRIPTS.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

URL = (
    "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
    "?active_page=Live%20Draft%20Room"
)
ISOLATION = "6108c9c"


def includes_isolation(sha: str) -> bool:
    sha = str(sha or "").lower()[:7]
    if not sha:
        return False
    if sha == ISOLATION:
        return True
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ISOLATION, sha],
            cwd=ROOT,
            capture_output=True,
        ).returncode
        == 0
    )


def click_live_draft_sidebar(page) -> str:
    return str(
        page.evaluate(
            """() => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              for (const root of roots()) {
                for (const el of root.querySelectorAll('label')) {
                  const t = String(el.innerText || '').replace(/\\s+/g, ' ').trim();
                  if (t.includes('Live Draft Room')) { el.click(); return t; }
                }
              }
              return '';
            }"""
        )
        or ""
    )


def main() -> int:
    from cloud_streamlit_wake import all_frames_text, goto_and_wake
    from playwright.sync_api import sync_playwright
    from run_solo_clean_verification import scrape_live_sha

    origin = subprocess.check_output(
        ["git", "rev-parse", "--short", "origin/dev"], cwd=ROOT, text=True
    ).strip()
    report: dict = {"origin_dev": origin, "steps": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        goto_and_wake(page, URL, timeout_s=240)
        page.wait_for_timeout(8000)
        report["steps"].append(
            {
                "phase": "initial",
                "sha": scrape_live_sha(page),
                "start_btn": "Start New Live Draft" in all_frames_text(page),
            }
        )
        label = click_live_draft_sidebar(page)
        report["sidebar_click_label"] = label
        for wait in (8, 20, 40):
            page.wait_for_timeout(wait * 1000)
            text = all_frames_text(page)
            sha = scrape_live_sha(page)
            report["steps"].append(
                {
                    "phase": f"after_sidebar_{wait}s",
                    "sha": sha,
                    "includes_isolation": includes_isolation(sha),
                    "start_btn": "Start New Live Draft" in text,
                }
            )
            if sha:
                report["observed_sha"] = sha
                break
        browser.close()

    report["observed_sha"] = report.get("observed_sha") or ""
    report["includes_isolation_build"] = includes_isolation(str(report.get("observed_sha")))
    out = ROOT / "data" / "deploy_probe_nav_ldr.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["includes_isolation_build"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
