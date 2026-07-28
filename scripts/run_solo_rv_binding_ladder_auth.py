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
    if ldr or step in ("RV1", "RV2", "RV3"):
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
    from live_draft_solo_rv_control_probe import playwright_ledger_scrape_script

    try:
        return str(page.evaluate(playwright_ledger_scrape_script()) or "")
    except Exception:
        return ""


def scrape_visible_page_text_legacy(page) -> str:
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
                has_streamlit_error: !!document.querySelector('.stException, [data-testid="stException"]'),
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
        "invalid_reason": page_state_to_invalid_reason(
            page_state, probe_parse=(probe or {}).get("_probe_parse")
        ),
        "probe_parse": dict((probe or {}).get("_probe_parse") or {}),
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
    control_step: str = "RV1",
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
        last_state = classify_page_shell(page_text=last_text, dom=dom, rows=rows, probe=probe)
        if last_state == "READY_LEDGER":
            last_state = "READY_PENDING"
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
        if control_step == "RV3":
            if events >= {"real_room_hydrated", "declaration_returned"}:
                return "READY", best_probe, best_rows, last_text
            if "rv3_setup_rerun_requested" in events or "production_room_reused" in events:
                last_state = "READY_PENDING"
        if events >= {"script_begin", "rv_entrypoint_entered"}:
            if "rv_mount_failed" in events or "production_room_creation_failed" in events:
                return "READY", best_probe, best_rows, last_text
            if control_step != "RV3" and "declaration_returned" in events and "real_room_hydrated" in events:
                return "READY", best_probe, best_rows, last_text
        page.wait_for_timeout(2000)
    if not best_rows and not ledger_ready(best_rows, page_text=last_text):
        if last_state == "READY_PENDING":
            return "READY_PENDING", best_probe, best_rows, last_text
        return last_state, best_probe, best_rows, last_text
    if ledger_ready(best_rows, page_text=last_text):
        return "READY", best_probe, best_rows, last_text
    return last_state if last_state != "READY_PENDING" else "READY_PENDING", best_probe, best_rows, last_text


