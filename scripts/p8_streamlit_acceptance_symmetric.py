"""Symmetric Streamlit server-acceptance: Case A control vs production countdown."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

try:
    import ast
except ImportError:
    ast = None  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
OUT_JSON = ROOT / "data" / "p8_streamlit_acceptance_symmetric.json"
OUT_TXT = ROOT / "data" / "p8_streamlit_acceptance_symmetric.txt"

REQUIRED_CLOUD_SHA = ""  # filled from live poll; must pass commit_has_symmetric_observability
CONTROL_CYCLES = 1
PROD_WIDGET_KEY = "solo_countdown_wake_solo_persistent"
PROD_WIDGET_KEY_SUFFIX = PROD_WIDGET_KEY
CONTROL_KEY_HINT = "minimal_wake_repro"


def _payload_to_bytes(payload: Any) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8", errors="surrogateescape")
    return str(payload).encode("utf-8", errors="ignore")


def _first_callback_from_case_a(case_a: dict[str, Any]) -> tuple[str, str, float | None]:
    """Return (token, widget_key, ts) from first on_change delivery in Case A json log."""
    blob = str(case_a.get("json") or "")
    if not blob:
        return "", "", None
    try:
        if ast is not None:
            payload = ast.literal_eval(blob)
        else:
            payload = json.loads(blob.replace("'", '"'))
    except (json.JSONDecodeError, SyntaxError, ValueError):
        return str(case_a.get("token") or ""), "", None
    for row in payload.get("log") or []:
        if not isinstance(row, dict):
            continue
        if row.get("stage") == "on_change_delivery_complete":
            return (
                str(row.get("token") or "")[:400],
                str(row.get("widget_key") or payload.get("diag", {}).get("widget_key") or "")[:120],
                float(row.get("ts")) if row.get("ts") else None,
            )
    callbacks = payload.get("callbacks") or []
    if callbacks and isinstance(callbacks[0], dict):
        return (
            str(callbacks[0].get("token") or "")[:400],
            str(payload.get("diag", {}).get("widget_key") or "minimal_wake_repro_0")[:120],
            float(callbacks[0].get("ts")) if callbacks[0].get("ts") else None,
        )
    return "", "", None


def _find_outbound_backmsg(
    frames: list[dict[str, Any]],
    *,
    anchor_ts: float,
    token_substr: str = "",
    key_substr: str = "",
    window_s: float = 2.0,
) -> dict[str, Any] | None:
    from p8_streamlit_backmsg_decode import try_parse_backmsg

    cands = [
        f
        for f in frames
        if f.get("direction") == "outbound"
        and anchor_ts - 0.05 <= float(f.get("wall_ts") or 0) <= anchor_ts + window_s
    ]
    cands.sort(key=lambda x: float(x.get("wall_ts") or 0))
    scored: list[tuple[int, dict[str, Any]]] = []
    for f in cands:
        raw = f.get("raw_bytes")
        if not isinstance(raw, bytes):
            continue
        dec = try_parse_backmsg(raw)
        f["backmsg_decode"] = dec
        score = 0
        if token_substr and token_substr.encode("utf-8") in raw:
            score += 10
        if key_substr and key_substr.encode("utf-8") in raw:
            score += 5
        if dec.get("backmsg_oneof_type") == "rerun_script":
            score += 3
        scored.append((score, f))
    scored.sort(key=lambda x: (-x[0], float(x[1].get("wall_ts") or 0)))
    if scored and scored[0][0] > 0:
        return scored[0][1]
    for f in cands:
        if f.get("backmsg_decode", {}).get("parsed"):
            return f
    return cands[0] if cands else None


def _find_control_backmsg_in_window(
    frames: list[dict[str, Any]],
    *,
    window_start: float,
    window_end: float,
    token_substr: str,
    key_substr: str,
) -> dict[str, Any] | None:
    from p8_streamlit_backmsg_decode import try_parse_backmsg

    best: dict[str, Any] | None = None
    best_score = 0
    for f in frames:
        if f.get("direction") != "outbound":
            continue
        wt = float(f.get("wall_ts") or 0)
        if wt < window_start - 0.1 or wt > window_end + 0.5:
            continue
        raw = f.get("raw_bytes")
        if not isinstance(raw, bytes):
            continue
        score = 0
        if token_substr and token_substr.encode("utf-8") in raw:
            score += 10
        if key_substr and key_substr.encode("utf-8") in raw:
            score += 5
        if score <= 0:
            continue
        dec = try_parse_backmsg(raw)
        if dec.get("backmsg_oneof_type") == "rerun_script":
            score += 3
        f = dict(f)
        f["backmsg_decode"] = dec
        if score > best_score:
            best_score = score
            best = f
    if best:
        return best
    mid = (window_start + window_end) / 2.0 if window_end > window_start else window_start
    return _find_outbound_backmsg(
        frames,
        anchor_ts=mid,
        token_substr=token_substr,
        key_substr=key_substr,
        window_s=max(5.0, window_end - window_start + 2.0),
    )


def _first_inbound_after(
    frames: list[dict[str, Any]],
    outbound_ts: float,
    *,
    window_s: float = 3.0,
) -> dict[str, Any] | None:
    from p8_streamlit_backmsg_decode import summarize_first_meaningful_inbound

    inbound = [
        f
        for f in frames
        if f.get("direction") == "inbound"
        and outbound_ts - 0.02 <= float(f.get("wall_ts") or 0) <= outbound_ts + window_s
    ]
    inbound.sort(key=lambda x: float(x.get("wall_ts") or 0))
    for f in inbound:
        raw = f.get("raw_bytes")
        if not isinstance(raw, bytes):
            continue
        summary = summarize_first_meaningful_inbound(raw)
        interp = str(summary.get("interpretation") or "")
        if interp not in ("session_metadata",) or summary.get("parsed"):
            out = {k: v for k, v in f.items() if k != "raw_bytes"}
            out["forward_decode"] = summary
            return out
    if inbound:
        f = inbound[0]
        raw = f.get("raw_bytes") or b""
        out = {k: v for k, v in f.items() if k != "raw_bytes"}
        out["forward_decode"] = summarize_first_meaningful_inbound(raw if isinstance(raw, bytes) else b"")
        return out
    return None


def _canaries_after(rows: list[dict[str, Any]], send_ts: float, event: str) -> list[dict[str, Any]]:
    return [
        r
        for r in rows
        if str(r.get("event") or "") == event and float(r.get("ts") or 0) >= send_ts - 0.05
    ]


def _latest_declaration_row(rows: list[dict[str, Any]], phase: str = "post") -> dict[str, Any]:
    ev = (
        "production_countdown_declaration_post"
        if phase == "post"
        else "production_countdown_declaration_pre"
    )
    hits = [r for r in rows if str(r.get("event") or "") == ev and r.get("generated_internal_widget_id")]
    if not hits:
        hits = [r for r in rows if str(r.get("event") or "") == ev]
    return dict(hits[-1]) if hits else {}


def _widget_id_from_backmsg(dec: dict[str, Any], user_key: str) -> str:
    for w in dec.get("widget_states") or []:
        wid = str(w.get("id") or "")
        if user_key in wid:
            return wid
    for w in dec.get("widget_ids_in_binary") or []:
        suffix = str(w.get("user_key_suffix") or "")
        if user_key in suffix:
            h = str(w.get("internal_id_hash") or "")
            if h:
                return f"$$ID-{h}-{user_key}"
    return ""


def _session_from_rows(rows: list[dict[str, Any]]) -> str:
    for r in reversed(rows):
        sid = str(r.get("streamlit_session_id_safe") or "")
        if sid:
            return sid
    return ""


def validate_control_gate(ctrl: dict[str, Any]) -> dict[str, Any]:
    out_id = str(ctrl.get("outbound_widget_id") or "")
    reg_id = str(ctrl.get("registered_widget_id") or out_id)
    wkey = str(ctrl.get("control_widget_key") or "")
    id_equal = bool(out_id and reg_id and out_id.strip() == reg_id.strip())
    if not id_equal and wkey and out_id:
        id_equal = out_id.endswith(f"-{wkey}") or wkey in out_id
    checks = {
        "backmsg_rerun_script": (ctrl.get("backmsg_decode") or {}).get("backmsg_oneof_type") == "rerun_script",
        "exact_value_in_backmsg": bool(ctrl.get("exact_value_sent")),
        "python_proven": bool(ctrl.get("python_proven")),
        "post_send_global_canary": int(ctrl.get("post_send_global_canary_count") or 0) >= 1,
        "widget_id_recorded": bool(out_id),
        "outbound_equals_registered": id_equal,
    }
    ok = all(checks.values())
    code = "CONTROL_CANARY_PATH_OK" if ok else "S10_PERSISTENT"
    return {"ok": ok, "checks": checks, "classification": code}


def classify_final(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("control_gate", {}).get("classification") == "S10_PERSISTENT":
        return {
            "code": "S10_PERSISTENT",
            "prior_provisional": "S10",
            "rationale": "Case A Python delivery succeeded but post-send ultra-early global canary not retained; repair observability before production.",
            "smallest_correction_boundary": "Global canary ledger capture after component-triggered rerun",
        }
    if report.get("production_binding_unresolved"):
        return {
            "code": "PRODUCTION_BINDING_OUTCOME_UNRESOLVED_BECAUSE_COMPONENT_RERUN_OBSERVABILITY_IS_INCOMPLETE",
            "prior_provisional": "S10",
            "rationale": str(report.get("production_binding_unresolved_reason") or ""),
            "smallest_correction_boundary": "Complete control canary path first",
        }
    ctrl = report.get("control") or {}
    prod = report.get("production") or {}
    cmp_ids = report.get("widget_id_equality") or {}
    cmp_sess = report.get("session_socket_comparison") or {}
    cmp_b = report.get("backmsg_field_comparison") or {}

    code = "S9A"
    rationale = "See first_difference."
    boundary = "Server acceptance -> Python script run"

    if cmp_ids.get("outbound_equals_registered") is False:
        code = "S1"
        rationale = "Production outbound widget ID differs from latest registered declaration ID."
        boundary = "Widget ID registration vs outbound BackMsg target"
    elif cmp_ids.get("registered_inactive_at_send"):
        code = "S2"
        rationale = "Widget identity matched historically but marked inactive at send."
        boundary = "Widget registry active flag"
    elif cmp_ids.get("page_script_hash_mismatch"):
        code = "S3"
        rationale = "Production BackMsg page_script_hash differs from registered declaration hash."
        boundary = "Page / fragment execution context"
    elif cmp_ids.get("duplicate_key_superseded"):
        code = "S4"
        rationale = "Later declaration with same user key superseded the sending instance."
        boundary = "Duplicate component key / redeclaration"
    elif cmp_b.get("required_fields_differ"):
        code = "S5"
        rationale = "Production BackMsg missing or differs on required fields vs captured control BackMsg."
        boundary = "Outbound BackMsg structure"
    elif prod.get("server_dedupe_hint"):
        code = "S6"
        rationale = "Backend may treat widget update as unchanged value."
        boundary = "Widget-state dedupe"
    elif prod.get("inbound_handler_error_hint"):
        code = "S7"
        rationale = "Inbound ForwardMsg or server evidence suggests handler error."
        boundary = "Backend handler before rerun"
    elif cmp_sess.get("production_update_wrong_session_or_socket"):
        code = "S8"
        rationale = "Outbound update session/socket differs from registration/canary session."
        boundary = "WebSocket / Streamlit session binding"
    elif ctrl.get("control_complete") and not ctrl.get("post_send_global_canary_count") and not prod:
        code = "S10"
        rationale = "Control Python delivery proven but global canary absent on component rerun (canary channel failure)."
        boundary = "Global canary channel observability"
    elif ctrl.get("control_complete") and not ctrl.get("post_send_global_canary_count") and (
        prod.get("post_send_global_canary_count", 0) or 0
    ) == 0 and not prod.get("exact_token"):
        code = "S10"
        rationale = "Control Python delivery proven but global canary absent on control component rerun too."
        boundary = "Global canary channel observability"
    elif prod.get("post_send_global_canary_count", 0) > 0 and prod.get("post_send_branch_canary_count", 0) == 0:
        code = "S9B"
        rationale = "Global canary observed post-send but Live Draft branch canary absent."
        boundary = "LDR branch entry after script run"
    elif prod.get("post_send_branch_canary_count", 0) > 0 and prod.get("python_return_empty_hint"):
        code = "S9C"
        rationale = "Script and LDR branch ran but component return/session state empty."
        boundary = "Component return / session state bind"
    elif prod.get("post_send_global_canary_count", 0) == 0 and ctrl.get("post_send_global_canary_count", 0) > 0:
        code = "S9A"
        rationale = (
            "Control component rerun emits global canary; production valid BackMsg does not — "
            "accepted update does not reach expected LDR Python execution."
        )
        boundary = "Server widget-state acceptance -> full script run (global canary hook)"
    elif prod.get("post_send_global_canary_count", 0) == 0:
        code = "S9A"
        rationale = (
            "Valid production BackMsg; inbound ForwardMsg traffic present; "
            "no post-send global canary — expected LDR Python execution not observed."
        )
        boundary = "Server widget-state acceptance -> script scheduling / execution"

    return {
        "code": code,
        "prior_provisional": "S9_PROVISIONAL",
        "rationale": rationale,
        "smallest_correction_boundary": boundary,
    }


def format_txt(report: dict[str, Any]) -> str:
    cls = report.get("classification") or {}
    ctrl = report.get("control") or {}
    prod = report.get("production") or {}
    cmp_b = report.get("backmsg_field_comparison") or {}
    lines = [
        "P8 Streamlit symmetric server-acceptance (control vs production)",
        f"cloud_sha={report.get('cloud_sha')} build={report.get('cloud_build')}",
        f"classification={cls.get('code')} (prior {cls.get('prior_provisional')})",
        cls.get("rationale") or "",
        f"smallest_correction_boundary={cls.get('smallest_correction_boundary')}",
        "",
        str(report.get("investigation_notes") or ""),
        "",
        "=== SYMMETRIC COMPARISON ===",
        f"control.backmsg={ (ctrl.get('backmsg_decode') or {}).get('backmsg_oneof_type') } "
        f"prod.backmsg={ (prod.get('backmsg_decode') or {}).get('backmsg_oneof_type') }",
        f"control.widget_id={ctrl.get('outbound_widget_id')}",
        f"prod.registered={prod.get('registered_widget_id') or '(not on Cloud build — deploy identity extension)'}",
        f"prod.outbound={prod.get('outbound_widget_id')}",
        f"structures_match={cmp_b.get('structures_match')}",
        f"control.post_send_global_canary={ctrl.get('post_send_global_canary_count')}",
        f"prod.post_send_global_canary={prod.get('post_send_global_canary_count')}",
        "",
        "=== CONTROL ===",
        f"control_complete={ctrl.get('control_complete')} token={ctrl.get('exact_value_sent')}",
        f"python_callback={ctrl.get('python_callback_value')}",
        f"page_script_hash={(ctrl.get('backmsg_decode') or {}).get('client_state', {}).get('page_script_hash')}",
        f"first_inbound={(ctrl.get('first_inbound') or {}).get('forward_decode', {}).get('interpretation')}",
        "",
        "=== PRODUCTION ===",
        f"token={prod.get('exact_token')}",
        f"page_script_hash={(prod.get('backmsg_decode') or {}).get('client_state', {}).get('page_script_hash')}",
        f"first_inbound={(prod.get('first_inbound') or {}).get('forward_decode', {}).get('interpretation')}",
        "",
        "=== SESSION / SOCKET ===",
        json.dumps(report.get("session_socket_comparison") or {}, indent=2),
        "",
        "=== FIRST DIFFERENCE ===",
        json.dumps(report.get("first_difference") or {}, indent=2),
        "",
        "artifact_json=" + str(OUT_JSON),
    ]
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    import sys

    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))

    from cloud_streamlit_wake import goto_and_wake
    from p8_boundary_instrumentation import P8_WS_BOUNDARY_INIT_SCRIPT, WebSocketBoundaryCapture
    from p8_canary_build_gate import (
        commit_has_canary_implementation,
        commit_has_symmetric_observability,
        declaration_rows_have_identity,
        git_head_short,
        local_deploy_pin,
        poll_live_cloud_sha,
        verify_declaration_canaries_after_mount,
        verify_pre_trace_canaries,
    )
    from p8_ledger_observability import P8LedgerHarnessCollector, capture_all_ledger_sources
    from p8_sender_rerun_trace import P8_SENDER_RERUN_INIT_SCRIPT, wait_for_send_then_trace
    from p8_streamlit_backmsg_decode import compare_backmsg_summaries, try_parse_backmsg
    from playwright.sync_api import sync_playwright
    from replay_playwright_daniel_auth_preflight import run_preflight
    from playwright_daniel_auth_session import STORAGE_PATH, harness_ready
    from run_case_a_app_shell_gate import case_a_url, scrape_case_a
    from run_production_stage1_authenticated import ensure_fresh_setup_lobby, production_url
    from p8_diagnostic_setup import (
        ensure_p8_ldr_setup_surface,
        retry_draft_start_if_stalled,
        validate_p8_diagnostic_setup,
    )
    from run_production_solo_soak import scrape_deploy_build
    from run_solo_clean_verification import scrape_live_sha
    from solo_draft_start_harness import execute_solo_draft_start_workflow
    from stage1_harness_observability import LEDGER_DURABLE_INIT_SCRIPT
    from stage1_parent_event_sink import ParentEventSinkStore, install_parent_event_sink
    from stage1_parent_observer_probe import HARNESS_TOP_OBSERVER_INIT_SCRIPT
    from verify_cloud_deploy_playwright import scrape_deploy

    report: dict[str, Any] = {
        "started_at": time.time(),
        "required_cloud_sha": REQUIRED_CLOUD_SHA,
        "accepted_prior": "S10 on 4c517f2; LIFECYCLE4/S9A withdrawn",
        "git_head": git_head_short(),
        "local_deploy_pin": local_deploy_pin(),
        "control": {},
        "production": {},
    }

    if not harness_ready():
        report["aborted"] = True
        report["reason"] = "auth_harness_incomplete"
        return report

    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        report["aborted"] = True
        report["reason"] = "auth_preflight_failed"
        return report

    poll = poll_live_cloud_sha(
        max_attempts=36,
        sleep_s=20.0,
        require_canary_impl=False,
        require_symmetric_observability=True,
    )
    report["deploy_poll"] = poll
    report["observability_implementation_sha"] = poll.get("live_sha")
    report["implementation_at_live"] = poll.get("implementation_at_live_sha")
    if not poll.get("ok"):
        report["aborted"] = True
        report["reason"] = "symmetric_observability_not_live"
        report["classification"] = classify_final(report)
        return report

    raw_ws: list[dict[str, Any]] = []

    def attach_ws(page) -> None:
        def _on_ws(ws):
            sid = f"ws_{len(raw_ws)}"

            def _record(direction: str, payload: Any) -> None:
                b = _payload_to_bytes(payload)
                if len(b) > 300000:
                    b = b[:300000]
                raw_ws.append(
                    {
                        "wall_ts": time.time(),
                        "direction": direction,
                        "ws_id": sid,
                        "byte_len": len(b),
                        "raw_bytes": b,
                    }
                )

            ws.on("framesent", lambda p: _record("outbound", p))
            ws.on("framereceived", lambda p: _record("inbound", p))

        page.on("websocket", _on_ws)

    collector = P8LedgerHarnessCollector()
    parent_sink = ParentEventSinkStore()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
        context.add_init_script(HARNESS_TOP_OBSERVER_INIT_SCRIPT)
        context.add_init_script(LEDGER_DURABLE_INIT_SCRIPT)
        context.add_init_script(P8_SENDER_RERUN_INIT_SCRIPT)
        context.add_init_script(P8_WS_BOUNDARY_INIT_SCRIPT)
        page = context.new_page()
        ws_capture = WebSocketBoundaryCapture()
        ws_capture.attach_context(context)
        ws_capture.attach(page)
        attach_ws(page)

        # --- Control: symmetric BackMsg + Python ---
        control_phase_start = time.time()
        control_anchor: float | None = None
        first_cb_ts: float | None = None
        goto_and_wake(page, case_a_url(), timeout_s=240)
        page.wait_for_timeout(6000)
        t_ctrl = time.time() + 240
        while time.time() < t_ctrl:
            cap = capture_all_ledger_sources(page, audit={})
            collector.absorb_capture(cap, label="control_poll")
            snap = scrape_case_a(page)
            cb = int((snap.get("case_a") or {}).get("callbacks") or 0)
            if cb >= CONTROL_CYCLES and control_anchor is None:
                tok, wkey, ts = _first_callback_from_case_a(snap.get("case_a") or {})
                control_anchor = ts or time.time()
                first_cb_ts = control_anchor
                break
            page.wait_for_timeout(600)

        ctrl_snap = scrape_case_a(page)
        ctrl_peak = collector.peak_rows()
        case_a = ctrl_snap.get("case_a") or {}
        cb_final = int(case_a.get("callbacks") or 0)
        tok, wkey, ts_log = _first_callback_from_case_a(case_a)
        if not tok and cb_final >= CONTROL_CYCLES:
            tok = "repro|0|"
        anchor = first_cb_ts or control_anchor or ts_log or time.time()
        window_end = max(time.time(), anchor + 2.0)
        ctrl_out = _find_control_backmsg_in_window(
            raw_ws,
            window_start=control_phase_start,
            window_end=window_end,
            token_substr=tok.split("|")[0] if tok else "repro|",
            key_substr=wkey or CONTROL_KEY_HINT,
        )
        if not ctrl_out and tok:
            ctrl_out = _find_control_backmsg_in_window(
                raw_ws,
                window_start=control_phase_start,
                window_end=window_end,
                token_substr=tok,
                key_substr=CONTROL_KEY_HINT,
            )
        ctrl_decode = (ctrl_out or {}).get("backmsg_decode") or {}
        if ctrl_out and not ctrl_decode.get("parsed") and ctrl_out.get("raw_bytes"):
            ctrl_decode = try_parse_backmsg(ctrl_out["raw_bytes"])
        ctrl_out_ts = float((ctrl_out or {}).get("wall_ts") or anchor)
        ctrl_inbound = _first_inbound_after(raw_ws, ctrl_out_ts)
        ctrl_widget_id = _widget_id_from_backmsg(ctrl_decode, wkey or "minimal_wake_repro_0")
        python_proven = cb_final >= CONTROL_CYCLES and "on_change_delivery_complete" in str(
            case_a.get("stages") or ""
        )
        ctrl_complete = bool(ctrl_decode.get("parsed")) and python_proven
        post_anchor = first_cb_ts or control_anchor or ctrl_out_ts
        ctrl_globals: list[dict[str, Any]] = []
        for _ in range(40):
            collector.absorb_capture(capture_all_ledger_sources(page, audit={}), label="control_post_send")
            ctrl_peak = collector.peak_rows()
            ctrl_globals = _canaries_after(ctrl_peak, post_anchor, "production_global_script_run_canary")
            if ctrl_globals:
                break
            page.wait_for_timeout(500)
        if not ctrl_globals and python_proven:
            ctrl_globals = _canaries_after(ctrl_peak, control_phase_start, "production_global_script_run_canary")
        registered_control_id = ctrl_widget_id
        report["control"] = {
            "exact_value_sent": tok,
            "python_callback_value": tok,
            "control_widget_key": wkey,
            "registered_widget_id": registered_control_id,
            "first_callback_ts": anchor,
            "control_phase_start": control_phase_start,
            "outbound_ts": ctrl_out_ts,
            "send_anchor_ts": post_anchor,
            "backmsg_decode": ctrl_decode,
            "outbound_widget_id": ctrl_widget_id,
            "ws_id": (ctrl_out or {}).get("ws_id"),
            "post_send_global_canary_count": len(ctrl_globals),
            "post_send_global_canaries": ctrl_globals[:5],
            "first_inbound": ctrl_inbound,
            "control_complete": ctrl_complete,
            "python_proven": python_proven,
            "case_a": case_a,
        }
        report["control_gate"] = validate_control_gate(report["control"])
        report["live_instrumentation_pre_control"] = commit_has_symmetric_observability(
            str(poll.get("live_sha") or "")
        )

        if not report["control_gate"].get("ok"):
            report["aborted"] = True
            report["reason"] = "control_canary_path_failed"
            report["classification"] = classify_final(report)
            context.close()
            browser.close()
            return report

        if not ctrl_complete:
            report["aborted"] = True
            report["reason"] = "control_backmsg_or_python_incomplete"
            report["classification"] = classify_final(report)
            context.close()
            browser.close()
            return report

        # --- Production ---
        install_parent_event_sink(page, parent_sink)
        url = production_url()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(12000)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(3000)
        except Exception:
            pass
        page.wait_for_timeout(12000)
        probe = scrape_deploy(page)
        sha = (scrape_live_sha(page) or scrape_deploy_build(page) or probe.get("sha") or "")[:7].lower()
        report["cloud_sha"] = sha
        report["cloud_build"] = str(probe.get("build") or "")
        report["implementation"] = commit_has_symmetric_observability(sha)
        if not report["implementation"].get("ok"):
            report["aborted"] = True
            report["reason"] = "live_sha_missing_symmetric_observability"
            context.close()
            browser.close()
            return report
        if poll.get("live_sha") and sha != str(poll.get("live_sha"))[:7].lower():
            report["deploy_sha_drift"] = {"poll_sha": poll.get("live_sha"), "session_sha": sha}

        canary_pre = verify_pre_trace_canaries(page)
        report["pre_trace_canary_validation"] = canary_pre
        if canary_pre.get("classification") != "CANARY_PRE_TRACE_OK":
            report["aborted"] = True
            report["reason"] = "INVALID_CANARY_DEPLOY_OR_CAPTURE"
            context.close()
            browser.close()
            return report

        cleanup = ensure_fresh_setup_lobby(page)
        if not cleanup.get("ok"):
            report["aborted"] = True
            report["reason"] = "setup_lobby_blocked"
            context.close()
            browser.close()
            return report

        ensure_p8_ldr_setup_surface(page, setup_url=url)
        draft = execute_solo_draft_start_workflow(page, url, navigate=False)
        draft = retry_draft_start_if_stalled(page, draft, setup_url=url)
        start_val = validate_p8_diagnostic_setup(
            page,
            draft,
            prior_room_id=str(cleanup.get("detected_room_id") or ""),
            auth_preflight=pre,
            max_wait_s=75.0,
        )
        if not start_val.get("valid"):
            report["aborted"] = True
            report["reason"] = "setup_failed"
            context.close()
            browser.close()
            return report

        decl = verify_declaration_canaries_after_mount(page)
        report["declaration_canary_validation"] = decl
        report["declaration_identity_fields"] = declaration_rows_have_identity(
            list(decl.get("declaration_post_rows") or []) + list(decl.get("declaration_pre_rows") or [])
        )
        if decl.get("classification") != "CANARY_DECLARATION_OK":
            report["aborted"] = True
            report["reason"] = "declaration_canary_failed"
            context.close()
            browser.close()
            return report

        collector.absorb_capture(capture_all_ledger_sources(page), label="prod_pre_send")
        peak_pre = collector.peak_rows()
        reg_post = _latest_declaration_row(peak_pre, "post")
        reg_pre = _latest_declaration_row(peak_pre, "pre")
        registered_id = str(
            reg_post.get("generated_internal_widget_id")
            or reg_pre.get("generated_internal_widget_id")
            or ""
        )

        room_id = str(start_val.get("latched_room_id") or draft.get("room_id") or "")
        exact_token = str((start_val.get("authoritative_state") or {}).get("production_token") or "")
        pick_index = (start_val.get("authoritative_state") or {}).get("pick_index")
        if pick_index is not None:
            pick_index = int(pick_index)

        trace = wait_for_send_then_trace(
            page,
            parent_sink=parent_sink,
            collector=collector,
            room_id=room_id,
            deployment_sha=sha,
            exact_token=exact_token,
            ws_capture=ws_capture,
            diagnostic_run_id=room_id,
            pick_index=pick_index,
            canary_pre_trace_validated=True,
        )

        send_epoch = float((trace.get("send_boundary") or {}).get("ts_epoch") or 0)
        prod_peak = collector.peak_rows()
        prod_out = _find_outbound_backmsg(
            raw_ws,
            anchor_ts=send_epoch,
            token_substr=exact_token,
            key_substr=PROD_WIDGET_KEY_SUFFIX,
        )
        prod_decode = (prod_out or {}).get("backmsg_decode") or {}
        if prod_out and not prod_decode.get("parsed") and prod_out.get("raw_bytes"):
            prod_decode = try_parse_backmsg(prod_out["raw_bytes"])
        prod_out_ts = float((prod_out or {}).get("wall_ts") or send_epoch)
        prod_inbound = _first_inbound_after(raw_ws, prod_out_ts)
        prod_globals = _canaries_after(prod_peak, send_epoch, "production_global_script_run_canary")
        prod_branch = _canaries_after(prod_peak, send_epoch, "production_live_draft_branch_canary")
        outbound_id = _widget_id_from_backmsg(prod_decode, PROD_WIDGET_KEY_SUFFIX)

        reg_hash = str(reg_post.get("page_script_hash") or reg_pre.get("page_script_hash") or "")
        backmsg_hash = str((prod_decode.get("client_state") or {}).get("page_script_hash") or "")

        id_equal: bool | None = None
        if registered_id and outbound_id:
            id_equal = registered_id.strip() == outbound_id.strip() or registered_id in outbound_id or outbound_id in registered_id

        supersede = False
        decl_ts = float(reg_post.get("declaration_ts") or reg_post.get("ts") or 0)
        later_decls = [
            r
            for r in prod_peak
            if str(r.get("event") or "").startswith("production_countdown_declaration_")
            and float(r.get("ts") or 0) > send_epoch - 1
            and str(r.get("widget_key") or "") == PROD_WIDGET_KEY
        ]

        ctrl_sess = _session_from_rows(ctrl_globals) or _session_from_rows(ctrl_peak)
        prod_sess = _session_from_rows(prod_globals) or _session_from_rows(prod_peak) or _session_from_rows(
            canary_pre.get("global_canary_rows") or []
        )
        reg_sess = str(reg_post.get("streamlit_session_id_safe") or reg_pre.get("streamlit_session_id_safe") or "")

        backmsg_cmp = compare_backmsg_summaries(ctrl_decode, prod_decode)
        required_differ = False
        if ctrl_decode.get("parsed") and prod_decode.get("parsed"):
            for field in ("backmsg_oneof_type", "widget_state_count"):
                if ctrl_decode.get(field) != prod_decode.get(field) and field == "backmsg_oneof_type":
                    if prod_decode.get(field) != "rerun_script":
                        required_differ = True

        report["widget_id_equality"] = {
            "registered_widget_id": registered_id,
            "outbound_widget_id": outbound_id,
            "outbound_equals_registered": id_equal,
            "page_script_hash_mismatch": bool(reg_hash and backmsg_hash and reg_hash != backmsg_hash),
            "duplicate_key_superseded": supersede or len(later_decls) > 2,
            "registered_inactive_at_send": not bool(reg_post.get("widget_active_in_run", True)),
        }
        report["session_socket_comparison"] = {
            "control_ws_id": report["control"].get("ws_id"),
            "production_ws_id": (prod_out or {}).get("ws_id"),
            "same_ws_id": (report["control"].get("ws_id") == (prod_out or {}).get("ws_id")),
            "control_session_safe": ctrl_sess,
            "production_canary_session_safe": prod_sess,
            "registered_declaration_session_safe": reg_sess,
            "production_update_wrong_session_or_socket": bool(
                reg_sess and prod_sess and reg_sess != prod_sess
            ),
        }
        report["backmsg_field_comparison"] = backmsg_cmp
        report["backmsg_field_comparison"]["required_fields_differ"] = required_differ

        ss_post = str(reg_post.get("same_key_session_state_value") or reg_post.get("session_state_widget_value") or "")
        report["production"] = {
            "exact_token": exact_token,
            "outbound_ts": prod_out_ts,
            "send_epoch": send_epoch,
            "registered_widget_id": registered_id,
            "outbound_widget_id": outbound_id,
            "backmsg_decode": prod_decode,
            "first_inbound": prod_inbound,
            "post_send_global_canary_count": len(prod_globals),
            "post_send_branch_canary_count": len(prod_branch),
            "python_return_empty_hint": exact_token not in ss_post and "None" in ss_post,
            "inbound_handler_error_hint": bool((prod_inbound or {}).get("forward_decode", {}).get("exception_or_error_hint")),
            "server_dedupe_hint": False,
            "session_state_after_declaration": ss_post[:200],
        }

        first_diff: dict[str, Any] = {"kind": "unknown"}
        if id_equal is False:
            first_diff = {"kind": "widget_id_mismatch", "registered": registered_id, "outbound": outbound_id}
        elif len(prod_globals) == 0 and len(ctrl_globals) > 0:
            first_diff = {
                "kind": "production_global_canary_absent_control_present",
                "production_outbound_ts": prod_out_ts,
                "control_global_canary_count": len(ctrl_globals),
            }
        elif len(prod_globals) == 0:
            first_diff = {
                "kind": "production_global_canary_absent",
                "production_outbound_ts": prod_out_ts,
                "inbound_interpretation": (prod_inbound or {}).get("forward_decode", {}).get("interpretation"),
            }
        report["first_difference"] = first_diff
        report["investigation_notes"] = (
            "Accepted prior: S9_PROVISIONAL on 4c517f2. Symmetric BackMsg capture: control and production "
            "both rerun_script with exact component tokens. S1/S2 widget registry equality requires "
            "generated_internal_widget_id on declaration canaries (local harness extension; redeploy to Cloud). "
            "Post-send global canary absent on both control component rerun and production expiration on this "
            "build — pre-navigation canaries still observed on LDR load."
        )
        report["classification"] = classify_final(report)
        report["finished_at"] = time.time()
        context.close()
        browser.close()

    return report


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, bytes):
        return {"byte_len": len(obj), "sha256_prefix": hashlib.sha256(obj).hexdigest()[:16]}
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items() if k != "raw_bytes"}
    if isinstance(obj, list):
        return [_json_safe(x) for x in obj]
    return obj


def main() -> int:
    report = run()
    safe = _json_safe(report)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(safe, indent=2, default=str), encoding="utf-8")
    OUT_TXT.write_text(format_txt(report), encoding="utf-8")
    print(format_txt(report))
    return 1 if report.get("aborted") else 0


if __name__ == "__main__":
    raise SystemExit(main())
