"""One-shot Cloud deploy HTML scrape."""
from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/~/+/?active_page=Live%20Draft%20Room"
OUT = Path(__file__).resolve().parent.parent / "data" / "cloud_deploy_scrape.json"
CANDIDATES = ("44092f7", "8be8a78", "eb31631", "265d2bf", "9c5fa0c", "77c10b7", "093d86e", "c875735")


def main() -> None:
    result: dict = {"url": URL, "found": {}, "probe": None, "comment": None}
    with sync_playwright() as p:
        page = p.chromium.launch(headless=True).new_page(viewport={"width": 1440, "height": 1200})
        page.goto(URL, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(20000)
        html = page.content()
        text = page.inner_text("body", timeout=30000)
        result["probe"] = page.evaluate(
            """() => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              for (const root of roots()) {
                const el = root.querySelector('#solo-deploy-build');
                if (el) return {sha: el.getAttribute('data-sha'), build: el.getAttribute('data-build'), where: 'dom'};
                const h = root.documentElement ? root.documentElement.innerHTML : '';
                const m = h.match(/solo-deploy-build sha=([0-9a-f]{7})/i);
                if (m) return {sha: m[1], build: '', where: 'comment'};
              }
              return null;
            }"""
        )
        m = re.search(r"solo-deploy-build sha=([0-9a-f]{7})", html, re.I)
        result["comment"] = m.group(1).lower() if m else None
        for sha in CANDIDATES:
            result["found"][sha] = sha in html.lower() or sha in text.lower()
        page.close()
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
