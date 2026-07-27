"""Run RV0–RV3 return-value binding ladder on Cloud (authenticated). Stops at first valid failure."""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
OUT = ROOT / "data" / "solo_rv_binding_ladder.json"


def required_implementation_sha() -> str:
    marker = ROOT / "deploy_commit.txt"
    if marker.is_file():
        for line in marker.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "branch:" not in line.lower():
                return line.split()[0].lower()[:7]
    return "a2aaa8e"


REQUIRED_SHA = required_implementation_sha()

from playwright_daniel_auth_session import STORAGE_PATH, append_suite_sid_to_url, harness_ready  # noqa: E402
from replay_playwright_daniel_auth_preflight import run_preflight  # noqa: E402
from run_production_stage1_authenticated import (  # noqa: E402
    production_url,
    wait_one_expiration,
    validate_production_draft_start,
)
from solo_draft_start_harness import execute_solo_draft_start_workflow  # noqa: E402
from solo_rv_ladder_runner_state import (  # noqa: E402
    classify_page_shell,
    ledger_rows_for_run as state_ledger_rows_for_run,
    ledger_ready,
    page_state_to_invalid_reason,
    should_begin_instrumentation_epoch,
    verify_rv1_control_url,
)
from stage1_preflight_cleanup import run_stage1_preflight_cleanup  # noqa: E402

EVIDENCE_DIR = ROOT / "data" / "solo_rv_rv1_failure_evidence"


def rv_url(step: str, run_id: str, *, ldr: bool = False, harness_room_id: str = "") -> str:
    q = {
        "solo_rv_ladder": step,
        "solo_rv_run_id": run_id,
        "solo_delivery_diag": "1",
        "solo_component_diag": "1",
        "solo_diag_timer": "10",
    }
    if harness_room_id:
        q["solo_rv_harness_room_id"] = harness_room_id.strip().upper()
    if ldr or step == "RV1":
        q["active_page"] = "Live Draft Room"
    base = f"{BASE}/?{urlencode(q)}"
    return append_suite_sid_to_url(base)


def scrape_b64_probe(page, element_id: str) -> dict[str, Any]:
    try:
        b64 = page.evaluate(
            f"""() => {{
              function roots(){{ const r=[document]; for (const f of document.querySelectorAll('iframe')) {{ try {{ r.push(f.contentDocument);}} catch(e){{}} }} return r.filter(Boolean); }}
              for (const root of roots()) {{
                const el = root.querySelector(#{element_id});
                if (el) return el.getAttribute('data-b64') || '';
              }}
              return '';
            }}"""
        )
        if not b64:
            return {}
        pad = b64 + "==="[: (4 - len(b64) % 4) % 4]
        return json.loads(base64.b64decode(pad).decode("utf-8"))
    except Exception:
        return {}


def scrape_registry_localstorage(page) -> dict[str, Any]:
    try:
        raw = page.evaluate(
            """() => {
              try {
                const s = localStorage.getItem('__solo_rv_instance_registry_v1');
                return s ? JSON.parse(s) : {};
              } catch (e) { return {}; }
            }"""
        )
        if isinstance(raw, dict) and raw.get("last"):
            return raw
        probe = scrape_b64_probe(page, "solo-rv-instance-registry")
        if probe:
            return {"python_side_probe": probe, "last": [], "logical": []}
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def verify_cloud_sha(page) -> tuple[str, str]:
    from cloud_streamlit_wake import scrape_deploy_sha_from_page
    from run_production_solo_soak import all_frames_text, scrape_deploy_build
    from run_solo_clean_verification import scrape_live_sha
    from verify_cloud_deploy_playwright import scrape_deploy

    probe = scrape_deploy(page) or {}
    sha = (
        scrape_live_sha(page)
        or scrape_deploy_sha_from_page(page)
        or scrape_deploy_build(page)
        or str(probe.get("sha") or "")
    ).strip().lower()[:7]
    build = str(probe.get("build") or "").strip()
    if not build:
        m = __import__("re").search(r"baseball-dev-([0-9a-f]{7})", all_frames_text(page), __import__("re").I)
        if m:
            build = f"baseball-dev-{m.group(1).lower()}"
    return sha, build


def assert_cloud_implementation_ready(page, required: str) -> tuple[bool, str, str]:
    sha, build = verify_cloud_sha(page)
    ok_sha = sha == required[:7]
    ok_build = build.lower() == f"baseball-dev-{required[:7].lower()}"
    if ok_sha and ok_build:
        return True, sha, build
    if ok_sha and not ok_build:
        return False, sha, build
    return False, sha, build


