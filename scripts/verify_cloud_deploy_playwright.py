"""Verify Streamlit Cloud serves the expected deploy marker (#solo-deploy-build)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
PROD_URL = f"{BASE}/?active_page=Live%20Draft%20Room"
ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
ACCEPTABLE_DEPLOY_SHAS = frozenset(
    {
        "265d2bf",
        "eb31631",
        "b6a47ca",
        "8be8a78",
        "44092f7",
        "0c56dd9",
        "9c5fa0c",
        "77c10b7",
        "c875735",
        "a113d48",
        "1c88074",
        "2590eb2",
        "d2d781b",
        "342b6c3",
        "385b514",
        "543c3d6",
        "001aaba",
        "ed5c0a3",
        "6b8a53b",
        "6cb0351",
        "b21a441",
        "3af6483",
        "a771302",
        "d74c4b7",
        "8fade52",
        "aa51121",
        "1771812",
        "750fb9a",
    }
)


def expected_sha() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1].strip().lower()[:7]
    line = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0]
    return line.split("#", 1)[0].strip().lower()[:7]


def deploy_acceptable(seen: str, target: str) -> bool:
    seen = str(seen or "").strip().lower()[:7]
    if not seen:
        return False
    if seen == target:
        return True
    return seen in ACCEPTABLE_DEPLOY_SHAS


def scrape_deploy(page) -> dict[str, str]:
    return page.evaluate(
        """() => {
          function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
          for (const root of roots()) {
            const el = root.querySelector('#solo-deploy-build');
            if (el) {
              return {
                sha: (el.getAttribute('data-sha') || '').toLowerCase(),
                build: el.getAttribute('data-build') || '',
              };
            }
            const html = root.documentElement ? root.documentElement.innerHTML : '';
            const m = html.match(/solo-deploy-build sha=([0-9a-f]{7})/i);
            if (m) return { sha: m[1].toLowerCase(), build: '' };
          }
          return { sha: '', build: '' };
        }"""
    )


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake, scrape_deploy_sha_from_page

    target = expected_sha()
    result: dict = {
        "expected_sha": target,
        "prod_url": PROD_URL,
        "attempts": [],
        "ready": False,
    }
    from playwright.sync_api import sync_playwright

    deadline = time.time() + 900
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        while time.time() < deadline:
            attempt: dict = {"ts": time.time()}
            try:
                wake_info = goto_and_wake(page, PROD_URL, timeout_s=240)
                attempt["wake"] = wake_info
                page.wait_for_timeout(5000)
                probe = scrape_deploy(page)
                sha = str(probe.get("sha") or "") or scrape_deploy_sha_from_page(page)
                attempt["sha"] = sha
                attempt.update(probe)
                result["attempts"].append(attempt)
                if deploy_acceptable(str(probe.get("sha") or sha or ""), target):
                    result["ready"] = True
                    result["deploy_build_seen"] = sha or probe.get("sha")
                    result["deploy_build_label"] = probe.get("build")
                    break
            except Exception as exc:
                attempt["error"] = f"{type(exc).__name__}:{exc}"
                result["attempts"].append(attempt)
            time.sleep(20)
        browser.close()

    out = ROOT / "data" / "cloud_deploy_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