def run_rv_control_observation(
    page,
    run_id: str,
    *,
    control_step: str,
    harness_room_id: str,
    url_check: dict[str, Any],
    diagnostics: dict[str, Any],
    session_trace: list[dict[str, Any]],
    instrumentation_epoch_id: str = "",
) -> dict[str, Any]:
    page_state, probe, rows, _text = wait_for_rv1_control_ready(
        page,
        run_id,
        timeout_s=180.0 if control_step == "RV3" else 120.0,
        control_step=control_step,
    )
    session_trace.append(
        {
            "phase": f"{control_step.lower()}_control_url",
            **session_fingerprint(page),
            "streamlit_session_id": streamlit_session_from_rows(rows),
        }
    )
    if page_state != "READY":
        reason = page_state_to_invalid_reason(page_state, probe_parse=(probe or {}).get("_probe_parse"))
        if not rows and page_state in ("READY_PENDING", "PAGE_NOT_READY"):
            parse = dict((probe or {}).get("_probe_parse") or {})
            if parse.get("prefix_found") and not parse.get("decode_ok"):
                reason = page_state_to_invalid_reason("PAGE_NOT_READY", probe_parse=parse)
            elif not parse.get("decode_ok"):
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
        page,
        run_id,
        harness_room_id=harness_room_id,
        probe=probe,
        rows=rows,
        instrumentation_epoch_id=instrumentation_epoch_id,
        control_step=control_step,
    )
    return {
        "verdict": None,
        "reason": "",
        "page_state": "READY_HYDRATED",
        "expiration": exp,
        "control_probe": probe,
        "registry": reg,
        "instrumentation_epoch_ms": epoch_ms,
        "instrumentation_epoch_id": instrumentation_epoch_id or meta.get("instrumentation_epoch_id"),
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
    instrumentation_epoch_id: str = "",
    control_step: str = "RV1",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], float | None, dict[str, Any]]:
    from solo_rv_browser_observation import (
        attach_rv_page_listeners,
        build_run_identity_from_ledger,
        filter_observations_by_run_identity,
    )

    deadline = time.time() + 120.0
    while time.time() < deadline:
        probe = poll_control_probe_best(page, probe)
        rows = state_ledger_rows_for_run(probe, run_id)
        if any(r.get("event") == "declaration_attempt" for r in rows):
            break
        attach_rv_page_listeners(page)
        page.wait_for_timeout(2000)

    identity = build_run_identity_from_ledger(rows, run_id=run_id)
    expected_token = str(identity.get("expected_token") or "")
    hydrated_room = str(identity.get("room_id") or "")
    attach_rv_page_listeners(page, expected_token=expected_token)

    decl_deadline = time.time() + 120.0
    while time.time() < decl_deadline:
        probe = poll_control_probe_best(page, probe)
        rows = state_ledger_rows_for_run(probe, run_id)
        identity = build_run_identity_from_ledger(rows, run_id=run_id)
        expected_token = str(identity.get("expected_token") or expected_token)
        hydrated_room = str(identity.get("room_id") or hydrated_room)
        if any(r.get("event") == "declaration_returned" for r in rows):
            break
        attach_rv_page_listeners(page, expected_token=expected_token)
        page.wait_for_timeout(2000)

    exp = wait_rv_control_expiration(page, timeout_s=95.0)
    exp["control_step"] = control_step
    reg = scrape_registry_localstorage(page)
    exp, reg = filter_observations_by_run_identity(exp, reg, identity)
    exp["harness_room_id"] = harness_room_id
    exp["hydrated_room_id"] = hydrated_room
    exp["instrumentation_epoch_id"] = instrumentation_epoch_id
    exp["expected_token_ledger"] = expected_token
    poll_until = time.time() + (180.0 if control_step == "RV3" else 60.0)
    from live_draft_solo_rv_declaration_ledger import infer_browser_send_ts_seconds, ledger_post_delivery_proof_satisfied

    browser_send_ts = infer_browser_send_ts_seconds(rows, expiration=exp)
    while time.time() < poll_until:
        probe = poll_control_probe_best(page, probe, run_id=run_id)
        rows = state_ledger_rows_for_run(probe, run_id)
        if control_step == "RV3":
            if any(str(r.get("event") or "") == "rv_mount_failed" for r in rows):
                break
            if browser_send_ts is None:
                browser_send_ts = infer_browser_send_ts_seconds(rows, expiration=exp)
            proven, _src = ledger_post_delivery_proof_satisfied(
                rows, expected_token=expected_token, browser_send_ts=browser_send_ts
            )
            if proven:
                break
            if any(str(r.get("event") or "") == "post_delivery_redeclaration" for r in rows):
                break
        elif any(str(r.get("event") or "") == "post_delivery_redeclaration" for r in rows):
            break
        attach_rv_page_listeners(page, expected_token=expected_token)
        page.wait_for_timeout(2000)
    probe = poll_control_probe_best(page, probe, run_id=run_id)
    rows = state_ledger_rows_for_run(probe, run_id)
    return exp, probe, reg, None, {
        "expected_token": expected_token,
        "hydrated_room_id": hydrated_room,
        "pre_expiration_rows": rows,
        "run_identity": identity,
        "instrumentation_epoch_id": instrumentation_epoch_id,
    }


