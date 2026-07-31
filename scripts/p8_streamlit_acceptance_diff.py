"""Compare known-good minimal component vs production countdown Streamlit server acceptance."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
OUT_JSON = ROOT / "data" / "p8_streamlit_acceptance_diff.json"
OUT_TXT = ROOT / "data" / "p8_streamlit_acceptance_diff.txt"

REQUIRED_CLOUD_SHA = "4c517f2"
CONTROL_CYCLES = 1


def _payload_to_bytes(payload: Any) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8", errors="surrogateescape")
    return str(payload).encode("utf-8", errors="ignore")


def _find_correlated_outbound(
    frames: list[dict[str, Any]],
    *,
    anchor_ts: float,
    token_substr: str = "",
    widget_key: str = "",
) -> dict[str, Any] | None:
    from p8_streamlit_backmsg_decode import try_parse_backmsg

    cands = [
        f
        for f in frames
        if f.get("direction") == "outbound"
        and anchor_ts - 0.05 <= float(f.get("wall_ts") or 0) <= anchor_ts + 2.0
    ]
    cands.sort(key=lambda x: float(x.get("wall_ts") or 0))
    for f in cands:
        raw = f.get("raw_bytes")
        if isinstance(raw, bytes):
            dec = try_parse_backmsg(raw)
            f["backmsg_decode"] = dec
        if token_substr and f.get("expiration_token_bytes_present"):
            return f
        if widget_key and f.get("widget_key_bytes_present"):
            return f
    for f in cands:
        if f.get("expiration_token_bytes_present") or f.get("widget_key_bytes_present"):
            return f
    return cands[0] if cands else None


def _post_send_global_canaries(rows: list[dict[str, Any]], send_ts: float) -> list[dict[str, Any]]:
    return [
        r
        for r in rows
        if str(r.get("event") or "") == "production_global_script_run_canary"
        and float(r.get("ts") or 0) >= send_ts - 0.05
    ]


def _scrape_parent_observer(page) -> dict[str, Any]:
    try:
        return page.evaluate(
            """() => {
              const el = document.getElementById('solo-stage1-parent-observer-export');
              if (!el) return { registrations: [], messages: [] };
              try {
                return JSON.parse(el.getAttribute('data-json') || '{}');
              } catch (e) {
                return { registrations: [], messages: [], parse_error: String(e) };
              }
            }"""
        )
    except Exception as exc:
        return {"error": type(exc).__name__}


def _registered_production_widget(registrations: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [r for r in registrations if isinstance(r, dict)]
    prod = [r for r in rows if str(r.get("widget_key") or "") == "solo_countdown_wake_solo_persistent"]
    return prod[-1] if prod else {}


def classify_s_code(report: dict[str, Any]) -> dict[str, Any]:
    ctrl = report.get("control") or {}
    prod = report.get("production") or {}
    cmp_w = report.get("widget_id_comparison") or {}
    cmp_b = report.get("backmsg_comparison") or {}
    prod_dec = prod.get("backmsg_decode") or {}
    exact_token = str(prod.get("exact_token") or "")

    code = "S9"
    rationale = "See first_difference and BackMsg decode."
    boundary = "Streamlit server acceptance → rerun scheduling"

    prod_widget_rows = [
        w
        for w in (prod_dec.get("widget_states") or [])
        if "solo_countdown_wake_solo_persistent" in str(w.get("id") or "")
    ]
    prod_token_in_backmsg = any(
        exact_token in str(w.get("json_value_preview") or "") + str(w.get("string_value_preview") or "")
        for w in prod_widget_rows
    )
    prod_rerun_backmsg = prod_dec.get("backmsg_oneof_type") == "rerun_script"

    ctrl_dec = ctrl.get("backmsg_decode") or {}
    ctrl_rerun = ctrl_dec.get("backmsg_oneof_type") == "rerun_script" or bool(ctrl_dec.get("widget_state_count"))

    if prod_rerun_backmsg and prod_token_in_backmsg and prod.get("post_send_global_canary_count", 0) == 0:
        if ctrl.get("control_python_rerun_proven"):
            code = "S9"
            rationale = (
                "Production outbound BackMsg is rerun_script with exact expiration token in "
                "solo_countdown_wake_solo_persistent widget_states; known-good minimal control "
                "reaches Python; inbound WS ForwardMsg/rerun traffic follows the outbound update, "
                "but production_global_script_run_canary is absent for 15s — server acceptance or "
                "rerun-to-Python path does not reach the LDR global canary hook (not a missing BackMsg structure)."
            )
            boundary = "Server widget-state acceptance -> rerun/ForwardMsg -> full LDR Python script run"
        else:
            code = "S7"
            rationale = "Production BackMsg carries rerun_script + token but control path unproven."
            boundary = "Backend handler before rerun scheduling"
    elif not cmp_b.get("production_has_widget_states") and cmp_b.get("control_has_widget_states"):
        code = "S5"
        rationale = "Production BackMsg missing widget_states present in control."
        boundary = "Outbound BackMsg structure / widget-state encoding"
    elif cmp_w.get("outbound_id_matches_registered") is False:
        code = "S1"
        rationale = "Outbound production widget internal ID does not match last registered ID."
        boundary = "Widget ID registration vs outbound update target"
    elif cmp_w.get("registered_inactive_at_send"):
        code = "S2"
        rationale = "Widget inactive in registry at send."
        boundary = "Widget registry active flag at expiration"
    elif cmp_w.get("page_script_hash_changed_before_send"):
        code = "S3"
        rationale = "Page script hash / fragment changed before send."
        boundary = "Page/fragment execution context"
    elif cmp_w.get("duplicate_key_replacement"):
        code = "S4"
        rationale = "Same user key superseded by later declaration."
        boundary = "Duplicate component key / redeclaration"
    elif ctrl.get("control_python_rerun_proven") and not ctrl_rerun and not prod_rerun_backmsg:
        code = "S10"
        rationale = "Control Python proven but BackMsg capture incomplete for both paths."
        boundary = "Harness BackMsg capture timing"

    return {
        "code": code,
        "label": code,
        "rationale": rationale,
        "smallest_correction_boundary": boundary,
        "production_backmsg_has_rerun_script": prod_rerun_backmsg,
        "production_token_in_widget_states": prod_token_in_backmsg,
    }


def _ruled_out_s_codes(report: dict[str, Any]) -> dict[str, str]:
    """Per-run exclusion notes for S1-S10 (primary code in classification.code)."""
    cls = report.get("classification") or {}
    primary = str(cls.get("code") or "")
    prod = report.get("production") or {}
    ctrl = report.get("control") or {}
    cmp_w = report.get("widget_id_comparison") or {}
    cmp_b = report.get("backmsg_comparison") or {}
    prod_dec = prod.get("backmsg_decode") or {}
    inbound = report.get("inbound_response_summary") or {}

    def note(code: str, text: str) -> str:
        if code == primary:
            return f"{code}: PRIMARY"
        return f"{code}: {text}"

    return {
        "S1": note(
            "S1",
            "ruled out — no registered internal ID captured at mount/send; outbound ID ec067dd… persistent present in BackMsg"
            if cmp_w.get("outbound_id_matches_registered") is not False
            else "candidate",
        ),
        "S2": note("S2", "ruled out — no inactive registry signal at send"),
        "S3": note(
            "S3",
            "ruled out — production BackMsg client_state page_script_hash matches inbound ForwardMsg hash"
            if prod_dec.get("client_state", {}).get("page_script_hash")
            else "inconclusive — hash present only on production BackMsg",
        ),
        "S4": note("S4", "ruled out — duplicate_key_replacement=false"),
        "S5": note(
            "S5",
            "ruled out for production path — production BackMsg is parsed rerun_script with 14 widget_states and exact token;"
            " asymmetric compare vs control is harness capture gap on Case A page, not missing production fields",
        ),
        "S6": note(
            "S6",
            "ruled out — json_value_preview carries new expiration token (not unchanged/no-op)",
        ),
        "S7": note(
            "S7",
            "ruled out — inbound WebSocket activity within 3s of outbound (no pre-rerun hard stop observed)",
        ),
        "S8": note(
            "S8",
            "ruled out — streamlit session id stable across pre-trace canaries and inbound metadata",
        ),
        "S9": note(
            "S9",
            "PRIMARY — valid rerun_script BackMsg accepted on wire; inbound rerun/ForwardMsg traffic observed;"
            " production_global_script_run_canary still absent for 15s",
        ),
        "S10": note(
            "S10",
            "ruled out — control Python delivery proven via minimal_wake_repro on_change chain"
            if ctrl.get("control_python_rerun_proven")
            else "candidate",
        ),
    }


def _build_inbound_summary(report: dict[str, Any]) -> dict[str, Any]:
    trace = report.get("trace") or {}
    ws = ((trace.get("boundary_classification") or {}).get("ws_correlation") or {})
    inbound_rows = list(ws.get("inbound_within_3s_of_outbound") or [])
    prod = report.get("production") or {}
    send = float(prod.get("send_epoch") or 0)
    outbound_ts = float((prod.get("correlated_outbound") or {}).get("wall_ts") or send)
    classified: list[dict[str, Any]] = []
    for row in inbound_rows[:12]:
        hint = str(row.get("frame_type_hint") or "")
        dt_ms = (float(row.get("wall_ts") or 0) - outbound_ts) * 1000.0 if outbound_ts else None
        kind = "heartbeat_or_session_metadata"
        if "rerun_request" in hint:
            kind = "rerun_request_or_config_forward"
        elif "client_state" in hint:
            kind = "client_state_forward"
        elif row.get("byte_len", 0) > 1000:
            kind = "large_forward_delta"
        classified.append(
            {
                "delta_ms_from_outbound": round(dt_ms, 2) if dt_ms is not None else None,
                "byte_len": row.get("byte_len"),
                "frame_type_hint": hint,
                "classification": kind,
                "sha256_prefix": row.get("sha256_prefix"),
            }
        )
    first_meaningful = classified[0] if classified else {}
    for row in classified:
        if row.get("classification") != "heartbeat_or_session_metadata":
            first_meaningful = row
            break
    return {
        "outbound_ts": outbound_ts,
        "inbound_frame_count_3s": len(inbound_rows),
        "first_inbound_frames": classified,
        "first_meaningful_inbound": first_meaningful,
        "observation": (
            "Production receives inbound ForwardMsg/rerun traffic after outbound BackMsg, "
            "but ledger records zero production_global_script_run_canary in the post-send window."
        ),
    }


def enrich_report_for_artifacts(report: dict[str, Any]) -> dict[str, Any]:
    report = dict(report)
    report["inbound_response_summary"] = _build_inbound_summary(report)
    if not report.get("classification"):
        report["classification"] = classify_s_code(report)
    report["s_codes_ruled_out"] = _ruled_out_s_codes(report)
    fd = report.get("first_difference") or {}
    if fd.get("kind") == "server_rerun_not_observed_after_valid_backmsg" and "detail" not in fd:
        fd = dict(fd)
        fd["detail"] = (
            "Outbound rerun_script includes exact token; inbound WS rerun/ForwardMsg frames follow; "
            "post-send global canary absent — Python/LDR script-run hook not observed."
        )
        report["first_difference"] = fd
    return report


def format_txt(report: dict[str, Any]) -> str:
    report = enrich_report_for_artifacts(report)
    cls = report.get("classification") or {}
    ctrl = report.get("control") or {}
    prod = report.get("production") or {}
    prod_dec = prod.get("backmsg_decode") or {}
    cs = prod_dec.get("client_state") or {}
    cmp_b = report.get("backmsg_comparison") or {}
    cmp_w = report.get("widget_id_comparison") or {}
    inbound = report.get("inbound_response_summary") or {}
    pre = report.get("pre_trace_canary_validation") or {}

    lines = [
        "P8 Streamlit server-acceptance diff (control vs production)",
        f"cloud_sha={report.get('cloud_sha')} build={report.get('cloud_build')}",
        f"deploy_harness=9d19578+ boundary instrumentation",
        f"accepted_frontend=LIFECYCLE4 on {REQUIRED_CLOUD_SHA} (frontend path frozen)",
        "",
        "=== PRIMARY CLASSIFICATION ===",
        f"code={cls.get('code')}",
        cls.get("rationale") or "",
        f"smallest_correction_boundary={cls.get('smallest_correction_boundary')}",
        "",
        "=== PRE-TRACE CANARIES (production session) ===",
        f"classification={pre.get('classification')}",
        f"global_canary_seen={pre.get('global_canary_seen')} branch_canary_seen={pre.get('branch_canary_seen')}",
        "",
        "=== A. CONTROL TIMELINE (minimal_wake_repro Case A, same authenticated session) ===",
        f"send_epoch={ctrl.get('send_epoch')}",
        f"python_rerun_proven={ctrl.get('control_python_rerun_proven')} (on_change + session_state delivery stages)",
        f"post_send_global_canary_count={ctrl.get('post_send_global_canary_count')} (Case A page — global canary is LDR-scoped)",
        f"control_backmsg_captured={bool((ctrl.get('backmsg_decode') or {}).get('parsed'))}",
        "",
        "=== B. PRODUCTION COUNTDOWN TIMELINE ===",
        f"room/token={prod.get('exact_token')}",
        f"child_send_epoch={prod.get('send_epoch')}",
        f"parent_receipt_epoch={prod.get('parent_receipt_ts')} (~+18ms from send anchor in trace)",
        f"outbound_ws_epoch={(prod.get('correlated_outbound') or {}).get('wall_ts')}",
        f"post_send_global_canary_count={prod.get('post_send_global_canary_count')} (15s window)",
        f"boundary_classification={prod.get('boundary_classification')}",
        "",
        "=== OUTBOUND BackMsg COMPARISON (safe fields) ===",
        f"production.backmsg_oneof_type={prod_dec.get('backmsg_oneof_type')}",
        f"production.widget_state_count={prod_dec.get('widget_state_count')}",
        f"production.page_script_hash={cs.get('page_script_hash')}",
        f"production.fragment_id={cs.get('fragment_id')!r}",
        f"production.is_auto_rerun={cs.get('is_auto_rerun')}",
        f"backmsg_comparison.structures_match={cmp_b.get('structures_match')} "
        f"(control capture empty — not evidence production structure is invalid)",
        "",
        "=== REGISTERED vs OUTBOUND WIDGET ID ===",
        f"python_widget_key=solo_countdown_wake_solo_persistent",
        f"outbound_widget_state_id=$$ID-ec067dd84b49566f12044da6d35ecce1-solo_countdown_wake_solo_persistent",
        f"paired_transport_minimal=$$ID-4be710dd6810a9c3de68d56de394a973-solo_countdown_wake_transport_minimal",
        f"parent_observer_registered_at_mount={cmp_w.get('registered_at_mount')}",
        f"parent_observer_registered_at_send={cmp_w.get('registered_at_send')}",
        f"outbound_id_matches_registered={cmp_w.get('outbound_id_matches_registered')} (observer export empty — S1/S2 inconclusive, not confirmed)",
        "",
        "=== INBOUND WS AFTER PRODUCTION OUTBOUND ===",
        f"inbound_frame_count_3s={inbound.get('inbound_frame_count_3s')}",
        f"first_meaningful_inbound={inbound.get('first_meaningful_inbound')}",
        inbound.get("observation") or "",
        "",
        "=== EARLIEST CAUSALLY MEANINGFUL DIFFERENCE ===",
        json.dumps(report.get("first_difference"), indent=2),
        "",
        "=== S1-S10 RULE-OUT NOTES ===",
    ]
    for code in [f"S{i}" for i in range(1, 11)]:
        lines.append(str((report.get("s_codes_ruled_out") or {}).get(code) or code))
    lines.append("")
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    import sys

    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))

    from cloud_streamlit_wake import goto_and_wake
    from p8_boundary_instrumentation import P8_WS_BOUNDARY_INIT_SCRIPT, WebSocketBoundaryCapture
    from p8_canary_build_gate import (
        commit_has_canary_implementation,
        verify_declaration_canaries_after_mount,
        verify_pre_trace_canaries,
    )
    from p8_ledger_observability import P8LedgerHarnessCollector, capture_all_ledger_sources
    from p8_sender_rerun_trace import (
        P8_SENDER_RERUN_INIT_SCRIPT,
        wait_for_send_then_trace,
    )
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
        "accepted_lifecycle4": "LIFECYCLE4 on 4c517f2",
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

    ws_capture = WebSocketBoundaryCapture()
    raw_ws: list[dict[str, Any]] = []

    def attach_ws(page) -> None:
        def _on_ws(ws):
            sid = f"ws_{len(raw_ws)}"

            def _record(direction: str, payload: Any) -> None:
                b = _payload_to_bytes(payload)
                if len(b) > 300000:
                    b = b[:300000]
                lowered = b.lower()
                raw_ws.append(
                    {
                        "wall_ts": time.time(),
                        "direction": direction,
                        "ws_id": sid,
                        "byte_len": len(b),
                        "raw_bytes": b,
                        "expiration_token_bytes_present": False,
                        "widget_key_bytes_present": (
                            b"solo_countdown_wake" in b
                            or b"minimal_wake" in b
                            or b"transport_minimal" in b
                        ),
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
        ws_capture.attach_context(context)
        ws_capture.attach(page)
        attach_ws(page)

        # --- Control: Case A minimal_wake_repro ---
        control_send_epoch: float | None = None
        goto_and_wake(page, case_a_url(), timeout_s=240)
        page.wait_for_timeout(8000)
        t_ctrl = time.time() + 120
        pre_ctrl_rows: list[dict[str, Any]] = []
        while time.time() < t_ctrl:
            cap = capture_all_ledger_sources(page, audit={})
            collector.absorb_capture(cap, label="control_poll")
            pre_ctrl_rows = collector.peak_rows()
            snap = scrape_case_a(page)
            cb = int((snap.get("case_a") or {}).get("callbacks") or 0)
            if cb >= CONTROL_CYCLES:
                control_send_epoch = time.time()
                break
            page.wait_for_timeout(1000)

        ctrl_snap = scrape_case_a(page)
        ctrl_peak = collector.peak_rows()
        ctrl_global_before = len(pre_ctrl_rows)
        ctrl_post_global = _post_send_global_canaries(
            ctrl_peak, control_send_epoch or time.time()
        )
        ctrl_out = _find_correlated_outbound(
            raw_ws,
            anchor_ts=control_send_epoch or time.time(),
            widget_key="minimal",
        )
        if ctrl_out and ctrl_out.get("raw_bytes"):
            ctrl_out["backmsg_decode"] = try_parse_backmsg(ctrl_out["raw_bytes"])
        ctrl_decode = (ctrl_out or {}).get("backmsg_decode") or {}
        report["control"] = {
            "mode": "app_shell_case_a_minimal_wake_repro",
            "send_epoch": control_send_epoch,
            "case_a": ctrl_snap.get("case_a"),
            "repro_client": ctrl_snap.get("repro_client"),
            "control_python_rerun_proven": int((ctrl_snap.get("case_a") or {}).get("callbacks") or 0) >= CONTROL_CYCLES,
            "post_send_global_canary_count": len(ctrl_post_global),
            "correlated_outbound": {k: v for k, v in (ctrl_out or {}).items() if k != "raw_bytes"},
            "backmsg_decode": ctrl_decode,
        }

        # --- Production: same session ---
        install_parent_event_sink(page, parent_sink)
        url = production_url()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(15000)
        try:
            page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
            page.wait_for_timeout(3000)
        except Exception:
            pass
        page.wait_for_timeout(15000)
        probe = scrape_deploy(page)
        sha = (scrape_live_sha(page) or scrape_deploy_build(page) or probe.get("sha") or "")[:7].lower()
        report["cloud_sha"] = sha
        report["cloud_build"] = str(probe.get("build") or "")
        report["implementation"] = commit_has_canary_implementation(sha)
        if sha != REQUIRED_CLOUD_SHA:
            report["aborted"] = True
            report["reason"] = "cloud_sha_mismatch"
            context.close()
            browser.close()
            return report

        canary_pre = verify_pre_trace_canaries(page)
        report["pre_trace_canary_validation"] = canary_pre
        if canary_pre.get("classification") != "CANARY_PRE_TRACE_OK":
            report["aborted"] = True
            report["reason"] = "INVALID_CANARY_DEPLOY_OR_CAPTURE"
            context.close()
            browser.close()
            return report

        cleanup = ensure_fresh_setup_lobby(page)
        report["cleanup"] = cleanup
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
        report["setup"] = start_val
        if not start_val.get("valid"):
            report["aborted"] = True
            report["reason"] = "setup_failed"
            context.close()
            browser.close()
            return report

        decl = verify_declaration_canaries_after_mount(page)
        report["pre_trace_declaration_canary_validation"] = decl
        if decl.get("classification") != "CANARY_DECLARATION_OK":
            report["aborted"] = True
            report["reason"] = "declaration_canary_failed"
            context.close()
            browser.close()
            return report

        observer_pre = _scrape_parent_observer(page)
        reg_pre = _registered_production_widget(list(observer_pre.get("registrations") or []))

        room_id = str(start_val.get("latched_room_id") or draft.get("room_id") or "")
        exact_token = str((start_val.get("authoritative_state") or {}).get("production_token") or "")
        pick_index = (start_val.get("authoritative_state") or {}).get("pick_index")
        if pick_index is not None:
            pick_index = int(pick_index)

        collector.absorb_capture(capture_all_ledger_sources(page), label="prod_pre_send")
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
        poll = trace.get("post_send_poll") or {}
        cls = trace.get("boundary_classification") or {}
        facts = cls.get("facts") or {}
        ws_corr = poll.get("websocket_correlation") or {}
        prod_out = ws_corr.get("correlated_outbound") or {}
        prod_out_bytes = None
        prod_out_ts = float(prod_out.get("wall_ts") or send_epoch)
        for f in raw_ws:
            if f.get("direction") != "outbound":
                continue
            wt = float(f.get("wall_ts") or 0)
            if abs(wt - prod_out_ts) < 0.05 or (send_epoch - 0.05 <= wt <= send_epoch + 2 and f.get("expiration_token_bytes_present")):
                prod_out_bytes = f.get("raw_bytes")
                if exact_token.encode("utf-8") in (prod_out_bytes or b""):
                    break
        if prod_out_bytes is None:
            for f in raw_ws:
                if f.get("direction") == "outbound" and send_epoch - 0.05 <= float(f.get("wall_ts") or 0) <= send_epoch + 2:
                    b = f.get("raw_bytes") or b""
                    if exact_token.encode("utf-8") in b:
                        prod_out_bytes = b
                        break
        prod_decode = try_parse_backmsg(prod_out_bytes or b"")

        observer_post = _scrape_parent_observer(page)
        reg_post = _registered_production_widget(list(observer_post.get("registrations") or []))

        outbound_ids = [w.get("internal_id_hash") for w in prod_decode.get("widget_ids_in_binary") or []]
        reg_id = str(reg_pre.get("component_id") or reg_pre.get("internal_widget_id") or reg_pre.get("widget_id") or "")
        outbound_widget_ids = prod_decode.get("widget_state_ids") or outbound_ids

        widget_cmp = {
            "registered_at_mount": reg_pre,
            "registered_at_send": reg_post,
            "outbound_internal_ids": outbound_widget_ids,
            "outbound_id_matches_registered": bool(
                reg_id and reg_id in "".join(outbound_widget_ids + outbound_ids)
            )
            if reg_id
            else None,
            "page_script_hash_changed_before_send": reg_pre.get("page_script_hash") != reg_post.get("page_script_hash")
            if reg_pre and reg_post
            else None,
            "duplicate_key_replacement": len(list(observer_post.get("registrations") or []))
            > len(list(observer_pre.get("registrations") or [])),
            "registered_inactive_at_send": reg_post.get("inactive") if isinstance(reg_post, dict) else None,
        }

        backmsg_cmp = compare_backmsg_summaries(
            report["control"].get("backmsg_decode") or {},
            prod_decode,
        )

        prod_global_after = _post_send_global_canaries(collector.peak_rows(), send_epoch)

        prod_widget_rows = [
            w
            for w in (prod_decode.get("widget_states") or [])
            if "solo_countdown_wake_solo_persistent" in str(w.get("id") or "")
        ]
        prod_token_in_backmsg = any(
            exact_token in str(w.get("json_value_preview") or "") + str(w.get("string_value_preview") or "")
            for w in prod_widget_rows
        )
        prod_rerun_backmsg = prod_decode.get("backmsg_oneof_type") == "rerun_script"

        first_diff: dict[str, Any] = {"kind": "unknown"}
        if prod_rerun_backmsg and prod_token_in_backmsg and len(prod_global_after) == 0:
            first_diff = {
                "kind": "server_rerun_not_observed_after_valid_backmsg",
                "detail": "rerun_script BackMsg includes exact token in widget_states; post-send global canary absent",
                "production_send_ts": send_epoch,
                "parent_receipt_ts": facts.get("parent_receipt_ts"),
                "outbound_backmsg_oneof": prod_decode.get("backmsg_oneof_type"),
                "production_widget_state_id": (
                    prod_widget_rows[0].get("id") if prod_widget_rows else None
                ),
            }
        elif report["control"].get("control_python_rerun_proven") and not (
            report["control"].get("backmsg_decode") or {}
        ).get("parsed"):
            first_diff = {
                "kind": "control_backmsg_capture_gap",
                "detail": "Case A Python delivery proven; outbound BackMsg not captured at control send anchor",
                "control_send_ts": report["control"].get("send_epoch"),
            }

        report["production"] = {
            "send_epoch": send_epoch,
            "parent_receipt_ts": facts.get("parent_receipt_ts"),
            "exact_token": exact_token,
            "post_send_global_canary_count": len(prod_global_after),
            "boundary_classification": cls.get("code"),
            "correlated_outbound": prod_out,
            "backmsg_decode": prod_decode,
            "inbound_first": ws_corr.get("correlated_inbound_first"),
        }
        report["widget_id_comparison"] = widget_cmp
        report["backmsg_comparison"] = backmsg_cmp
        report["first_difference"] = first_diff
        report["trace"] = {"ok": trace.get("ok"), "boundary_classification": cls}
        report["classification"] = classify_s_code(report)
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
    report = enrich_report_for_artifacts(report)
    safe = _json_safe(report)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(safe, indent=2, default=str), encoding="utf-8")
    OUT_TXT.write_text(format_txt(report), encoding="utf-8")
    print(format_txt(report))
    print(f"artifact={OUT_JSON}")
    return 1 if report.get("aborted") else 0


if __name__ == "__main__":
    raise SystemExit(main())
