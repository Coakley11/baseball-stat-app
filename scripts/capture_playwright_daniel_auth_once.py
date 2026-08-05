"""One-shot headed capture: strict Cloud auth proof before writing harness files."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from playwright_auth_capture_strict import evaluate_strict_capture  # noqa: E402
from playwright_auth_preflight_strict import inspect_start_control, paired_transition_authenticated, suite_sid_from_url  # noqa: E402
from playwright_daniel_auth_session import (  # noqa: E402
    SESSION_PATH,
    STORAGE_PATH,
    append_suite_sid_to_url,
    atomic_write_harness_files,
    utc_capture_timestamp,
)

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
WAIT_S = int(os.environ.get("SOLO_AUTH_MANUAL_WAIT_S", "900"))
POLL_MS = int(os.environ.get("CAPTURE_STRICT_POLL_MS", "3500"))


def _status(msg: str) -> None:
    print(f"[capture] {msg}", flush=True)


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


def _provider_login_url(url: str) -> bool:
    u = (url or "").lower()
    return any(x in u for x in ("accounts.google", "login.microsoftonline", "auth0.com", "supabase.co/auth"))


def _fail(
    *,
    failure: str,
    target_sid: str,
    files_updated: bool,
    extra: dict[str, Any] | None = None,
) -> int:
    payload: dict[str, Any] = {
        "ok": False,
        "failure": failure,
        "target_suite_sid_prefix": target_sid[:8] if target_sid else "",
        "files_updated": files_updated,
        "storage_saved": False,
        "strict_auth_passed": False,
        "bridge_persisted": False,
        "start_enabled": False,
    }
    if extra:
        payload.update(extra)
    print(json.dumps(payload))
    return 1


def _capture_url(target_sid: str) -> str:
    from queueui_audit_protocol import queueui_root_predicate_audit_url_base

    return append_suite_sid_to_url(queueui_root_predicate_audit_url_base(), target_sid)


def _strict_poll(page, *, target_sid: str, scrape_ledger) -> dict[str, Any]:
    from stage1_preflight_cleanup import _scrape_lobby

    ledger = scrape_ledger(page) or []
    url_sid = suite_sid_from_url(page.url or "")
    start = inspect_start_control(page)
    lobby = _scrape_lobby(page)
    if not start.get("visible") and lobby.get("has_start_new"):
        start["visible"] = True
    paired = paired_transition_authenticated(page)
    signed_in = "Signed in as" in _body_text(page)
    return evaluate_strict_capture(
        target_sid=target_sid,
        url_sid=url_sid,
        ledger_rows=ledger,
        start_enabled=bool(start.get("enabled")),
        start_visible=bool(start.get("visible")),
        paired_authenticated=paired,
        signed_in_display=signed_in,
    )


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from p8_production_start_harness import scrape_stage1_ledger_rows
    from playwright.sync_api import sync_playwright
    from queueui_audit_protocol import scrape_deploy_marker_from_page

    reuse = str(os.environ.get("CAPTURE_SUITE_SID") or "").strip()
    if reuse:
        target_sid = reuse
    else:
        target_sid = str(uuid.uuid4())

    storage_mtime_before = STORAGE_PATH.stat().st_mtime if STORAGE_PATH.is_file() else 0.0
    session_mtime_before = SESSION_PATH.stat().st_mtime if SESSION_PATH.is_file() else 0.0
    start_url = _capture_url(target_sid)

    _status("waiting for normal sign-in (headed window opening)")
    _status(f"deterministic suite_sid prefix={target_sid[:8]}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        goto_and_wake(page, start_url, timeout_s=240)

        deadline = time.time() + WAIT_S
        provider_seen = False
        signed_in_display = False
        while time.time() < deadline:
            url = page.url or ""
            if _provider_login_url(url):
                if not provider_seen:
                    _status("provider login detected")
                    provider_seen = True
            text = _body_text(page)
            signed_in_display = "Signed in as" in text
            url_sid = suite_sid_from_url(url)
            if url_sid and url_sid != target_sid:
                context.close()
                browser.close()
                return _fail(
                    failure="suite_sid_changed",
                    target_sid=target_sid,
                    files_updated=False,
                    extra={"url_sid_prefix": url_sid[:8]},
                )
            if signed_in_display and url_sid == target_sid:
                _status("waiting for Streamlit hydration")
                break
            page.wait_for_timeout(1200)
        else:
            context.close()
            browser.close()
            return _fail(
                failure="timeout_before_signed_in_and_stable_sid",
                target_sid=target_sid,
                files_updated=False,
                extra={"signed_in_display": signed_in_display},
            )

        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(3000)
        except Exception:
            pass

        _status("waiting for bridge persistence")
        last_eval: dict[str, Any] = {}
        while time.time() < deadline:
            url_sid = suite_sid_from_url(page.url or "")
            if url_sid and url_sid != target_sid:
                context.close()
                browser.close()
                return _fail(
                    failure="suite_sid_changed",
                    target_sid=target_sid,
                    files_updated=False,
                )
            last_eval = _strict_poll(page, target_sid=target_sid, scrape_ledger=scrape_stage1_ledger_rows)
            if last_eval.get("bridge_persisted"):
                _status("waiting for Start enablement")
            if last_eval.get("strict_auth_passed"):
                break
            if last_eval.get("start_enabled") is False and last_eval.get("bridge_persisted"):
                _status("waiting for Start enablement")
            page.wait_for_timeout(POLL_MS)
            try:
                goto_and_wake(page, _capture_url(target_sid), timeout_s=120)
            except Exception:
                pass
        else:
            context.close()
            browser.close()
            return _fail(
                failure=str(last_eval.get("failure") or "timeout_strict_capture"),
                target_sid=target_sid,
                files_updated=False,
                extra={"strict_capture": _public_summary(last_eval)},
            )

        if not last_eval.get("strict_auth_passed"):
            context.close()
            browser.close()
            return _fail(
                failure=str(last_eval.get("failure") or "strict_capture_incomplete"),
                target_sid=target_sid,
                files_updated=False,
                extra={"strict_capture": _public_summary(last_eval)},
            )

        live_sha, _src = scrape_deploy_marker_from_page(page)
        _status("strict capture passed — saving files")

        def _write_storage(path: Path) -> None:
            context.storage_state(path=str(path))

        meta = {
            "captured_at": utc_capture_timestamp(),
            "cloud_runtime_sha": live_sha or "",
            "strict_auth_passed": True,
            "bridge_persisted": True,
            "start_enabled": bool(last_eval.get("start_enabled")),
            "strict_capture": _public_summary(last_eval),
        }
        atomic_write_harness_files(
            suite_sid=target_sid,
            storage_writer=_write_storage,
            capture_metadata=meta,
        )
        context.close()
        browser.close()

    files_updated = (
        STORAGE_PATH.is_file()
        and SESSION_PATH.is_file()
        and STORAGE_PATH.stat().st_mtime > storage_mtime_before
        and SESSION_PATH.stat().st_mtime > session_mtime_before
    )
    _status("files saved")
    print(
        json.dumps(
            {
                "ok": True,
                "target_suite_sid_prefix": target_sid[:8],
                "files_updated": files_updated,
                "storage_saved": STORAGE_PATH.is_file(),
                "strict_auth_passed": True,
                "bridge_persisted": True,
                "start_enabled": bool(last_eval.get("start_enabled")),
                "cloud_runtime_sha": meta.get("cloud_runtime_sha"),
                "strict_capture": _public_summary(last_eval),
            }
        )
    )
    return 0


def _public_summary(ev: dict[str, Any]) -> dict[str, Any]:
    bp = ev.get("bridge_persistence") if isinstance(ev.get("bridge_persistence"), dict) else {}
    return {
        "sid_stable": bool(ev.get("sid_stable")),
        "bridge_lookup": ev.get("bridge_lookup"),
        "apply_authenticated_user_ok": bool(ev.get("apply_authenticated_user_ok")),
        "session_flag_present": bool(ev.get("session_flag_present")),
        "is_authenticated": bool(ev.get("is_authenticated")),
        "auth_session_complete": bool(ev.get("auth_session_complete")),
        "start_enabled": bool(ev.get("start_enabled")),
        "restore_blocked_reason": str(ev.get("restore_blocked_reason") or "")[:80],
        "bridge_persistence": {
            "persistence_attempted": bool(bp.get("persistence_attempted")),
            "persistence_succeeded": bool(bp.get("persistence_succeeded")),
            "suite_sid_prefix_match": bool(bp.get("suite_sid_prefix_match")),
            "access_token_present": bool(bp.get("access_token_present")),
            "refresh_token_present": bool(bp.get("refresh_token_present")),
            "auth_user_id_present": bool(bp.get("auth_user_id_present")),
            "bridge_record_complete": bool(bp.get("bridge_record_complete")),
            "failure_reason": str(bp.get("failure_reason") or "")[:80],
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
