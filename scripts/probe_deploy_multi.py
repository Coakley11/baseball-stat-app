"""Multi-method deploy SHA probe for production Cloud app."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
# Streamlit Community Cloud returns HTTP 400 for legacy ~/+/ paths on this app.
LDR_URL = f"{BASE}/?active_page=Live%20Draft%20Room"
URL = LDR_URL
EXPECTED = "8fade52"
OUT = Path(__file__).resolve().parent.parent / "data" / "cloud_deploy_multi_probe.json"
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def scrape_frames(page) -> dict:
    return page.evaluate(
        """() => {
          function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
          let text=''; let html=''; let el=null;
          for (const root of roots()) {
            if (root.body) text += root.body.innerText + '\\n';
            if (root.documentElement) html += root.documentElement.innerHTML + '\\n';
            if (!el) el = root.querySelector('#solo-deploy-build');
          }
          return {
            title: document.title || '',
            text_len: text.length,
            html_len: html.length,
            iframe_count: document.querySelectorAll('iframe').length,
            text_snippet: text.slice(0, 500),
            el_sha: el ? (el.getAttribute('data-sha') || '') : '',
            el_build: el ? (el.getAttribute('data-build') || '') : '',
            html_has_comment: html.includes('solo-deploy-build sha='),
          };
        }"""
    )


def sha_from_html(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    m = re.search(r"solo-deploy-build sha=([0-9a-f]{7})", html, re.I)
    if m:
        out["comment"] = m.group(1).lower()
    m2 = re.search(r'data-sha="([0-9a-f]{7})"', html, re.I)
    if m2:
        out["data_attr"] = m2.group(1).lower()
    m3 = re.search(r"baseball-dev-([0-9a-f]{7})", html, re.I)
    if m3:
        out["label"] = m3.group(1).lower()
    return out


def main() -> int:
    from playwright.sync_api import sync_playwright

    from cloud_streamlit_wake import all_frames_text, ensure_app_awake, is_app_asleep

    report: dict = {
        "url": URL,
        "expected_sha": EXPECTED,
        "github_dev_head": "aa51121",
        "github_fix_sha": "8fade52",
        "attempts": [],
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        resp = page.goto(URL, wait_until="domcontentloaded", timeout=240000)
        report["http_status"] = resp.status if resp else None
        wake_info = ensure_app_awake(page, timeout_s=240)
        report["wake"] = wake_info
        t0 = time.time()
        for i in range(60):
            text = all_frames_text(page)
            if is_app_asleep(text):
                ensure_app_awake(page, timeout_s=90)
            page.wait_for_timeout(5000)
            html = page.content()
            frame = scrape_frames(page)
            html_sha = sha_from_html(html)
            observed = (
                str(frame.get("el_sha") or "")
                or html_sha.get("comment", "")
                or html_sha.get("data_attr", "")
                or html_sha.get("label", "")
            ).lower()[:7]
            row = {
                "i": i + 1,
                "elapsed_s": round(time.time() - t0, 1),
                **frame,
                "html_sha": html_sha,
                "observed_sha": observed,
            }
            report["attempts"].append(row)
            if observed or int(frame.get("text_len") or 0) > 200:
                report["deployed_sha_observed"] = observed
                report["app_loaded"] = int(frame.get("text_len") or 0) > 200
                if observed == EXPECTED:
                    report["build_confirmed"] = True
                    break
                if observed and observed != EXPECTED:
                    report["build_confirmed"] = False
                    break
        browser.close()

    report["deployed_sha_observed"] = report.get("deployed_sha_observed") or ""
    report["build_confirmed"] = report.get("deployed_sha_observed") == EXPECTED
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("http_status", "deployed_sha_observed", "build_confirmed", "app_loaded") if k in report}, indent=2))
    print("saved", OUT)
    return 0 if report.get("build_confirmed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
