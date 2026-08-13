"""Save Playwright storage after manual sign-in in a headed browser (no env password)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "playwright_daniel_auth.storage.json"
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
WAIT_S = int(os.environ.get("SOLO_AUTH_MANUAL_WAIT_S", "600"))


def _signed_in(page) -> bool:
    text = page.evaluate(_roots_js())
    return "Signed in as" in text


def _workspace_hint(page) -> str:
    text = page.evaluate(_roots_js())
    import re

    m = re.search(r"Workspace[:\\s]+([A-Za-z0-9_-]+)", text, re.I)
    if m:
        return m.group(1)[:40]
    m = re.search(r"Active workspace[:\\s]+([A-Za-z0-9_-]+)", text, re.I)
    return (m.group(1) if m else "")[:40]


def _roots_js() -> str:
    return """
    () => {
      const roots = [document];
      for (const f of document.querySelectorAll('iframe')) {
        try { if (f.contentDocument) roots.push(f.contentDocument); } catch (e) {}
      }
      return roots.map(r => (r.body && r.body.innerText) || '').join('\\n');
    }
    """


def main() -> int:
    out = Path(os.environ.get("SOLO_AUTH_STORAGE_STATE", str(DEFAULT_OUT)))
    SCRIPTS = Path(__file__).resolve().parent
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))

    from playwright.sync_api import sync_playwright

    from cloud_streamlit_wake import goto_and_wake

    print(
        "Opening Baseball dev app in a headed browser. Sign in to the Daniel account, then wait.",
        flush=True,
    )
    authenticated = False
    workspace_hint = ""
    storage_created = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        goto_and_wake(
            page,
            f"{BASE}/?active_page=Live%20Draft%20Room",
            timeout_s=240,
        )
        deadline = time.time() + WAIT_S
        while time.time() < deadline:
            if _signed_in(page):
                authenticated = True
                workspace_hint = _workspace_hint(page)
                break
            page.wait_for_timeout(1500)
        if authenticated:
            out.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(out))
            storage_created = True
        context.close()
        browser.close()

    print(
        json.dumps(
            {
                "authenticated": authenticated,
                "workspace_hint": workspace_hint or None,
                "storage_created": storage_created,
            }
        )
    )
    return 0 if authenticated and storage_created else 1


if __name__ == "__main__":
    raise SystemExit(main())
