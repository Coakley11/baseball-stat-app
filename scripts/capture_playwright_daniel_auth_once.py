"""One-shot headed capture: Playwright storage + suite_sid (no retries, single window)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from playwright_daniel_auth_session import STORAGE_PATH, save_session  # noqa: E402

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
START_URL = f"{BASE}/?active_page=Live%20Draft%20Room"
WAIT_S = int(__import__("os").environ.get("SOLO_AUTH_MANUAL_WAIT_S", "900"))


def _body_text(page) -> str:
    return page.evaluate(
        """() => {
      const roots = [document];
      for (const f of document.querySelectorAll('iframe')) {
        try { if (f.contentDocument) roots.push(f.contentDocument); } catch (e) {}
      }
      return roots.map(r => (r.body && r.body.innerText) || '').join('\\n');
    }"""
    )


def _suite_sid_from_url(url: str) -> str:
    try:
        q = parse_qs(urlparse(url).query)
        return str(q.get("suite_sid", [""])[0] or "").strip()
    except Exception:
        return ""


def _authenticated_from_diag(page) -> bool | None:
    diag_url = (
        f"{BASE}/?active_page=Live%20Draft%20Room"
        f"&solo_delivery_diag=1&solo_bridge_transition=A0&solo_component_diag=1"
    )
    sid = _suite_sid_from_url(page.url)
    if sid:
        diag_url += f"&suite_sid={sid}"
    try:
        from cloud_streamlit_wake import goto_and_wake

        goto_and_wake(page, diag_url, timeout_s=240)
        page.wait_for_timeout(12000)
    except Exception:
        return None
    try:
        b64 = page.evaluate(
            """() => {
          function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) {
            try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
          for (const root of roots()) {
            const el = root.querySelector('#solo-paired-transition-diag');
            if (el) return el.getAttribute('data-paired-transition-b64') || '';
          }
          return '';
        }"""
        )
        if not b64:
            return None
        import base64

        raw = base64.b64decode(b64 + "==="[: (4 - len(b64) % 4) % 4])
        payload = json.loads(raw.decode("utf-8"))
        rows = payload.get("rows") or []
        if isinstance(rows, list) and rows:
            last = rows[-1]
            if isinstance(last, dict) and "authenticated" in last:
                return bool(last.get("authenticated"))
    except Exception:
        return None
    return None


def main() -> int:
    from playwright.sync_api import sync_playwright

    from cloud_streamlit_wake import goto_and_wake

    failure = ""
    signed_in_display = False
    authenticated_app: bool | None = None
    suite_sid_captured = False
    storage_saved = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        print("Single headed window open. Sign in to the Daniel account, then wait.", flush=True)
        goto_and_wake(page, START_URL, timeout_s=240)
        deadline = time.time() + WAIT_S
        while time.time() < deadline:
            text = _body_text(page)
            signed_in_display = "Signed in as" in text
            sid = _suite_sid_from_url(page.url)
            if signed_in_display and sid:
                break
            page.wait_for_timeout(1200)
        else:
            failure = "timeout_before_signed_in_and_suite_sid"
            context.close()
            browser.close()
            print(
                json.dumps(
                    {
                        "ok": False,
                        "failure": failure,
                        "signed_in_display": signed_in_display,
                        "suite_sid_captured": False,
                        "storage_saved": False,
                    }
                )
            )
            return 1

        sid = _suite_sid_from_url(page.url)
        if not sid:
            failure = "suite_sid_missing_from_url_after_sign_in"
            context.close()
            browser.close()
            print(
                json.dumps(
                    {
                        "ok": False,
                        "failure": failure,
                        "signed_in_display": signed_in_display,
                        "suite_sid_captured": False,
                        "storage_saved": False,
                    }
                )
            )
            return 1

        authenticated_app = _authenticated_from_diag(page)
        if authenticated_app is not True:
            if authenticated_app is False:
                failure = "authenticated_false_in_app_probe"
            else:
                text = _body_text(page)
                if "Not signed in" in text:
                    failure = "not_signed_in_visible_in_app"
                    authenticated_app = False
                elif signed_in_display:
                    authenticated_app = True
                else:
                    failure = "authenticated_probe_unavailable"
            if failure:
                context.close()
                browser.close()
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "failure": failure,
                            "signed_in_display": signed_in_display,
                            "authenticated_app": authenticated_app,
                            "suite_sid_captured": False,
                            "storage_saved": False,
                        }
                    )
                )
                return 1

        STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(STORAGE_PATH))
        storage_saved = STORAGE_PATH.is_file()
        save_session(suite_sid=sid)
        suite_sid_captured = True
        context.close()
        browser.close()

    print(
        json.dumps(
            {
                "ok": True,
                "signed_in_display": signed_in_display,
                "authenticated_app": authenticated_app is True,
                "suite_sid_captured": suite_sid_captured,
                "storage_saved": storage_saved,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
