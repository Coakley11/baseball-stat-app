"""One-shot deploy SHA probe after Cloud reboot."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

URL = (
    "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
    "?active_page=Live%20Draft%20Room"
)
ISOLATION_ANCHOR = "6108c9c"
CAND = ("c7a748b", "6b38df4", "6108c9c", "ca10b70", "4d73e84")
OUT = ROOT / "data" / "deploy_probe_reboot.json"


def includes_isolation(short_sha: str) -> bool:
    sha = str(short_sha or "").strip().lower()[:7]
    if not sha:
        return False
    if sha == ISOLATION_ANCHOR:
        return True
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ISOLATION_ANCHOR, sha],
            cwd=ROOT,
            capture_output=True,
            timeout=10,
        ).returncode
        == 0
    )


def sha_from_html(html: str) -> str:
    for pat in (
        r"solo-deploy-build sha=([0-9a-f]{7})",
        r'data-sha="([0-9a-f]{7})"',
        r"baseball-dev-([0-9a-f]{7})",
    ):
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1).lower()
    return ""


def main() -> int:
    from cloud_streamlit_wake import (
        all_frames_text,
        goto_and_wake,
        is_app_asleep,
        scrape_deploy_sha_from_page,
        wake_streamlit_app,
    )
    from playwright.sync_api import sync_playwright

    origin_dev = subprocess.check_output(
        ["git", "rev-parse", "--short", "origin/dev"], cwd=ROOT, text=True
    ).strip()
    report: dict = {
        "url": URL,
        "origin_dev": origin_dev,
        "deploy_commit_txt": (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0],
        "attempts": [],
    }
    observed = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"]
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        goto_and_wake(page, URL, timeout_s=240)
        t0 = time.time()
        clicked_sidebar = False
        for i in range(36):
            if is_app_asleep(all_frames_text(page)):
                wake_streamlit_app(page)
            html = page.content()
            text = all_frames_text(page)
            sha = scrape_deploy_sha_from_page(page) or sha_from_html(html)
            hits = {c: c in html.lower() for c in CAND}
            ldr = "start new live draft" in text.lower()
            row = {
                "i": i + 1,
                "elapsed_s": round(time.time() - t0, 1),
                "sha": sha,
                "includes_isolation_build": includes_isolation(sha),
                "ldr_setup_ui": ldr,
                "html_hits": hits,
                "text_len": len(text),
            }
            report["attempts"].append(row)
            if sha:
                observed = sha
                break
            if i == 8 and not ldr and not clicked_sidebar:
                clicked_sidebar = bool(
                    page.evaluate(
                        """() => {
                          function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
                          for (const root of roots()) {
                            for (const el of root.querySelectorAll('[data-testid=\"stSidebar\"] *, label, p, span')) {
                              const t = String(el.innerText || '').trim();
                              if (t === 'Live Draft Room') { el.click(); return true; }
                            }
                          }
                          return false;
                        }"""
                    )
                )
                row["sidebar_click"] = clicked_sidebar
            page.wait_for_timeout(5000)
        browser.close()

    report["observed_sha"] = observed
    report["includes_isolation_build"] = includes_isolation(observed)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("origin_dev", "observed_sha", "includes_isolation_build")}, indent=2))
    print("artifact", OUT)
    return 0 if report["includes_isolation_build"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
