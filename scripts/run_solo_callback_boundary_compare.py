"""Anonymous vs authenticated short A0 runs with callback-boundary forensics."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "solo_callback_boundary_compare.json"
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"


def _signed_in_probe_js() -> str:
    return """() => {
      const text = document.body ? document.body.innerText : '';
      return {
        signed_in_caption: /Signed in as/i.test(text),
        sign_in_gate: /Sign in to continue/i.test(text),
        log_in_tab: /Log in/i.test(text),
      };
    }"""


def cloud_login(page) -> dict[str, Any]:
    """Sign in via Real Accounts form when SOLO_AUTH_EMAIL/PASSWORD are set."""
    email = os.environ.get("SOLO_AUTH_EMAIL", "").strip()
    password = os.environ.get("SOLO_AUTH_PASSWORD", "").strip()
    storage = os.environ.get("SOLO_AUTH_STORAGE_STATE", "").strip()
    if storage:
        return {"ok": True, "method": "storage_state", "path": storage, "note": "load via context"}
    if not email or not password:
        return {
            "ok": False,
            "skipped": True,
            "reason": "Set SOLO_AUTH_EMAIL and SOLO_AUTH_PASSWORD (or SOLO_AUTH_STORAGE_STATE) for authenticated test",
        }
    from cloud_streamlit_wake import goto_and_wake

    goto_and_wake(page, BASE + "/?active_page=Live%20Draft%20Room", timeout_s=180)
    probe = page.evaluate(_signed_in_probe_js())
    if probe.get("signed_in_caption"):
        return {"ok": True, "method": "already_signed_in", "probe": probe}
    try:
        page.get_by_text("Log in", exact=False).first.click(timeout=8000)
    except Exception:
        pass
    try:
        page.get_by_label("Email").first.fill(email, timeout=8000)
        page.get_by_label("Password").first.fill(password, timeout=8000)
        page.get_by_role("button", name="Log in").first.click(timeout=8000)
    except Exception as exc:
        return {"ok": False, "error": f"login_ui:{type(exc).__name__}:{exc}", "probe": probe}
    page.wait_for_timeout(6000)
    probe2 = page.evaluate(_signed_in_probe_js())
    return {
        "ok": bool(probe2.get("signed_in_caption")),
        "method": "email_password",
        "probe_before": probe,
        "probe_after": probe2,
    }


def _summarize_boundary(a0: dict[str, Any]) -> dict[str, Any]:
    cb = a0.get("callback_boundary") or {}
    rows = cb.get("rows") if isinstance(cb, dict) else []
    if not isinstance(rows, list):
        rows = []
    entry = a0.get("callback_boundary_expiration_entry") or {}
    first_loss = a0.get("callback_boundary_first_disappearance")
    script_pair = a0.get("callback_boundary_script_begin_after_callback")
    auth_at_entry = {
        "authenticated": entry.get("authenticated") if isinstance(entry, dict) else None,
        "auth_enabled": entry.get("auth_enabled") if isinstance(entry, dict) else None,
        "restore_block_reason": entry.get("restore_block_reason") if isinstance(entry, dict) else "",
        "restore_blocked_reason": entry.get("restore_blocked_reason") if isinstance(entry, dict) else "",
        "room_present": entry.get("live_draft_room_present") if isinstance(entry, dict) else None,
        "room_id": entry.get("live_draft_room_id") if isinstance(entry, dict) else "",
    }
    interpretation = ""
    if isinstance(entry, dict) and entry.get("live_draft_room_present") is False:
        interpretation = "room_absent_at_callback_entry"
    elif first_loss:
        prior = (first_loss.get("prior") or {}) if isinstance(first_loss, dict) else {}
        absent = (first_loss.get("first_absent") or {}) if isinstance(first_loss, dict) else {}
        interpretation = (
            f"room_lost_at:{absent.get('point')}|after:{prior.get('point')}"
        )
    elif isinstance(script_pair, dict):
        prior = script_pair.get("prior") or {}
        if prior.get("live_draft_room_present") and not (script_pair.get("script_begin") or {}).get(
            "live_draft_room_present"
        ):
            interpretation = "room_present_at_callback_return_absent_at_script_begin"
    return {
        "interpretation": interpretation,
        "room_at_callback_entry": auth_at_entry,
        "first_disappearance": first_loss,
        "script_begin_after_callback": script_pair,
        "boundary_row_count": len(rows),
        "boundary_tail": rows[-12:] if rows else [],
    }


def run_scenario(*, authenticated: bool) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright
    from run_solo_bridge_transition_a0_only import run_a0
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks

    ws_frames: list[dict[str, Any]] = []
    login_meta: dict[str, Any] = {"authenticated_requested": authenticated}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        storage = os.environ.get("SOLO_AUTH_STORAGE_STATE", "").strip()
        if authenticated and storage and Path(storage).is_file():
            context = browser.new_context(
                viewport={"width": 1440, "height": 1400},
                storage_state=storage,
            )
        else:
            context = browser.new_context(viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        install_ws_and_postmessage_hooks(page, ws_frames)
        if authenticated:
            login_meta = cloud_login(page)
            if not login_meta.get("ok") and not login_meta.get("skipped"):
                context.close()
                browser.close()
                return {"login": login_meta, "skipped_run": True}
            if login_meta.get("skipped"):
                context.close()
                browser.close()
                return {"login": login_meta, "skipped_run": True}
        else:
            login_meta = {"ok": True, "method": "anonymous_headless"}
        a0 = run_a0(page, ws_frames)
        context.close()
        browser.close()
    summary = _summarize_boundary(a0)
    return {
        "login": login_meta,
        "a0": a0,
        "boundary_summary": summary,
    }


def main() -> int:
    report: dict[str, Any] = {
        "started_at": time.time(),
        "deploy_note": "requires callback boundary diag on Cloud",
    }
    report["anonymous"] = run_scenario(authenticated=False)
    report["authenticated"] = run_scenario(authenticated=True)
    report["finished_at"] = time.time()
    report["comparison"] = {
        "anonymous_room_loss": report["anonymous"].get("a0", {}).get("python_truly_lost_room"),
        "authenticated_room_loss": (
            None
            if report["authenticated"].get("skipped_run")
            else report["authenticated"].get("a0", {}).get("python_truly_lost_room")
        ),
        "anonymous_interpretation": report["anonymous"].get("boundary_summary", {}).get("interpretation"),
        "authenticated_interpretation": report["authenticated"].get("boundary_summary", {}).get(
            "interpretation"
        ),
        "auth_test_skipped": bool(report["authenticated"].get("skipped_run")),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "comparison": report["comparison"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
