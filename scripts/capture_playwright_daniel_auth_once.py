"""One-shot headed capture: strict Cloud auth proof before writing harness files."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from playwright_auth_capture_diag import (  # noqa: E402
    RESULT_PATH,
    CaptureTraceCollector,
    TRACE_ROOT,
    build_failure_payload,
    classify_auth_login,
    extract_identity_from_ledger,
    is_cloud_app_url,
    is_oauth_callback_url,
    is_provider_url,
    ledger_login_timeline,
    login_transition_state,
    new_run_identity,
    probe_storage_booleans,
    save_trace_bundle,
    verify_capture_url,
    write_result_artifact,
)
from playwright_auth_capture_strict import evaluate_strict_capture  # noqa: E402
from playwright_auth_preflight_strict import inspect_start_control, paired_transition_authenticated, suite_sid_from_url  # noqa: E402
from playwright_daniel_auth_session import (  # noqa: E402
    SESSION_PATH,
    STORAGE_PATH,
    append_suite_sid_to_url,
    atomic_write_harness_files,
    utc_capture_timestamp,
)

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
            "readback_succeeded": bool(bp.get("readback_succeeded")),
            "suite_sid_prefix_match": bool(bp.get("suite_sid_prefix_match")),
            "access_token_present": bool(bp.get("access_token_present")),
            "refresh_token_present": bool(bp.get("refresh_token_present")),
            "auth_user_id_present": bool(bp.get("auth_user_id_present")),
            "bridge_record_complete": bool(bp.get("bridge_record_complete")),
            "failure_reason": str(bp.get("failure_reason") or "")[:80],
        },
    }


def _finalize_exit(
    *,
    code: int,
    identity: dict[str, Any],
    failure: str,
    page,
    collector: CaptureTraceCollector,
    ledger_rows: list[dict[str, Any]],
    strict_capture: dict[str, Any] | None,
    files_updated: bool,
    sid_drift: bool = False,
    timeout_before_sign_in: bool = False,
    screenshot_phase: str = "timeout",
    extra_stdout: dict[str, Any] | None = None,
    skip_trace: bool = False,
) -> int:
    url = page.url or ""
    identity["final_browser_url"] = url[:512]
    identity.update(extract_identity_from_ledger(ledger_rows))
    storage = probe_storage_booleans(page)
    url_sid = suite_sid_from_url(url)
    login_state = login_transition_state(
        target_sid=str(identity.get("suite_sid") or ""),
        url_sid=url_sid,
        provider_seen=bool(identity.get("provider_login_seen")),
        oauth_callback_seen=bool(identity.get("oauth_callback_seen")),
        returned_to_app=is_cloud_app_url(url),
        storage=storage,
        signed_in_display=bool(identity.get("signed_in_display")),
        ledger_rows=ledger_rows,
        strict_failure=failure,
    )
    auth_class = classify_auth_login(
        login_state,
        sid_drift=sid_drift,
        timeout_before_sign_in=timeout_before_sign_in,
    )
    trace_meta: dict[str, Any] = {}
    if not skip_trace:
        trace_dir = TRACE_ROOT / f"{identity.get('suite_sid_prefix') or 'unknown'}_{int(time.time())}"
        trace_meta = save_trace_bundle(
            trace_dir=trace_dir,
            page=page,
            identity=identity,
            storage_probe=storage,
            collector=collector,
            ledger_rows=ledger_rows,
            screenshot_labels=[(screenshot_phase, None)],
        )
    payload = build_failure_payload(
        identity=identity,
        failure=failure,
        strict_capture=_public_summary(strict_capture) if strict_capture else None,
        login_state=login_state,
        auth_login_class=auth_class if code != 0 else "",
        trace_meta=trace_meta,
        files_updated=files_updated,
    )
    payload["login_timeline"] = ledger_login_timeline(ledger_rows)
    payload["capture_url_check"] = verify_capture_url(
        str(identity.get("target_url") or ""), expected_sid=str(identity.get("suite_sid") or "")
    )
    artifact = write_result_artifact(payload if code != 0 else {**payload, "ok": True, "failure": ""})
    stdout: dict[str, Any] = {
        "ok": code == 0,
        "failure": failure if code != 0 else "",
        "suite_sid": identity.get("suite_sid"),
        "suite_sid_prefix": identity.get("suite_sid_prefix"),
        "files_updated": files_updated,
        "auth_login_classification": auth_class if code != 0 else "",
        "first_missing_login_transition": login_state.get("first_missing_transition"),
        "bridge_save_attempted": login_state.get("bridge_save_attempted"),
        "bridge_readback_attempted": login_state.get("bridge_readback_attempted"),
        "artifact": str(artifact),
        "trace_dir": trace_meta.get("trace_dir"),
    }
    if extra_stdout:
        stdout.update(extra_stdout)
    stdout["strict_capture"] = _public_summary(strict_capture or {})
    print(json.dumps(stdout, default=str))
    return code


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from p8_production_start_harness import scrape_stage1_ledger_rows
    from playwright.sync_api import sync_playwright
    from queueui_audit_protocol import scrape_deploy_marker_from_page

    reuse = str(os.environ.get("CAPTURE_SUITE_SID") or "").strip()
    target_sid = reuse if reuse else str(uuid.uuid4())
    start_url = _capture_url(target_sid)
    identity = new_run_identity(suite_sid=target_sid, target_url=start_url)
    identity["capture_url_check"] = verify_capture_url(start_url, expected_sid=target_sid)
    write_result_artifact({**identity, "phase": "started"})

    storage_mtime_before = STORAGE_PATH.stat().st_mtime if STORAGE_PATH.is_file() else 0.0
    session_mtime_before = SESSION_PATH.stat().st_mtime if SESSION_PATH.is_file() else 0.0

    _status("waiting for normal sign-in (headed window opening)")
    _status(f"suite_sid={target_sid}")

    collector = CaptureTraceCollector()
    last_eval: dict[str, Any] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        collector.attach(page)
        goto_and_wake(page, start_url, timeout_s=240)
        collector.note_url(page.url or "", label="initial_load")
        TRACE_ROOT.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(TRACE_ROOT / f"{target_sid[:8]}_login_start.png"))
        except Exception:
            pass

        deadline = time.time() + WAIT_S
        while time.time() < deadline:
            url = page.url or ""
            collector.note_url(url)
            if is_provider_url(url):
                if not identity["provider_login_seen"]:
                    _status("provider login detected")
                    identity["provider_login_seen"] = True
                    try:
                        page.screenshot(path=str(TRACE_ROOT / f"{target_sid[:8]}_provider_login.png"))
                    except Exception:
                        pass
            if is_oauth_callback_url(url) or (identity["provider_login_seen"] and is_cloud_app_url(url)):
                identity["oauth_callback_seen"] = True
                try:
                    page.screenshot(path=str(TRACE_ROOT / f"{target_sid[:8]}_callback_return.png"))
                except Exception:
                    pass
            signed_in_display = "Signed in as" in _body_text(page)
            identity["signed_in_display"] = signed_in_display
            url_sid = suite_sid_from_url(url)
            if url_sid and url_sid != target_sid:
                ledger = scrape_stage1_ledger_rows(page) or []
                code = _finalize_exit(
                    code=1,
                    identity=identity,
                    failure="suite_sid_changed",
                    page=page,
                    collector=collector,
                    ledger_rows=ledger,
                    strict_capture=None,
                    files_updated=False,
                    sid_drift=True,
                    screenshot_phase="sid_drift",
                    extra_stdout={"url_sid": url_sid},
                )
                context.close()
                browser.close()
                return code
            if signed_in_display and url_sid == target_sid:
                _status("waiting for Streamlit hydration")
                try:
                    page.screenshot(path=str(TRACE_ROOT / f"{target_sid[:8]}_hydration_wait.png"))
                except Exception:
                    pass
                break
            page.wait_for_timeout(1200)
        else:
            ledger = scrape_stage1_ledger_rows(page) or []
            identity["cloud_runtime_sha"] = (scrape_deploy_marker_from_page(page)[0] or "")
            code = _finalize_exit(
                code=1,
                identity=identity,
                failure="timeout_before_signed_in_and_stable_sid",
                page=page,
                collector=collector,
                ledger_rows=ledger,
                strict_capture=None,
                files_updated=False,
                timeout_before_sign_in=True,
                screenshot_phase="timeout_sign_in",
            )
            context.close()
            browser.close()
            return code

        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(3000)
        except Exception:
            pass

        _status("waiting for bridge persistence / strict auth")
        while time.time() < deadline:
            url_sid = suite_sid_from_url(page.url or "")
            collector.note_url(page.url or "")
            if url_sid and url_sid != target_sid:
                ledger = scrape_stage1_ledger_rows(page) or []
                code = _finalize_exit(
                    code=1,
                    identity=identity,
                    failure="suite_sid_changed",
                    page=page,
                    collector=collector,
                    ledger_rows=ledger,
                    strict_capture=last_eval or None,
                    files_updated=False,
                    sid_drift=True,
                    screenshot_phase="sid_drift_hydration",
                )
                context.close()
                browser.close()
                return code
            last_eval = _strict_poll(page, target_sid=target_sid, scrape_ledger=scrape_stage1_ledger_rows)
            if last_eval.get("strict_auth_passed"):
                break
            page.wait_for_timeout(POLL_MS)
            try:
                goto_and_wake(page, _capture_url(target_sid), timeout_s=120)
            except Exception:
                pass
        else:
            ledger = scrape_stage1_ledger_rows(page) or []
            identity["cloud_runtime_sha"] = (scrape_deploy_marker_from_page(page)[0] or "")
            code = _finalize_exit(
                code=1,
                identity=identity,
                failure=str(last_eval.get("failure") or "timeout_strict_capture"),
                page=page,
                collector=collector,
                ledger_rows=ledger,
                strict_capture=last_eval,
                files_updated=False,
                screenshot_phase="timeout_hydration",
            )
            context.close()
            browser.close()
            return code

        if not last_eval.get("strict_auth_passed"):
            ledger = scrape_stage1_ledger_rows(page) or []
            identity["cloud_runtime_sha"] = (scrape_deploy_marker_from_page(page)[0] or "")
            code = _finalize_exit(
                code=1,
                identity=identity,
                failure=str(last_eval.get("failure") or "strict_capture_incomplete"),
                page=page,
                collector=collector,
                ledger_rows=ledger,
                strict_capture=last_eval,
                files_updated=False,
                screenshot_phase="strict_incomplete",
            )
            context.close()
            browser.close()
            return code

        live_sha, _src = scrape_deploy_marker_from_page(page)
        identity["cloud_runtime_sha"] = live_sha or ""
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
        files_updated = (
            STORAGE_PATH.is_file()
            and SESSION_PATH.is_file()
            and STORAGE_PATH.stat().st_mtime > storage_mtime_before
            and SESSION_PATH.stat().st_mtime > session_mtime_before
        )
        ledger = scrape_stage1_ledger_rows(page) or []
        identity["files_updated"] = files_updated
        identity["ok"] = True
        storage = probe_storage_booleans(page)
        login_state = login_transition_state(
            target_sid=target_sid,
            url_sid=suite_sid_from_url(page.url or ""),
            provider_seen=bool(identity.get("provider_login_seen")),
            oauth_callback_seen=bool(identity.get("oauth_callback_seen")),
            returned_to_app=True,
            storage=storage,
            signed_in_display=True,
            ledger_rows=ledger,
            strict_failure="",
        )
        trace_dir = TRACE_ROOT / f"{target_sid[:8]}_{int(time.time())}_success"
        trace_meta = save_trace_bundle(
            trace_dir=trace_dir,
            page=page,
            identity=identity,
            storage_probe=storage,
            collector=collector,
            ledger_rows=ledger,
            screenshot_labels=[("success", None)],
        )
        success_payload = {
            **identity,
            "capture_ended_at": utc_capture_timestamp(),
            "failure": "",
            "strict_capture": _public_summary(last_eval),
            "login_boundary": login_state,
            "login_timeline": ledger_login_timeline(ledger),
            "trace": trace_meta,
            "ok": True,
            "files_updated": files_updated,
        }
        write_result_artifact(success_payload)
        stdout = {
            "ok": True,
            "suite_sid": target_sid,
            "files_updated": files_updated,
            "cloud_runtime_sha": live_sha,
            "artifact": str(RESULT_PATH),
            "trace_dir": trace_meta.get("trace_dir"),
            "strict_capture": _public_summary(last_eval),
        }
        print(json.dumps(stdout, default=str))
        context.close()
        browser.close()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