def redact_url(url: str) -> str:
    try:
        from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

        parts = urlparse(url)
        q = parse_qs(parts.query, keep_blank_values=True)
        if "suite_sid" in q:
            q["suite_sid"] = ["[redacted]"]
        return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, urlencode(q, doseq=True), parts.fragment))
    except Exception:
        return "[redacted]"


def attach_page_diagnostics(page) -> dict[str, Any]:
    collectors: dict[str, Any] = {"console": [], "pageerrors": [], "request_failed": []}

    def _on_console(msg: Any) -> None:
        try:
            collectors["console"].append({"type": msg.type, "text": str(msg.text)[:2000]})
        except Exception:
            pass

    def _on_pageerror(exc: Any) -> None:
        collectors["pageerrors"].append(str(exc)[:4000])

    def _on_request_failed(req: Any) -> None:
        try:
            collectors["request_failed"].append(
                {"url": str(req.url)[:500], "failure": str(req.failure)[:500] if req.failure else ""}
            )
        except Exception:
            pass

    page.on("console", _on_console)
    page.on("pageerror", _on_pageerror)
    page.on("requestfailed", _on_request_failed)
    return collectors


def scrape_visible_page_text(page) -> str:
    try:
        return str(
            page.evaluate(
                """() => {
              function allText() {
                let t = document.body ? document.body.innerText : '';
                for (const f of document.querySelectorAll('iframe')) {
                  try {
                    if (f.contentDocument && f.contentDocument.body) {
                      t += '\\n' + f.contentDocument.body.innerText;
                    }
                  } catch (e) {}
                }
                return t;
              }
              return allText();
            }"""
            )
            or ""
        )
    except Exception:
        return ""


def scrape_page_dom_snapshot(page) -> dict[str, Any]:
    from live_draft_solo_rv_control_probe import RV_LEDGER_B64_PREFIX

    try:
        return page.evaluate(
            f"""() => {{
              function roots() {{
                const r = [document];
                for (const f of document.querySelectorAll('iframe')) {{
                  try {{ if (f.contentDocument) r.push(f.contentDocument); }} catch (e) {{}}
                }}
                return r.filter(Boolean);
              }}
              let text = '';
              for (const root of roots()) {{
                if (root.body) text += root.body.innerText + '\\n';
              }}
              const prefix = {json.dumps(RV_LEDGER_B64_PREFIX)};
              let hasProbe = false;
              for (const root of roots()) {{
                if (root.querySelector('#solo-rv-control-probe')) hasProbe = true;
              }}
              return {{
                has_streamlit_app: !!document.querySelector('[data-testid="stApp"]'),
                has_st_exception: !!document.querySelector('.stException, [data-testid="stException"]'),
                has_streamlit_error: /Traceback|Error:/i.test(text),
                has_login: /sign in|log in|not signed in/i.test(text) && !/signed in as/i.test(text),
                has_ledger_prefix: text.includes(prefix),
                has_probe_el: hasProbe,
                has_live_draft_heading: /Live Draft/i.test(text),
                app_loading: !!document.querySelector('[data-testid="stStatusWidget"]'),
              }};
            }}"""
        )
    except Exception:
        return {}


def session_fingerprint(page) -> dict[str, Any]:
    try:
        fp = page.evaluate(
            """() => {
              const keys = document.cookie.split(';').map(s => s.split('=')[0].trim()).filter(Boolean).sort();
              return {
                cookie_key_fingerprint: keys.join('|'),
                path: location.pathname,
                has_suite_sid: location.search.includes('suite_sid='),
              };
            }"""
        )
        fp["url_redacted"] = redact_url(page.url)
        return fp if isinstance(fp, dict) else {"url_redacted": redact_url(page.url)}
    except Exception:
        return {"url_redacted": redact_url(page.url)}


def streamlit_session_from_rows(rows: list[dict[str, Any]]) -> str:
    for row in reversed(rows):
        sid = str(row.get("streamlit_session_id") or "").strip()
        if sid:
            return sid
    return ""


