"""One-time: save Playwright storage state for Daniel Real Account (env creds, not stored in repo)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "playwright_daniel_auth.storage.json"
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"


def main() -> int:
    out = Path(os.environ.get("SOLO_AUTH_STORAGE_STATE", str(DEFAULT_OUT)))
    if out.is_file():
        print(json.dumps({"ok": True, "already_exists": str(out)}))
        return 0
    email = os.environ.get("SOLO_AUTH_EMAIL", "").strip()
    password = os.environ.get("SOLO_AUTH_PASSWORD", "").strip()
    if not email or not password:
        print(
            "Set SOLO_AUTH_EMAIL and SOLO_AUTH_PASSWORD in the environment, then re-run.",
            file=sys.stderr,
        )
        return 2
    from playwright.sync_api import sync_playwright

    from cloud_streamlit_wake import goto_and_wake

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        goto_and_wake(page, BASE, timeout_s=180)
        try:
            page.get_by_text("Log in", exact=False).first.click(timeout=8000)
        except Exception:
            pass
        page.get_by_label("Email").first.fill(email, timeout=15000)
        page.get_by_label("Password").first.fill(password, timeout=15000)
        page.get_by_role("button", name="Log in").first.click(timeout=15000)
        page.wait_for_timeout(8000)
        signed_in = page.evaluate(
            "() => /Signed in as/i.test(document.body ? document.body.innerText : '')"
        )
        if not signed_in:
            print("Login did not reach Signed in state.", file=sys.stderr)
            context.close()
            browser.close()
            return 3
        out.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(out))
        context.close()
        browser.close()
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