def merge_ledger_rows(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Union ledger rows by event_sequence (runner polls may see partial DOM refreshes)."""
    merged: dict[int, dict[str, Any]] = {}
    fallback = 0
    for row in list(a or []) + list(b or []):
        if not isinstance(row, dict):
            continue
        seq = int(row.get("event_sequence") or 0)
        if seq <= 0:
            fallback += 1
            seq = -fallback
        merged[seq] = row
    return sorted(merged.values(), key=lambda r: (int(r.get("event_sequence") or 0), float(r.get("ts") or 0)))


def merge_probe_ledgers(best: dict[str, Any], fresh: dict[str, Any], *, run_id: str = "") -> dict[str, Any]:
    if not fresh:
        return best
    rid = str(run_id or fresh.get("run_id") or best.get("run_id") or "")
    best_rows = ledger_rows_for_run(best, rid) if rid else list(best.get("rows") or [])
    fresh_rows = ledger_rows_for_run(fresh, rid) if rid else list(fresh.get("rows") or [])
    merged_rows = merge_ledger_rows(best_rows, fresh_rows)
    out = dict(fresh)
    if merged_rows:
        out["rows"] = merged_rows
    parse = dict(out.get("_probe_parse") or {})
    if parse.get("decode_ok") or merged_rows:
        parse["decode_ok"] = bool(parse.get("decode_ok") or merged_rows)
        out["_probe_parse"] = parse
    try:
        win_count = fresh.get("_window_ledger_row_count")
        if win_count is not None:
            out["_window_ledger_row_count"] = win_count
    except Exception:
        pass
    return out


def scrape_control_probe(page) -> dict[str, Any]:
    from live_draft_solo_rv_control_probe import decode_control_probe_text_with_meta, playwright_ledger_scrape_script

    try:
        text = str(page.evaluate(playwright_ledger_scrape_script()) or "")
        win_meta = page.evaluate(
            """() => ({
              rowCount: (typeof window.__soloRvLedgerRowCount === 'number') ? window.__soloRvLedgerRowCount : null,
              hasB64: !!(window.__soloRvLedgerB64),
              runId: String(window.__soloRvLedgerRunId || ''),
            })"""
        )
        payload, meta = decode_control_probe_text_with_meta(text)
        out: dict[str, Any] = {"_probe_parse": meta, "rows": list(payload.get("rows") or [])}
        if isinstance(win_meta, dict):
            out["_window_ledger_row_count"] = win_meta.get("rowCount")
            out["_window_ledger_run_id"] = win_meta.get("runId")
        if payload.get("run_id"):
            out["run_id"] = payload.get("run_id")
        if payload.get("step"):
            out["step"] = payload.get("step")
        if meta.get("decode_ok") and out["rows"]:
            return {**payload, "_probe_parse": meta, **{k: out[k] for k in out if k.startswith("_window")}}
        return out
    except Exception as exc:
        return {"rows": [], "_probe_parse": {"decode_ok": False, "decode_error": f"scrape_exception:{exc}"}}


def poll_control_probe_best(page, best: dict[str, Any], *, run_id: str = "") -> dict[str, Any]:
    probe = scrape_control_probe(page)
    return merge_probe_ledgers(best, probe, run_id=run_id)


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


def _grade_rv_real_control_step(
    *,
    step: str,
    run_id: str,
    expiration: dict[str, Any],
    control_probe: dict[str, Any],
    reg: dict[str, Any],
    ledger_rows: list[dict[str, Any]],
    room_id: str,
    room_reuse_report: dict[str, Any],
    instrumentation_epoch_ms: float | None,
) -> dict[str, Any]:
    from live_draft_solo_rv_binding_ladder import (
        build_declaration_timeline,
        build_instance_identity_report,
        classify_root_cause,
        grade_rv_control_validity,
    )
    from live_draft_solo_rv_control_probe import ledger_to_declaration_rows
    from solo_rv_browser_observation import (
        build_run_identity_from_ledger,
        classify_rv2_binding_failure,
        combine_rv_control_verdicts,
        grade_rv_post_delivery_lane,
        grade_rv_python_binding,
        lifecycle_instrumentation_report,
        summarize_rv_control_browser,
        validate_rv_browser_delivery,
    )

    rows = ledger_to_declaration_rows(ledger_rows)
    identity = build_run_identity_from_ledger(ledger_rows, run_id=run_id, control_name=step)
    browser = summarize_rv_control_browser(expiration, reg, identity)
    filtered_exp = browser.pop("_filtered_expiration", expiration)
    browser.pop("_filtered_registry", None)
    expected = str(identity.get("expected_token") or expiration.get("expected_token_ledger") or "")
    from live_draft_solo_rv_declaration_ledger import infer_browser_send_ts_seconds

    browser_send_ts = infer_browser_send_ts_seconds(ledger_rows, expiration=filtered_exp)
    python_verdict, python_reason = grade_rv_python_binding(ledger_rows, expected_token=expected)
    delivery_ok, delivery_reason = validate_rv_browser_delivery(
        browser=browser,
        expiration=filtered_exp,
        control_probe_rows=ledger_rows,
        expected_token=expected,
    )
    post_delivery_lane, post_delivery_reason = grade_rv_post_delivery_lane(
        ledger_rows, expected_token=expected, browser_send_ts=browser_send_ts
    )
    lifecycle_lane, observability_warnings = lifecycle_instrumentation_report(
        browser, browser_delivery_ok=delivery_ok
    )
    binding_fail: tuple[str, str] | None = None
    if python_verdict.startswith("FAIL") and delivery_ok:
        if step in ("RV2", "RV3"):
            fail_v, fail_r = classify_rv2_binding_failure(
                browser=browser, declaration_rows=ledger_rows, python_verdict=python_verdict
            )
            if fail_v:
                binding_fail = (fail_v, fail_r)
        else:
            fail_verdict, fail_reason = grade_rv_control_validity(
                step=step,
                ledger=ledger_rows,
                declaration_rows=rows,
                browser=browser,
                expiration=filtered_exp,
            )
            if fail_verdict == "FAIL":
                binding_fail = (fail_verdict, fail_reason)
    overall, overall_reason, py_lane, br_lane, life_lane, warnings = combine_rv_control_verdicts(
        setup_invalid="",
        python_verdict=python_verdict,
        python_reason=python_reason,
        browser_delivery_ok=delivery_ok,
        browser_delivery_reason=delivery_reason,
        lifecycle_lane=lifecycle_lane,
        observability_warnings=observability_warnings,
        binding_fail=binding_fail,
    )
    root = classify_root_cause(
        validity_ok=delivery_ok,
        verdict=overall,
        browser=browser,
        declaration_rows=rows,
    )
    if binding_fail and binding_fail[0] == "FAIL":
        root = binding_fail[1]
    elif overall in ("PASS_RETURN_VALUE_DELIVERY", "PASS_WITH_OBSERVABILITY_WARN", "PASS"):
        root = ""
    if step == "RV3":
        from solo_rv_ladder_runner_state import rv3_room_continuity_invalid_reason

        room_inv = rv3_room_continuity_invalid_reason(ledger_rows)
        setup_inv = __import__(
            "solo_rv_ladder_runner_state",
            fromlist=["rv3_ledger_invalid_reason"],
        ).rv3_ledger_invalid_reason(ledger_rows)
        events = {str(r.get("event") or "") for r in ledger_rows}
        placement_lane = (
            "PASS"
            if not setup_inv
            and "rv3_production_placement_entered" in events
            and "declaration_returned" in events
            else ("FAIL" if setup_inv else "PENDING")
        )
        room_lane = "FAIL" if room_inv else "PASS"
        if (
            room_inv
            and placement_lane == "PASS"
            and delivery_ok
            and python_verdict == "PASS_RETURN_VALUE_DELIVERY"
        ):
            overall = "INVALID"
            overall_reason = room_inv
            root = ""
            binding_fail = None
        result_room = {
            "production_placement_verdict": placement_lane,
            "room_continuity_verdict": room_lane,
            "room_continuity_reason": room_inv or "PASS",
            "post_delivery_redeclaration_verdict": post_delivery_lane,
            "post_delivery_redeclaration_reason": post_delivery_reason,
        }
        if (
            not room_inv
            and placement_lane == "PASS"
            and delivery_ok
            and python_verdict == "PASS_RETURN_VALUE_DELIVERY"
            and post_delivery_lane == "PASS"
        ):
            overall = (
                "PASS_WITH_OBSERVABILITY_WARN"
                if observability_warnings
                else "PASS_RETURN_VALUE_DELIVERY"
            )
            overall_reason = (
                observability_warnings[0]
                if observability_warnings
                else "rv3_production_binding_and_post_delivery_proven"
            )
            root = ""
            binding_fail = None
        elif (
            not room_inv
            and placement_lane == "PASS"
            and delivery_ok
            and python_verdict == "PASS_RETURN_VALUE_DELIVERY"
            and post_delivery_lane.startswith("INCOMPLETE")
        ):
            overall = "INCOMPLETE_OBSERVABILITY_POST_DELIVERY_DECLARATION"
            overall_reason = post_delivery_reason or "INCOMPLETE_OBSERVABILITY"
        try:
            from solo_rv_ladder_runner_state import rv3_post_delivery_observation_boundary

            result_room["post_delivery_observation_boundary"] = rv3_post_delivery_observation_boundary(
                ledger_rows, browser_send_ts=browser_send_ts
            )
        except ImportError:
            pass
        result_room["overall_verdict"] = overall
    else:
        result_room = {}
    hydrated_row = next((r for r in ledger_rows if r.get("event") == "real_room_hydrated"), None)
    streamlit_session = ""
    for row in ledger_rows:
        sid = str(row.get("streamlit_session_id") or row.get("script_run_id") or "")
        if sid:
            streamlit_session = sid
            break
    overall_key = f"overall_{step.lower()}_control"
    return {
        "step": step,
        "run_id": run_id,
        "room_id": room_id,
        "created_room_id": room_id,
        "hydrated_room_id": str((hydrated_row or {}).get("room_id") or expiration.get("hydrated_room_id") or ""),
        "pick_index": (hydrated_row or {}).get("pick_index"),
        "deadline": (hydrated_row or {}).get("deadline"),
        "expected_token": expected,
        "streamlit_session_id": streamlit_session,
        "instrumentation_epoch_ms": instrumentation_epoch_ms or expiration.get("instrumentation_epoch_ms"),
        "instrumentation_epoch_id": expiration.get("instrumentation_epoch_id"),
        "verdict": overall,
        "reason": overall_reason,
        overall_key: overall,
        "python_binding_verdict": py_lane,
        "python_binding_reason": python_reason,
        "browser_delivery_verdict": br_lane,
        "browser_delivery_reason": delivery_reason,
        "browser_validity_verdict": br_lane,
        "browser_validity_reason": delivery_reason,
        "lifecycle_instrumentation_verdict": life_lane,
        "observability_warnings": warnings,
        "validity_ok": delivery_ok,
        "validity_reason": delivery_reason,
        "root_cause": root,
        "browser_summary": browser,
        "control_probe_ledger": ledger_rows,
        "instance_identity_report": build_instance_identity_report(filtered_exp, reg),
        "declaration_timeline": build_declaration_timeline({"rows": rows}),
        "expiration_summary": {
            "token_sent": filtered_exp.get("token_sent"),
            "observation_duration_s": filtered_exp.get("observation_duration_s"),
            "post_send_observation_s": filtered_exp.get("post_send_observation_s"),
            "client_stages_tail": list(filtered_exp.get("client_stages") or [])[-20:],
        },
        "room_reuse_report": room_reuse_report,
        "run_identity": identity,
        "expiration_skipped": bool(expiration.get("skipped_expiration") or expiration.get("hydration_failed")),
        **result_room,
    }


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
    room_reuse_report: dict[str, Any] = {}
    if step in ("RV1", "RV2", "RV3"):
        from solo_rv_ladder_runner_state import (
            build_rv1_room_reuse_report,
            build_rv3_production_placement_report,
            rv1_logical_setup_invalid_reason,
            rv3_production_placement_invalid_reason,
        )

        room_reuse_report = build_rv1_room_reuse_report(ledger_rows, run_id=run_id)
        if step == "RV3":
            dup_reason = rv3_production_placement_invalid_reason(ledger_rows)
            room_continuity_only = dup_reason == "INVALID_RV3_POST_DELIVERY_ROOM_STATE_LOST"
            if not dup_reason:
                dup_reason = rv1_logical_setup_invalid_reason(ledger_rows)
            elif room_continuity_only:
                dup_reason = ""
        else:
            dup_reason = rv1_logical_setup_invalid_reason(ledger_rows)
        placement_report: dict[str, Any] = {}
        if step == "RV3" and not dup_reason:
            placement_report = build_rv3_production_placement_report(ledger_rows)
        if dup_reason:
            browser = summarize_browser_events(expiration, reg)
            hydrated_row = next((r for r in ledger_rows if r.get("event") == "real_room_hydrated"), None)
            overall_key = f"overall_{step.lower()}_control"
            return {
                "step": step,
                "run_id": run_id,
                "room_id": room_id,
                "created_room_id": room_id,
                "hydrated_room_id": str((hydrated_row or {}).get("room_id") or ""),
                "pick_index": (hydrated_row or {}).get("pick_index"),
                "deadline": (hydrated_row or {}).get("deadline"),
                "expected_token": str((hydrated_row or {}).get("expected_token") or ""),
                "instrumentation_epoch_ms": instrumentation_epoch_ms or expiration.get("instrumentation_epoch_ms"),
                "instrumentation_epoch_id": expiration.get("instrumentation_epoch_id"),
                "verdict": "INVALID",
                "reason": dup_reason,
                overall_key: "INVALID",
                "python_binding_verdict": "PENDING",
                "python_binding_reason": dup_reason,
                "browser_delivery_verdict": "PENDING",
                "lifecycle_instrumentation_verdict": "PENDING",
                "observability_warnings": [],
                "validity_ok": False,
                "validity_reason": dup_reason,
                "root_cause": "",
                "room_reuse_report": room_reuse_report,
                "production_placement_report": placement_report if step == "RV3" else {},
                "browser_summary": browser,
                "control_probe_ledger": ledger_rows,
                "expiration_skipped": bool(
                    expiration.get("skipped_expiration") or expiration.get("hydration_failed")
                ),
            }
    rows = ledger_to_declaration_rows(ledger_rows)
    if step in ("RV1", "RV2", "RV3"):
        result = _grade_rv_real_control_step(
            step=step,
            run_id=run_id,
            expiration=expiration,
            control_probe=control_probe,
            reg=reg,
            ledger_rows=ledger_rows,
            room_id=room_id,
            room_reuse_report=room_reuse_report,
            instrumentation_epoch_ms=instrumentation_epoch_ms,
        )
        if step == "RV3":
            from solo_rv_ladder_runner_state import build_rv3_production_placement_report

            result["production_placement_report"] = build_rv3_production_placement_report(ledger_rows)
        return result
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
        "room_reuse_report": room_reuse_report if step == "RV1" else {},
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


def run_rv1_control_observation(
    page,
    run_id: str,
    *,
    harness_room_id: str,
    url_check: dict[str, Any],
    diagnostics: dict[str, Any],
    session_trace: list[dict[str, Any]],
    instrumentation_epoch_id: str = "",
) -> dict[str, Any]:
    return run_rv_control_observation(
        page,
        run_id,
        control_step="RV1",
        harness_room_id=harness_room_id,
        url_check=url_check,
        diagnostics=diagnostics,
        session_trace=session_trace,
        instrumentation_epoch_id=instrumentation_epoch_id,
    )


def _run_rv_direct(
    context,
    run_id: str,
    *,
    control_step: str,
    cloud_sha: str,
    cloud_build: str,
) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from solo_rv_browser_observation import (
        attach_rv_page_listeners,
        install_rv_browser_capture_before_navigation,
        new_instrumentation_epoch_id,
    )

    instrumentation_epoch_id = new_instrumentation_epoch_id(step=control_step)
    install_rv_browser_capture_before_navigation(
        context,
        run_id=run_id,
        instrumentation_epoch_id=instrumentation_epoch_id,
        control_name=control_step,
    )
    page = context.new_page()
    attach_rv_page_listeners(page)
    diagnostics = attach_page_diagnostics(page)
    session_trace: list[dict[str, Any]] = []
    control_url = rv_url(control_step, run_id)
    goto_and_wake(page, control_url, timeout_s=240)
    attach_rv_page_listeners(page)
    page.wait_for_timeout(8000)
    from solo_rv_ladder_runner_state import verify_rv_control_url

    url_check = verify_rv_control_url(page.url, step=control_step, run_id=run_id)
    url_check["requested_url_redacted"] = redact_url(control_url)
    url_check["final_url_redacted"] = redact_url(page.url)
    obs = run_rv_control_observation(
        page,
        run_id,
        control_step=control_step,
        harness_room_id="",
        url_check=url_check,
        diagnostics=diagnostics,
        session_trace=session_trace,
        instrumentation_epoch_id=instrumentation_epoch_id,
    )
    if obs.get("verdict") == "INVALID":
        result = {
            "step": control_step,
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
            "instrumentation_epoch_id": instrumentation_epoch_id,
            "expiration_skipped": True,
            "validity_ok": False,
            "validity_reason": obs.get("reason"),
            "root_cause": "",
            "observability_warnings": [],
        }
        result["cloud_sha"] = cloud_sha
        result["cloud_build"] = cloud_build
        result["artifact_path"] = str(OUT)
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
        control_step,
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
    result["artifact_path"] = str(OUT)
    result["log_hint"] = str(ROOT / "data" / f"solo_rv_{control_step.lower()}_run.out")
    page.close()
    return result


def run_rv1_direct(context, run_id: str, *, cloud_sha: str, cloud_build: str) -> dict[str, Any]:
    return _run_rv_direct(context, run_id, control_step="RV1", cloud_sha=cloud_sha, cloud_build=cloud_build)


def run_rv3_direct(context, run_id: str, *, cloud_sha: str, cloud_build: str) -> dict[str, Any]:
    return _run_rv_direct(context, run_id, control_step="RV3", cloud_sha=cloud_sha, cloud_build=cloud_build)


def run_rv2_direct(context, run_id: str, *, cloud_sha: str, cloud_build: str) -> dict[str, Any]:
    return _run_rv_direct(context, run_id, control_step="RV2", cloud_sha=cloud_sha, cloud_build=cloud_build)


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
            elif step == "RV2":
                result = run_rv2_direct(context, run_id, cloud_sha=verified_sha, cloud_build=verified_build)
            elif step == "RV3":
                result = run_rv3_direct(context, run_id, cloud_sha=verified_sha, cloud_build=verified_build)
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
            if v in ("PASS", "PASS_RETURN_VALUE_DELIVERY", "PASS_WITH_OBSERVABILITY_WARN"):
                continue
            if v not in ("PASS", "PASS_RETURN_VALUE_DELIVERY", "PASS_WITH_OBSERVABILITY_WARN"):
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