def capture_rv1_failure_evidence(
    page,
    *,
    run_id: str,
    harness_room_id: str,
    diagnostics: dict[str, Any],
    page_state: str,
    url_check: dict[str, Any],
) -> dict[str, Any]:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    text = scrape_visible_page_text(page)
    dom = scrape_page_dom_snapshot(page)
    probe = scrape_control_probe(page)
    rows = state_ledger_rows_for_run(probe, run_id)
    evidence: dict[str, Any] = {
        "run_id": run_id,
        "harness_room_id": harness_room_id,
        "page_state": page_state,
        "invalid_reason": page_state_to_invalid_reason(page_state),
        "final_url_redacted": redact_url(page.url),
        "page_title": page.title(),
        "visible_text_head": text[:12000],
        "dom": dom,
        "url_check": url_check,
        "expected_run_id": run_id,
        "expected_harness_room_id": harness_room_id,
        "console_tail": list(diagnostics.get("console") or [])[-40:],
        "pageerrors": list(diagnostics.get("pageerrors") or [])[-20:],
        "request_failed_tail": list(diagnostics.get("request_failed") or [])[-30:],
        "ledger_row_count": len(rows),
        "ledger_events": [str(r.get("event") or "") for r in rows],
    }
    try:
        err_el = page.locator(".stException, [data-testid='stException']").first
        if err_el.count():
            evidence["streamlit_error_text"] = err_el.inner_text(timeout=2000)[:8000]
    except Exception:
        evidence["streamlit_error_text"] = ""
    shot = EVIDENCE_DIR / f"rv1_{run_id}.png"
    try:
        page.screenshot(path=str(shot), full_page=True)
        evidence["screenshot"] = str(shot)
    except Exception:
        evidence["screenshot"] = ""
    out_json = EVIDENCE_DIR / f"rv1_{run_id}.json"
    out_json.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    evidence["artifact_json"] = str(out_json)
    return evidence


def wait_for_rv1_control_ready(
    page,
    run_id: str,
    *,
    timeout_s: float = 120.0,
) -> tuple[str, dict[str, Any], list[dict[str, Any]], str]:
    """Wait until READY or terminal page state. Returns (page_state, probe, rows, visible_text)."""
    deadline = time.time() + timeout_s
    best_probe: dict[str, Any] = {}
    best_rows: list[dict[str, Any]] = []
    last_state = "PAGE_NOT_READY"
    last_text = ""
    while time.time() < deadline:
        last_text = scrape_visible_page_text(page)
        dom = scrape_page_dom_snapshot(page)
        probe = scrape_control_probe(page)
        rows = state_ledger_rows_for_run(probe, run_id)
        if probe and len(probe.get("rows") or []) >= len(best_probe.get("rows") or []):
            best_probe = probe
            best_rows = rows
        last_state = classify_page_shell(page_text=last_text, dom=dom, rows=rows)
        if last_state == "READY" and not (
            {str(r.get("event") or "") for r in rows} >= {"real_room_hydrated", "declaration_returned"}
        ):
            last_state = "READY_PENDING"
        if last_state == "READY":
            return "READY", best_probe, best_rows, last_text
        if last_state in ("APP_ERROR", "AUTH_LOST", "ROUTE_NOT_ENTERED"):
            if rows and any(
                r.get("event") in ("declaration_attempt", "production_draft_started", "real_room_hydrated")
                for r in rows
            ):
                last_state = "READY_PENDING"
            elif last_state in ("APP_ERROR", "AUTH_LOST"):
                return last_state, best_probe, best_rows, last_text
        events = {str(r.get("event") or "") for r in rows}
        if events >= {"script_begin", "rv_entrypoint_entered"}:
            if "rv_mount_failed" in events or "production_room_creation_failed" in events:
                return "READY", best_probe, best_rows, last_text
            if "declaration_returned" in events and "real_room_hydrated" in events:
                return "READY", best_probe, best_rows, last_text
        page.wait_for_timeout(2000)
    if not best_rows and not ledger_ready(best_rows, page_text=last_text):
        if last_state == "READY_PENDING":
            return "READY_PENDING", best_probe, best_rows, last_text
        return last_state, best_probe, best_rows, last_text
    if ledger_ready(best_rows, page_text=last_text):
        return "READY", best_probe, best_rows, last_text
    return last_state if last_state != "READY_PENDING" else "READY_PENDING", best_probe, best_rows, last_text


def run_rv1_control_observation(
    page,
    run_id: str,
    *,
    harness_room_id: str,
    url_check: dict[str, Any],
    diagnostics: dict[str, Any],
    session_trace: list[dict[str, Any]],
) -> dict[str, Any]:
    page_state, probe, rows, _text = wait_for_rv1_control_ready(page, run_id, timeout_s=120.0)
    session_trace.append({"phase": "rv1_control_url", **session_fingerprint(page), "streamlit_session_id": streamlit_session_from_rows(rows)})
    if page_state != "READY":
        reason = page_state_to_invalid_reason(page_state)
        if not rows and page_state in ("READY_PENDING", "PAGE_NOT_READY"):
            reason = "INVALID_RV_CONTROL_PAGE_NOT_OBSERVED"
        evidence = capture_rv1_failure_evidence(
            page,
            run_id=run_id,
            harness_room_id=harness_room_id,
            diagnostics=diagnostics,
            page_state=page_state,
            url_check=url_check,
        )
        return {
            "verdict": "INVALID",
            "reason": reason,
            "page_state": page_state,
            "control_probe_ledger": rows,
            "control_failure_evidence": evidence,
            "session_trace": session_trace,
            "instrumentation_epoch_ms": None,
            "expiration_skipped": True,
        }
    ok_epoch, verdict, reason = should_begin_instrumentation_epoch(
        page_state=page_state,
        rows=rows,
        harness_room_id=harness_room_id,
    )
    if not ok_epoch:
        evidence = capture_rv1_failure_evidence(
            page,
            run_id=run_id,
            harness_room_id=harness_room_id,
            diagnostics=diagnostics,
            page_state="READY",
            url_check=url_check,
        )
        return {
            "verdict": verdict or "INVALID",
            "reason": reason,
            "page_state": "READY",
            "control_probe_ledger": rows,
            "control_failure_evidence": evidence,
            "session_trace": session_trace,
            "instrumentation_epoch_ms": None,
            "expiration_skipped": True,
        }
    exp, probe, reg, epoch_ms, meta = _rv1_post_declaration_epoch(
        page, run_id, harness_room_id=harness_room_id, probe=probe, rows=rows
    )
    return {
        "verdict": None,
        "reason": "",
        "page_state": "READY_HYDRATED",
        "expiration": exp,
        "control_probe": probe,
        "registry": reg,
        "instrumentation_epoch_ms": epoch_ms,
        "declaration_meta": meta,
        "session_trace": session_trace,
        "expiration_skipped": False,
    }


