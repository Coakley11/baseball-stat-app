"""Request Streamlit Community Cloud dev app reboot (no deploy-nudge commit)."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

# baseball-stat-app dev — from share.streamlit.io app settings URL when available.
DEFAULT_APP_ID = os.environ.get("STREAMLIT_APP_ID", "").strip()
API = "https://api.streamlit.app/v1"


def reboot_app(app_id: str, *, token: str) -> dict:
    req = urllib.request.Request(
        f"{API}/apps/{app_id}/restart",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body) if body else {"ok": True}
    except json.JSONDecodeError:
        return {"ok": True, "raw": body[:500]}


def main() -> int:
    token = str(os.environ.get("STREAMLIT_API_TOKEN") or "").strip()
    app_id = DEFAULT_APP_ID or str(os.environ.get("STREAMLIT_BASEBALL_DEV_APP_ID") or "").strip()
    if not token or not app_id:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": "missing_credentials",
                    "hint": "Set STREAMLIT_API_TOKEN and STREAMLIT_APP_ID (or STREAMLIT_BASEBALL_DEV_APP_ID), "
                    "or reboot manually: share.streamlit.io → baseball-stat-app → dev → Reboot app",
                },
                indent=2,
            )
        )
        return 2
    try:
        out = reboot_app(app_id, token=token)
        print(json.dumps({"ok": True, "app_id": app_id, "response": out}, indent=2))
        return 0
    except urllib.error.HTTPError as exc:
        print(json.dumps({"ok": False, "http_status": exc.code, "body": exc.read().decode()[:800]}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
