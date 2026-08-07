"""One-shot headed capture: strict Cloud auth proof before writing harness files."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
    infer_timeout_failure_phase,
    is_cloud_app_url,
    is_provider_url,
    ledger_login_timeline,
    login_transition_state,
    new_run_identity,
    probe_storage_booleans,
    save_trace_bundle,
    verify_capture_url,
    write_result_artifact,
)
from playwright_auth_surface_monitor import BrowserSurfaceMonitor  # noqa: E402
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


def _observability_package(
    page,
    *,
    harness_sid: str,
    ledger_rows: list[dict[str, Any]],
    strict_failure: str,
) -> dict[str, Any]:
    from playwright_auth_observability import gather_page_observability
    from playwright_auth_preflight_strict import paired_transition_authenticated
    from playwright_auth_strict_evidence import build_strict_auth_evidence

    obs = gather_page_observability(page, harness_sid=harness_sid, strict_failure=strict_failure)
    cp = obs.get("checkpoint") or {}
    ss = obs.get("start_surface") or {}
    rows = obs.get("ledger_rows_for_eval") or ledger_rows
    paired = paired_transition_authenticated(page)
    auth_evidence = build_strict_auth_evidence(
        harness_sid=harness_sid,
        url=str(page.url or ""),
        ledger_rows=rows,
        start_inspect={
            "visible": ss.get("visible"),
            "enabled": ss.get("enabled"),
        },
        paired_authenticated=paired,
        diagnostic_run_id=str(cp.get("diagnostic_run_id") or ""),
        streamlit_session_id=str(cp.get("streamlit_session_id") or ""),
    )
    binding = {
        "checkpoint": cp,
        "binding": obs.get("binding"),
        "ledger_bind": obs.get("ledger_bind"),
        "start_surface": ss,
        "session_binding_failure": obs.get("session_binding_failure"),
        "playwright_page_id": hex(id(page))[:14],
        "page_url": str(page.url or "")[:512],
        "auth_evidence": auth_evidence,
        "login_timeline": ledger_login_timeline(rows),
    }
    return {
        "observability_binding": binding,
        "auth_observability_classification": obs.get("auth_observability_classification") or "",
        "auth_observability_detail": obs.get("auth_observability_detail") or "",
        "override_failure": obs.get("override_failure") or "",
        "ledger_rows": rows,
    }


def _strict_poll(page, *, target_sid: str, scrape_ledger) -> dict[str, Any]:
    from stage1_preflight_cleanup import _scrape_lobby

    if page is None or page.is_closed():
        return {"strict_auth_passed": False, "failure": "browser_page_closed"}
    try:
        from playwright_auth_observability import gather_page_observability

        obs = gather_page_observability(page, harness_sid=target_sid, strict_failure="")
        ledger = obs.get("ledger_rows_for_eval") or scrape_ledger(page) or []
    except Exception as exc:
        if "TargetClosedError" in type(exc).__name__ or "closed" in str(exc).lower():
            return {"strict_auth_passed": False, "failure": "browser_page_closed"}
        ledger = scrape_ledger(page) or []
        obs = {}
    url_sid = suite_sid_from_url(page.url or "")
    try:
        start = inspect_start_control(page)
        lobby = _scrape_lobby(page)
        if not start.get("visible") and lobby.get("has_start_new"):
            start["visible"] = True
        paired = paired_transition_authenticated(page)
        signed_in = "Signed in as" in _body_text(page)
    except Exception as exc:
        if "TargetClosedError" in type(exc).__name__ or "closed" in str(exc).lower():
            return {"strict_auth_passed": False, "failure": "browser_page_closed"}
        raise
    ev = evaluate_strict_capture(
        target_sid=target_sid,
        url_sid=url_sid,
        ledger_rows=ledger,
        start_enabled=bool(start.get("enabled")),
        start_visible=bool(start.get("visible")),
        paired_authenticated=paired,
        signed_in_display=signed_in,
        current_auth_dom=(obs.get("checkpoint") or {}).get("current_auth_dom")
        if obs
        else None,
        diagnostic_run_id=str((obs.get("checkpoint") or {}).get("diagnostic_run_id") or "")[:64]
        if obs
        else "",
        streamlit_session_id=str((obs.get("checkpoint") or {}).get("streamlit_session_id") or "")[:36]
        if obs
        else "",
    )
    if obs:
        from playwright_auth_observability import apply_observability_to_strict_summary

        ev = apply_observability_to_strict_summary(ev, obs)
        ev["_observability"] = {
            "binding": obs.get("binding"),
            "checkpoint": obs.get("checkpoint"),
            "start_surface": obs.get("start_surface"),
        }
    return ev


def _public_summary(ev: dict[str, Any]) -> dict[str, Any]:
    bp = ev.get("bridge_persistence") if isinstance(ev.get("bridge_persistence"), dict) else {}

    summary: dict[str, Any] = {
        "sid_stable": bool(ev.get("sid_stable")),
        "bridge_lookup": ev.get("bridge_lookup"),
        "apply_authenticated_user_ok": bool(ev.get("apply_authenticated_user_ok")),
        "session_flag_present": ev.get("session_flag_present"),
        "is_authenticated": ev.get("is_authenticated"),
        "auth_session_complete": ev.get("auth_session_complete"),
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
    if ev.get("auth_state_observability"):
        summary["auth_state_observability"] = ev.get("auth_state_observability")
    return summary


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
    browser_surfaces: dict[str, Any] | None = None,
    sign_in_initiated: bool = False,
    failure_phase: str = "",
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
        sign_in_initiated=sign_in_initiated or bool(identity.get("sign_in_initiated")),
    )
    if failure_phase:
        login_state["failure_phase"] = failure_phase
    elif code != 0:
        login_state["failure_phase"] = infer_timeout_failure_phase(login_state, strict_failure=failure)
    auth_class = classify_auth_login(
        login_state,
        sid_drift=sid_drift,
        timeout_before_sign_in=timeout_before_sign_in,
        start_enabled=bool((strict_capture or {}).get("start_enabled")),
    )
    auth_obs_class = ""
    auth_obs_detail = ""
    observability_binding: dict[str, Any] = {}
    if page is not None and not page.is_closed():
        try:
            pkg = _observability_package(
                page,
                harness_sid=str(identity.get("suite_sid") or ""),
                ledger_rows=ledger_rows,
                strict_failure=failure,
            )
            observability_binding = pkg["observability_binding"]
            ledger_rows = pkg.get("ledger_rows") or ledger_rows
            if pkg.get("override_failure"):
                failure = str(pkg["override_failure"])
            auth_obs_class = str(pkg.get("auth_observability_classification") or "")
            auth_obs_detail = str(pkg.get("auth_observability_detail") or "")
            if auth_obs_class and bool((strict_capture or {}).get("start_enabled")):
                auth_class = ""
                cp = observability_binding.get("checkpoint") or {}
                identity.update(
                    {
                        k: v
                        for k, v in cp.items()
                        if k in ("streamlit_session_id", "diagnostic_run_id", "deploy_sha")
                        and v
                    }
                )
        except Exception:
            pass
    auth_finalize_class = ""
    auth_finalize_detail = ""
    if failure in (
        "start_control_disabled",
        "streamlit_auth_incomplete",
        "strict_capture_incomplete",
        "auth_session_finalization_incomplete",
    ):
        try:
            from live_draft_auth_finalize_stage1_diag import classify_auth_finalize_from_ledger

            auth_finalize_class, auth_finalize_detail, _ev = classify_auth_finalize_from_ledger(ledger_rows)
        except ImportError:
            pass
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
            browser_surfaces=browser_surfaces,
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
    if auth_obs_class:
        payload["auth_observability_classification"] = auth_obs_class
        payload["auth_observability_detail"] = auth_obs_detail
        payload["auth_login_classification"] = ""
        payload["observability_binding"] = observability_binding
    payload["login_timeline"] = ledger_login_timeline(ledger_rows)
    payload["capture_url_check"] = verify_capture_url(
        str(identity.get("target_url") or ""), expected_sid=str(identity.get("suite_sid") or "")
    )
    if auth_finalize_class:
        payload["auth_session_finalization"] = auth_finalize_class
        payload["auth_finalize_detail"] = auth_finalize_detail
        identity["auth_login_classification"] = ""
    if strict_capture and strict_capture.get("auth_finalize_diag"):
        payload["auth_finalize_diag"] = strict_capture.get("auth_finalize_diag")
        payload["auth_finalize_diag_detail"] = strict_capture.get("auth_finalize_diag_detail")
    artifact = write_result_artifact(payload if code != 0 else {**payload, "ok": True, "failure": ""})
    stdout: dict[str, Any] = {
        "ok": code == 0,
        "failure": failure if code != 0 else "",
        "suite_sid": identity.get("suite_sid"),
        "suite_sid_prefix": identity.get("suite_sid_prefix"),
        "files_updated": files_updated,
        "auth_login_classification": auth_class if code != 0 and not auth_finalize_class and not auth_obs_class else "",
        "auth_observability_classification": auth_obs_class if code != 0 else "",
        "auth_observability_detail": auth_obs_detail if code != 0 else "",
        "auth_session_finalization": auth_finalize_class if auth_finalize_class else "",
        "auth_finalize_detail": auth_finalize_detail,
        "first_missing_login_transition": login_state.get("first_missing_transition"),
        "bridge_save_attempted": login_state.get("bridge_save_attempted"),
        "bridge_readback_attempted": login_state.get("bridge_readback_attempted"),
        "failure_phase": login_state.get("failure_phase") or "",
        "selected_app_page_id": (browser_surfaces or {}).get("selected_app_page_id") or "",
        "artifact": str(artifact),
        "trace_dir": trace_meta.get("trace_dir"),
    }
    if extra_stdout:
        stdout.update(extra_stdout)
    stdout["strict_capture"] = _public_summary(strict_capture or {})
    print(json.dumps(stdout, default=str))
    return code


def main() -> int:
    from cloud_streamlit_wake import gentle_wake_if_asleep, goto_and_wake
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
    surface_monitor: BrowserSurfaceMonitor | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        page = context.new_page()
        surface_monitor = BrowserSurfaceMonitor(context=context, target_sid=target_sid, collector=collector)
        surface_monitor.wire(page)
        goto_and_wake(page, start_url, timeout_s=240)
        collector.note_url(page.url or "", label="initial_load")
        TRACE_ROOT.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(TRACE_ROOT / f"{target_sid[:8]}_login_start.png"))
        except Exception:
            pass

        deadline = time.time() + WAIT_S
        _status("complete Daniel sign-in — harness will not reload the page while you type")
        hydration_announced = False
        hands_off_announced = False
        poll_interval_s = max(POLL_MS / 1000.0, 5.0)

        while time.time() < deadline:
            try:
                surface_monitor.poll()
            except Exception:
                pass
            surface_monitor.sync_identity(identity)

            if surface_monitor.hands_off_user_login():
                if not hands_off_announced:
                    hands_off_announced = True
                    _status("login in progress — no reloads, tab switches, or wake navigation")
                time.sleep(poll_interval_s)
                continue

            app_page = surface_monitor.cloud_app_page()
            if app_page is None:
                if context.pages and any(not pg.is_closed() for pg in context.pages):
                    time.sleep(poll_interval_s)
                    continue
                stub = page
                if stub.is_closed():
                    live = [pg for pg in context.pages if not pg.is_closed()]
                    stub = live[0] if live else page
                surfaces = surface_monitor.diagnostic_blob()
                code = _finalize_exit(
                    code=1,
                    identity=identity,
                    failure="browser_closed_before_capture_complete",
                    page=stub,
                    collector=collector,
                    ledger_rows=[],
                    strict_capture=last_eval or None,
                    files_updated=False,
                    screenshot_phase="browser_closed",
                    browser_surfaces=surfaces,
                    sign_in_initiated=surface_monitor.sign_in_initiated,
                    failure_phase="browser_closed_before_capture_complete",
                )
                try:
                    context.close()
                    browser.close()
                except Exception:
                    pass
                return code
            url = app_page.url or ""
            if is_provider_url(url):
                surface_monitor.record_harness_event("script_navigation_suppressed", detail="app_page_is_provider")
                time.sleep(poll_interval_s)
                continue
            collector.note_url(url, label="app_page_poll")
            url_sid = suite_sid_from_url(url)
            if url_sid and url_sid != target_sid:
                ledger = scrape_stage1_ledger_rows(app_page) or []
                surfaces = surface_monitor.diagnostic_blob()
                code = _finalize_exit(
                    code=1,
                    identity=identity,
                    failure="suite_sid_changed",
                    page=app_page,
                    collector=collector,
                    ledger_rows=ledger,
                    strict_capture=last_eval or None,
                    files_updated=False,
                    sid_drift=True,
                    screenshot_phase="sid_drift",
                    extra_stdout={"url_sid": url_sid},
                    browser_surfaces=surfaces,
                    sign_in_initiated=surface_monitor.sign_in_initiated,
                )
                context.close()
                browser.close()
                return code

            last_eval = _strict_poll(app_page, target_sid=target_sid, scrape_ledger=scrape_stage1_ledger_rows)
            if last_eval.get("failure") == "browser_page_closed":
                page = app_page
                continue
            if last_eval.get("strict_auth_passed"):
                page = app_page
                break

            if identity.get("signed_in_display") and not hydration_announced:
                hydration_announced = True
                _status("signed-in UI visible — waiting for ledger bridge/apply (not treating as success)")
                try:
                    app_page.screenshot(path=str(TRACE_ROOT / f"{target_sid[:8]}_signed_in_waiting_ledger.png"))
                except Exception:
                    pass

            time.sleep(poll_interval_s)
            if not surface_monitor.hands_off_user_login():
                try:
                    wake = gentle_wake_if_asleep(app_page)
                    if wake.get("action") == "wake_click":
                        surface_monitor.record_harness_event("script_wake_click_only", detail="asleep")
                except Exception as exc:
                    surface_monitor.record_harness_event("script_wake_failed", detail=type(exc).__name__)
        else:
            app_page = surface_monitor.app_page(page)
            ledger = scrape_stage1_ledger_rows(app_page) or []
            identity["cloud_runtime_sha"] = (scrape_deploy_marker_from_page(app_page)[0] or "")
            surfaces = surface_monitor.diagnostic_blob()
            fail = str(last_eval.get("failure") or "timeout_strict_capture")
            login_state_preview = login_transition_state(
                target_sid=target_sid,
                url_sid=suite_sid_from_url(app_page.url or ""),
                provider_seen=surface_monitor.provider_surface_seen,
                oauth_callback_seen=surface_monitor.oauth_callback_seen,
                returned_to_app=surface_monitor.returned_to_cloud_after_provider,
                storage=probe_storage_booleans(app_page),
                signed_in_display=surface_monitor.signed_in_display_any_surface,
                ledger_rows=ledger,
                strict_failure=fail,
                sign_in_initiated=surface_monitor.sign_in_initiated,
            )
            phase = infer_timeout_failure_phase(login_state_preview, strict_failure=fail)
            code = _finalize_exit(
                code=1,
                identity=identity,
                failure=fail,
                page=app_page,
                collector=collector,
                ledger_rows=ledger,
                strict_capture=last_eval,
                files_updated=False,
                screenshot_phase="timeout_hydration",
                browser_surfaces=surfaces,
                sign_in_initiated=surface_monitor.sign_in_initiated,
                failure_phase=phase,
            )
            context.close()
            browser.close()
            return code

        if not last_eval.get("strict_auth_passed"):
            app_page = surface_monitor.app_page(page)
            ledger = scrape_stage1_ledger_rows(app_page) or []
            identity["cloud_runtime_sha"] = (scrape_deploy_marker_from_page(app_page)[0] or "")
            surfaces = surface_monitor.diagnostic_blob()
            fail = str(last_eval.get("failure") or "strict_capture_incomplete")
            code = _finalize_exit(
                code=1,
                identity=identity,
                failure=fail,
                page=app_page,
                collector=collector,
                ledger_rows=ledger,
                strict_capture=last_eval,
                files_updated=False,
                screenshot_phase="strict_incomplete",
                browser_surfaces=surfaces,
                sign_in_initiated=surface_monitor.sign_in_initiated,
            )
            context.close()
            browser.close()
            return code

        page = surface_monitor.app_page(page)
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
        obs_pkg = _observability_package(
            page,
            harness_sid=target_sid,
            ledger_rows=ledger,
            strict_failure="",
        )
        observability_binding = obs_pkg["observability_binding"]
        ledger = obs_pkg.get("ledger_rows") or ledger
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
            sign_in_initiated=bool(identity.get("sign_in_initiated")),
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
            browser_surfaces=surface_monitor.diagnostic_blob() if surface_monitor else None,
        )
        success_payload = {
            **identity,
            "capture_ended_at": utc_capture_timestamp(),
            "failure": "",
            "strict_capture": _public_summary(last_eval),
            "login_boundary": login_state,
            "login_timeline": ledger_login_timeline(ledger),
            "observability_binding": observability_binding,
            "auth_capture_pass": True,
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
            "observability_binding": observability_binding,
            "auth_capture_pass": True,
        }
        print(json.dumps(stdout, default=str))
        context.close()
        browser.close()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