def _rv1_post_declaration_epoch(
    page,
    run_id: str,
    *,
    harness_room_id: str,
    probe: dict[str, Any],
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], float, dict[str, Any]]:
    from live_draft_solo_rv_binding_ladder import filter_observations_after_epoch

    expected_token = ""
    hydrated_room = ""
    for row in rows:
        if row.get("event") == "real_room_hydrated":
            expected_token = str(row.get("expected_token") or "")
            hydrated_room = str(row.get("room_id") or "")
            break
    deadline = time.time() + 120.0
    while time.time() < deadline:
        probe = poll_control_probe_best(page, probe)
        rows = state_ledger_rows_for_run(probe, run_id)
        if any(r.get("event") == "declaration_returned" for r in rows):
            break
        page.wait_for_timeout(2000)
    epoch_ms = reset_browser_instrumentation_epoch(page, run_id)
    exp = wait_rv_control_expiration(page, timeout_s=95.0)
    reg = scrape_registry_localstorage(page)
    exp, reg = filter_observations_after_epoch(
        exp,
        reg,
        epoch_ms=epoch_ms,
        expected_token=expected_token,
        run_id=run_id,
    )
    exp["harness_room_id"] = harness_room_id
    exp["hydrated_room_id"] = hydrated_room
    exp["instrumentation_epoch_ms"] = epoch_ms
    exp["expected_token_ledger"] = expected_token
    poll_until = time.time() + 60.0
    while time.time() < poll_until:
        probe = poll_control_probe_best(page, probe)
        page.wait_for_timeout(2000)
    probe = poll_control_probe_best(page, probe)
    return exp, probe, reg, epoch_ms, {
        "expected_token": expected_token,
        "hydrated_room_id": hydrated_room,
        "pre_expiration_rows": rows,
    }


def scrape_control_probe(page) -> dict[str, Any]:
    from live_draft_solo_rv_control_probe import RV_LEDGER_B64_PREFIX, decode_control_probe_text

    try:
        text = page.evaluate(
            """() => {
              function allText() {
                let t = document.body ? document.body.innerText : '';
                for (const f of document.querySelectorAll('iframe')) {
                  try {
                    if (f.contentDocument && f.contentDocument.body) {
                      t += '\\n' + f.contentDocument.body.innerText;
                    }
                  } catch (e) {}
                }
                return t;
              }
              return allText();
            }"""
        )
        payload = decode_control_probe_text(str(text or ""))
        if payload.get("rows"):
            return payload
    except Exception:
        pass
    return {}


def poll_control_probe_best(page, best: dict[str, Any]) -> dict[str, Any]:
    probe = scrape_control_probe(page)
    if probe and len(probe.get("rows") or []) >= len(best.get("rows") or []):
        return probe
    return best


def ledger_rows_for_run(probe: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    return [r for r in list(probe.get("rows") or []) if str(r.get("run_id") or "") == run_id]


def wait_for_rv_control_declaration(
    page,
    run_id: str,
    *,
    timeout_s: float = 120.0,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Wait for rv_entrypoint_entered + declaration_attempt (or mount failure) on control URL."""
    deadline = time.time() + timeout_s
    best_probe: dict[str, Any] = {}
    best_rows: list[dict[str, Any]] = []
    while time.time() < deadline:
        probe = scrape_control_probe(page)
        rows = ledger_rows_for_run(probe, run_id)
        if probe and len(probe.get("rows") or []) >= len(best_probe.get("rows") or []):
            best_probe = probe
            best_rows = rows
        events = {str(r.get("event") or "") for r in rows}
        if "rv_mount_failed" in events or "rv_real_room_hydration_failed" in events:
            return best_probe, rows
        if "rv_entrypoint_entered" in events and "declaration_attempt" in events:
            return best_probe, rows
        page.wait_for_timeout(2000)
    return best_probe, best_rows


def hydration_failed_in_probe(probe: dict[str, Any], run_id: str) -> bool:
    rows = ledger_rows_for_run(probe, run_id)
    return any(r.get("event") == "rv_real_room_hydration_failed" for r in rows)


def reset_browser_instrumentation_epoch(page, run_id: str) -> float:
    """Clear pre-navigation registry/listeners; start grading epoch (ms since epoch)."""
    from stage1_frame_transport_probe import install_immediate_parent_listeners

    epoch_ms = time.time() * 1000.0
    page.evaluate(
        """(payload) => {
          try { localStorage.removeItem('__solo_rv_instance_registry_v1'); } catch (e) {}
          try { localStorage.removeItem('__solo_immediate_parent_transport_v1'); } catch (e) {}
          window.__solo_immediate_parent_msgs = [];
          window.__solo_rv_instrumentation_epoch_ms = payload.epochMs;
          window.__solo_rv_instrumentation_run_id = payload.runId;
        }""",
        {"epochMs": epoch_ms, "runId": run_id},
    )
    install_immediate_parent_listeners(page)
    return epoch_ms


def wait_rv_control_expiration(page, *, timeout_s: float = 95.0) -> dict[str, Any]:
    exp = wait_one_expiration(page, timeout_s=timeout_s)
    poll_until = time.time() + 45.0
    while time.time() < poll_until:
        page.wait_for_timeout(2000)
    return exp


def wait_rv_control_with_epoch(
    page,
    run_id: str,
    *,
    harness_room_id: str,
    timeout_decl_s: float = 120.0,
    timeout_exp_s: float = 95.0,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], float, dict[str, Any]]:
    from live_draft_solo_rv_binding_ladder import filter_observations_after_epoch

    probe, rows = wait_for_rv_control_declaration(page, run_id, timeout_s=timeout_decl_s)
    if hydration_failed_in_probe(probe, run_id):
        return (
            {"harness_room_id": harness_room_id, "hydration_failed": True},
            probe,
            {"last": [], "logical": [], "run_id": run_id},
            0.0,
            {"expected_token": "", "hydrated_room_id": "", "pre_expiration_rows": rows},
        )
    if not rows:
        return (
            {"harness_room_id": harness_room_id, "skipped_expiration": True},
            probe,
            {"last": [], "logical": [], "run_id": run_id},
            0.0,
            {"expected_token": "", "hydrated_room_id": "", "pre_expiration_rows": rows},
        )
    ok_epoch, _, _ = should_begin_instrumentation_epoch(page_state="READY", rows=rows, harness_room_id=harness_room_id)
    if not ok_epoch:
        return (
            {"harness_room_id": harness_room_id, "skipped_expiration": True},
            probe,
            {"last": [], "logical": [], "run_id": run_id},
            0.0,
            {"expected_token": "", "hydrated_room_id": "", "pre_expiration_rows": rows},
        )
    expected_token = ""
    hydrated_room = ""
    for row in rows:
        if row.get("event") == "real_room_hydrated":
            expected_token = str(row.get("expected_token") or "")
            hydrated_room = str(row.get("room_id") or "")
            break
        if row.get("event") == "declaration_attempt" and not expected_token:
            expected_token = str(row.get("expected_token") or "")
            hydrated_room = str(row.get("room_id") or "")
    epoch_ms = reset_browser_instrumentation_epoch(page, run_id)
    exp = wait_rv_control_expiration(page, timeout_s=timeout_exp_s)
    reg = scrape_registry_localstorage(page)
    exp, reg = filter_observations_after_epoch(
        exp,
        reg,
        epoch_ms=epoch_ms,
        expected_token=expected_token,
        run_id=run_id,
    )
    exp["harness_room_id"] = harness_room_id
    exp["hydrated_room_id"] = hydrated_room
    exp["instrumentation_epoch_ms"] = epoch_ms
    exp["expected_token_ledger"] = expected_token
    best_probe = probe
    poll_until = time.time() + 60.0
    while time.time() < poll_until:
        best_probe = poll_control_probe_best(page, best_probe)
        page.wait_for_timeout(2000)
    best_probe = poll_control_probe_best(page, best_probe)
    return exp, best_probe, reg, epoch_ms, {
        "expected_token": expected_token,
        "hydrated_room_id": hydrated_room,
        "pre_expiration_rows": rows,
    }


def wait_rv0_with_probe_polling(page, *, timeout_s: float = 95.0) -> tuple[dict[str, Any], dict[str, Any]]:
    best_probe: dict[str, Any] = {}
    exp = wait_one_expiration(page, timeout_s=timeout_s)
    poll_until = time.time() + 60.0
    while time.time() < poll_until:
        best_probe = poll_control_probe_best(page, best_probe)
        page.wait_for_timeout(2000)
    best_probe = poll_control_probe_best(page, best_probe)
    return exp, best_probe


def evaluate_step(
    step: str,
    *,
    run_id: str,
    expiration: dict[str, Any],
    control_probe: dict[str, Any],
    reg: dict[str, Any],
    room_id: str = "",
    instrumentation_epoch_ms: float | None = None,
) -> dict[str, Any]:
    from live_draft_solo_rv_binding_ladder import (
        build_declaration_timeline,
        build_instance_identity_report,
        classify_root_cause,
        grade_rv_control_validity,
        summarize_browser_events,
    )
    from live_draft_solo_rv_control_probe import ledger_to_declaration_rows

    ledger_rows = [r for r in list(control_probe.get("rows") or []) if str(r.get("run_id") or "") in ("", run_id)]
    if run_id:
        matched = [r for r in ledger_rows if str(r.get("run_id") or "") == run_id]
        if matched:
            ledger_rows = matched
    rows = ledger_to_declaration_rows(ledger_rows)
    browser = summarize_browser_events(expiration, reg)
    validity_ok, validity_reason = __import__(
        "live_draft_solo_rv_binding_ladder", fromlist=["validate_rv_control_prerequisites"]
    ).validate_rv_control_prerequisites(
        declaration_rows=rows,
        browser=browser,
        expiration=expiration,
        control_probe_rows=ledger_rows,
    )
    verdict, reason = grade_rv_control_validity(
        step=step,
        ledger=ledger_rows,
        declaration_rows=rows,
        browser=browser,
        expiration=expiration,
    )
    root = classify_root_cause(
        validity_ok=validity_ok,
        verdict=verdict,
        browser=browser,
        declaration_rows=rows,
    )
    hydrated_row = next((r for r in ledger_rows if r.get("event") == "real_room_hydrated"), None)
    return {
        "step": step,
        "run_id": run_id,
        "room_id": room_id,
        "created_room_id": room_id,
        "hydrated_room_id": str(
            (hydrated_row or {}).get("room_id") or expiration.get("hydrated_room_id") or ""
        ),
        "pick_index": (hydrated_row or {}).get("pick_index"),
        "deadline": (hydrated_row or {}).get("deadline"),
        "expected_token": str((hydrated_row or {}).get("expected_token") or expiration.get("expected_token_ledger") or ""),
        "instrumentation_epoch_ms": instrumentation_epoch_ms or expiration.get("instrumentation_epoch_ms"),
        "verdict": verdict,
        "reason": reason,
        "validity_ok": validity_ok,
        "validity_reason": validity_reason,
        "root_cause": root,
        "browser_summary": browser,
        "control_probe_ledger": ledger_rows,
        "instance_identity_report": build_instance_identity_report(expiration, reg),
        "declaration_timeline": build_declaration_timeline({"rows": rows}),
        "expiration_summary": {
            "token_sent": expiration.get("token_sent"),
            "observation_duration_s": expiration.get("observation_duration_s"),
            "post_send_observation_s": expiration.get("post_send_observation_s"),
            "client_stages_tail": list(expiration.get("client_stages") or [])[-20:],
        },
    }


def run_rv0(context, run_id: str, *, cloud_sha: str, cloud_build: str) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake

    page = context.new_page()
    goto_and_wake(page, rv_url("RV0", run_id), timeout_s=240)
    page.wait_for_timeout(12000)
    exp, probe = wait_rv0_with_probe_polling(page, timeout_s=95.0)
    reg = scrape_registry_localstorage(page)
    result = evaluate_step("RV0", run_id=run_id, expiration=exp, control_probe=probe, reg=reg)
    result["cloud_sha"] = cloud_sha
    result["cloud_build"] = cloud_build
    page.close()
    return result


def run_rv1_direct(context, run_id: str, *, cloud_sha: str, cloud_build: str) -> dict[str, Any]:
    """Navigate directly to RV1 URL; room is created inside the diagnostic route."""
    from cloud_streamlit_wake import goto_and_wake

    page = context.new_page()
    diagnostics = attach_page_diagnostics(page)
    session_trace: list[dict[str, Any]] = []
    control_url = rv_url("RV1", run_id)
    goto_and_wake(page, control_url, timeout_s=240)
    page.wait_for_timeout(8000)
    url_check = verify_rv1_control_url(page.url, run_id=run_id)
    url_check["requested_url_redacted"] = redact_url(control_url)
    url_check["final_url_redacted"] = redact_url(page.url)
    obs = run_rv1_control_observation(
        page,
        run_id,
        harness_room_id="",
        url_check=url_check,
        diagnostics=diagnostics,
        session_trace=session_trace,
    )
    if obs.get("verdict") == "INVALID":
        result = {
            "step": "RV1",
            "run_id": run_id,
            "room_id": "",
            "created_room_id": "",
            "verdict": "INVALID",
            "reason": obs.get("reason"),
            "page_state": obs.get("page_state"),
            "url_check": url_check,
            "session_trace": obs.get("session_trace"),
            "control_probe_ledger": obs.get("control_probe_ledger") or [],
            "control_failure_evidence": obs.get("control_failure_evidence"),
            "instrumentation_epoch_ms": None,
            "expiration_skipped": True,
            "validity_ok": False,
            "validity_reason": obs.get("reason"),
            "root_cause": "",
        }
        result["cloud_sha"] = cloud_sha
        result["cloud_build"] = cloud_build
        page.close()
        return result
    exp = obs["expiration"]
    probe = obs["control_probe"]
    reg = obs["registry"]
    epoch_ms = obs["instrumentation_epoch_ms"]
    meta = obs["declaration_meta"]
    created_room = ""
    for row in state_ledger_rows_for_run(probe, run_id):
        if row.get("event") == "production_room_created":
            created_room = str(row.get("room_id") or (row.get("extra") or {}).get("room_id") or "")
            break
    result = evaluate_step(
        "RV1",
        run_id=run_id,
        expiration=exp,
        control_probe=probe,
        reg=reg,
        room_id=created_room,
        instrumentation_epoch_ms=epoch_ms,
    )
    result["declaration_meta"] = meta
    result["url_check"] = url_check
    result["session_trace"] = obs.get("session_trace", session_trace)
    result["cloud_sha"] = cloud_sha
    result["cloud_build"] = cloud_build
    page.close()
    return result


def run_rv_real_step(context, step: str, run_id: str, *, cloud_sha: str, cloud_build: str) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake

    page = context.new_page()
    diagnostics = attach_page_diagnostics(page)
    session_trace: list[dict[str, Any]] = []
    url = production_url()
    goto_and_wake(page, url, timeout_s=240)
    page.wait_for_timeout(15000)
    try:
        page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
        page.wait_for_timeout(3000)
    except Exception:
        pass
    page.wait_for_timeout(20000)
    cleanup = run_stage1_preflight_cleanup(page)
    if not cleanup.get("ok"):
        page.close()
        return {"step": step, "verdict": "INVALID", "reason": "setup_lobby_blocked", "run_id": run_id, "cleanup": cleanup}
    draft = execute_solo_draft_start_workflow(page, url, navigate=False)
    start_val = validate_production_draft_start(page, draft, prior_room_id=str(cleanup.get("detected_room_id") or ""))
    if not start_val.get("valid"):
        page.close()
        return {"step": step, "verdict": "INVALID", "reason": "draft_start_invalid", "run_id": run_id, "start": start_val}
    harness_room_id = str(start_val.get("latched_room_id") or "")
    session_trace.append(
        {
            "phase": "room_creation",
            **session_fingerprint(page),
            "streamlit_session_id": streamlit_session_from_rows(state_ledger_rows_for_run(scrape_control_probe(page), run_id)),
        }
    )
    goto_and_wake(page, url, timeout_s=120)
    page.wait_for_timeout(10000)
    session_trace.append({"phase": "ldr_refresh", **session_fingerprint(page)})
    control_url = rv_url(step, run_id, ldr=True, harness_room_id=harness_room_id)
    goto_and_wake(page, control_url, timeout_s=240)
    page.wait_for_timeout(8000)
    url_check = verify_rv1_control_url(page.url, run_id=run_id, harness_room_id=harness_room_id) if step == "RV1" else {"ok": True}
    url_check["requested_url_redacted"] = redact_url(control_url)
    url_check["final_url_redacted"] = redact_url(page.url)

    if step == "RV1":
        obs = run_rv1_control_observation(
            page,
            run_id,
            harness_room_id=harness_room_id,
            url_check=url_check,
            diagnostics=diagnostics,
            session_trace=session_trace,
        )
        if obs.get("verdict") == "INVALID":
            result = {
                "step": step,
                "run_id": run_id,
                "room_id": harness_room_id,
                "created_room_id": harness_room_id,
                "verdict": "INVALID",
                "reason": obs.get("reason"),
                "page_state": obs.get("page_state"),
                "url_check": url_check,
                "session_trace": obs.get("session_trace"),
                "control_probe_ledger": obs.get("control_probe_ledger") or [],
                "control_failure_evidence": obs.get("control_failure_evidence"),
                "instrumentation_epoch_ms": None,
                "expiration_skipped": True,
                "validity_ok": False,
                "validity_reason": obs.get("reason"),
                "root_cause": "",
            }
            result["cloud_sha"] = cloud_sha
            result["cloud_build"] = cloud_build
            page.close()
            return result
        exp = obs["expiration"]
        probe = obs["control_probe"]
        reg = obs["registry"]
        epoch_ms = obs["instrumentation_epoch_ms"]
        meta = obs["declaration_meta"]
    else:
        exp, probe, reg, epoch_ms, meta = wait_rv_control_with_epoch(
            page,
            run_id,
            harness_room_id=harness_room_id,
            timeout_decl_s=120.0,
            timeout_exp_s=95.0,
        )
    result = evaluate_step(
        step,
        run_id=run_id,
        expiration=exp,
        control_probe=probe,
        reg=reg,
        room_id=harness_room_id,
        instrumentation_epoch_ms=epoch_ms,
    )
    result["declaration_meta"] = meta
    result["url_check"] = url_check
    if step == "RV1":
        result["session_trace"] = obs.get("session_trace", session_trace)
    else:
        result["session_trace"] = session_trace
    result["cloud_sha"] = cloud_sha
    result["cloud_build"] = cloud_build
    page.close()
    return result


def main() -> int:
    if not harness_ready():
        print(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}))
        return 1
    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        print(json.dumps({"aborted": True, "reason": "auth_preflight_failed"}))
        return 1
    summary: dict[str, Any] = {
        "started_at": time.time(),
        "required_implementation_sha": REQUIRED_SHA,
        "artifact": str(OUT),
        "steps": [],
        "stopped_at": None,
        "first_valid_failure": None,
    }
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        pre_ctx = browser.new_context(
            storage_state=str(STORAGE_PATH),
            viewport={"width": 1440, "height": 1400},
        )
        pre_page = pre_ctx.new_page()
        goto_and_wake(
            pre_page,
            append_suite_sid_to_url(f"{BASE}/?solo_delivery_diag=1"),
            timeout_s=240,
        )
        pre_page.wait_for_timeout(10000)
        ok, verified_sha, verified_build = assert_cloud_implementation_ready(pre_page, REQUIRED_SHA)
        pre_page.close()
        pre_ctx.close()
        summary["cloud_sha_verified_at_start"] = verified_sha
        summary["cloud_build_verified_at_start"] = verified_build
        if not ok:
            summary["aborted"] = True
            summary["abort_reason"] = f"cloud_sha_mismatch_{verified_sha}_need_{REQUIRED_SHA[:7]}"
            browser.close()
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
            print(json.dumps(summary, indent=2, default=str))
            return 1
        ladder_steps = tuple(
            s.strip().upper()
            for s in os.environ.get("SOLO_RV_LADDER_STEPS", "RV1").split(",")
            if s.strip()
        )
        for step in ladder_steps:
            run_id = str(uuid.uuid4())
            context = browser.new_context(
                storage_state=str(STORAGE_PATH),
                viewport={"width": 1440, "height": 1400},
            )
            if step == "RV0":
                result = run_rv0(context, run_id, cloud_sha=verified_sha, cloud_build=verified_build)
            elif step == "RV1":
                result = run_rv1_direct(context, run_id, cloud_sha=verified_sha, cloud_build=verified_build)
            else:
                result = run_rv_real_step(
                    context, step, run_id, cloud_sha=verified_sha, cloud_build=verified_build
                )
            context.close()
            summary["steps"].append(result)
            v = str(result.get("verdict") or "")
            if step == "RV0":
                if v != "PASS_RETURN_VALUE_DELIVERY":
                    summary["stopped_at"] = step
                    if v == "INVALID":
                        summary["first_invalid_control"] = result
                    else:
                        summary["first_valid_failure"] = result
                    break
                continue
            if v == "INVALID":
                summary["stopped_at"] = step
                summary["first_invalid_control"] = result
                break
            if v not in ("PASS", "PASS_RETURN_VALUE_DELIVERY"):
                summary["stopped_at"] = step
                summary["first_valid_failure"] = result
                break
        browser.close()
    summary["finished_at"] = time.time()
    summary["implementation_sha_observed"] = summary.get("cloud_sha_verified_at_start")
    summary["cloud_build_observed"] = summary.get("cloud_build_verified_at_start")
    if summary["steps"] and summary["steps"][-1].get("cloud_sha"):
        summary["implementation_sha_observed"] = summary["steps"][-1].get("cloud_sha")
        summary["cloud_build_observed"] = summary["steps"][-1].get("cloud_build")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return 0 if not summary.get("stopped_at") else 1


if __name__ == "__main__":
    raise SystemExit(main())
