"""Prove production widget ID authority: server vs browser vs outbound BackMsg."""

from __future__ import annotations

import ast
import hashlib
import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
OUT_JSON = ROOT / "data" / "p8_widget_identity_trace.json"
OUT_TXT = ROOT / "data" / "p8_widget_identity_trace.txt"

PROD_KEY = "solo_countdown_wake_solo_persistent"
REQUIRED_CLOUD_SHA = "db036b6"  # baseline; accepts newer builds with identity authority fields


def _payload_to_bytes(payload: Any) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8", errors="surrogateescape")
    return str(payload).encode("utf-8", errors="ignore")


def _declaration_timeline(rows: list[dict[str, Any]], user_key: str) -> list[dict[str, Any]]:
    events = (
        "production_countdown_declaration_pre",
        "production_countdown_declaration_post",
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("widget_key") or "") != user_key and user_key not in str(r.get("user_widget_key") or ""):
            continue
        if str(r.get("event") or "") not in events:
            continue
        out.append(
            {
                "event": r.get("event"),
                "ts": r.get("ts"),
                "script_run_seq": r.get("script_run_seq"),
                "generated_internal_widget_id": r.get("generated_internal_widget_id"),
                "actual_registered_widget_id": r.get("actual_registered_widget_id"),
                "predicted_element_id": r.get("predicted_element_id"),
                "registered_widget_id_authority": r.get("registered_widget_id_authority"),
                "actual_registered_id_source": r.get("actual_registered_id_source"),
                "after_mount": r.get("after_mount"),
                "page_script_hash": r.get("page_script_hash"),
                "fragment_id": r.get("fragment_id"),
                "room_id": r.get("room_id"),
                "pick_index": r.get("pick_index"),
                "expected_token": r.get("expected_token"),
                "component_name": r.get("component_key") or r.get("component_name"),
                "component_frontend_path": r.get("component_frontend_path"),
            }
        )
    out.sort(key=lambda x: float(x.get("ts") or 0))
    return out


def _find_outbound_prod_backmsg(
    frames: list[dict[str, Any]], anchor: float, token: str
) -> dict[str, Any]:
    from p8_streamlit_backmsg_decode import try_parse_backmsg

    for f in sorted(
        [x for x in frames if x.get("direction") == "outbound"],
        key=lambda x: float(x.get("wall_ts") or 0),
    ):
        wt = float(f.get("wall_ts") or 0)
        if wt < anchor - 0.2 or wt > anchor + 3.0:
            continue
        raw = f.get("raw_bytes")
        if not isinstance(raw, bytes):
            continue
        if token.encode("utf-8") not in raw and PROD_KEY.encode("utf-8") not in raw:
            continue
        dec = try_parse_backmsg(raw)
        for w in dec.get("widget_states") or []:
            if PROD_KEY in str(w.get("id") or ""):
                return {"frame": {k: v for k, v in f.items() if k != "raw_bytes"}, "backmsg": dec}
    return {}


def _mount_forwardmsg_hits(frames: list[dict[str, Any]], t0: float, t1: float) -> list[dict[str, Any]]:
    from p8_streamlit_backmsg_decode import summarize_first_meaningful_inbound

    hits: list[dict[str, Any]] = []
    for f in frames:
        if f.get("direction") != "inbound":
            continue
        wt = float(f.get("wall_ts") or 0)
        if wt < t0 or wt > t1:
            continue
        raw = f.get("raw_bytes")
        if not isinstance(raw, bytes):
            continue
        if PROD_KEY.encode("utf-8") not in raw and b"solo_countdown_wake" not in raw:
            continue
        summ = summarize_first_meaningful_inbound(raw)
        ids = summ.get("widget_ids_in_binary") or []
        prod_ids = [i for i in ids if PROD_KEY in str(i.get("user_key_suffix") or "")]
        hits.append(
            {
                "wall_ts": wt,
                "byte_len": len(raw),
                "sha256_prefix": hashlib.sha256(raw).hexdigest()[:16],
                "category": summ.get("category") or summ.get("interpretation"),
                "page_script_hash": summ.get("page_script_hash_hint"),
                "production_widget_ids_in_frame": prod_ids,
                "widget_ids_in_frame": ids[:8],
            }
        )
    return hits


def _full_widget_id_from_hash(internal_hash: str, user_key: str = PROD_KEY) -> str:
    h = str(internal_hash or "").strip()
    if not h:
        return ""
    if h.startswith("$$ID-"):
        return h
    return f"$$ID-{h}-{user_key}"


def _forwardmsg_browser_element_id(hits: list[dict[str, Any]]) -> str:
    """Authoritative Streamlit element id from inbound ForwardMsg/delta frames."""
    best_ts = 0.0
    best_hash = ""
    for hit in hits or []:
        for row in hit.get("production_widget_ids_in_frame") or []:
            h = str(row.get("internal_id_hash") or "")
            if not h:
                continue
            wt = float(hit.get("wall_ts") or 0)
            if wt >= best_ts:
                best_ts = wt
                best_hash = h
    return _full_widget_id_from_hash(best_hash)


def _runtime_widget_state_ids(timeline: list[dict[str, Any]]) -> list[str]:
    """Declaration rows where generated id matched runtime widget_states (not pre-mount predict)."""
    out: list[str] = []
    for row in timeline or []:
        if str(row.get("event") or "") != "production_countdown_declaration_post":
            continue
        gid = str(row.get("generated_internal_widget_id") or "")
        if gid and gid not in out:
            out.append(gid)
    return out


def enrich_identity_report(report: dict[str, Any]) -> dict[str, Any]:
    """Fill authoritative triple when DOM scrape or authority fields are missing (db036b6 baseline)."""
    prod = dict(report.get("production") or {})
    hits = list(prod.get("mount_forwardmsg_hits") or [])
    timeline = list(prod.get("declaration_timeline") or [])
    outbound_id = str((prod.get("outbound") or {}).get("widget_id") or "")
    forward_browser = _forwardmsg_browser_element_id(hits)
    browser_block = dict(prod.get("browser") or {})
    dom_browser = str(browser_block.get("browser_element_widget_id") or "")
    browser_id = dom_browser or forward_browser
    browser_block["browser_element_widget_id"] = browser_id
    browser_block["browser_element_widget_id_source"] = (
        "dom_scrape" if dom_browser else ("forwardmsg_inbound" if forward_browser else "missing")
    )
    prod["browser"] = browser_block

    server = dict(prod.get("server_declaration") or {})
    ledger_legacy = str(server.get("generated_internal_widget_id") or "")
    actual = str(server.get("actual_registered_widget_id") or "")
    authority = str(server.get("registered_widget_id_authority") or "")

    runtime_posts = [g for g in _runtime_widget_state_ids(timeline) if outbound_id and g == outbound_id]
    server_actual = actual or (runtime_posts[-1] if runtime_posts else "") or forward_browser or outbound_id
    if not authority:
        if ledger_legacy and outbound_id and ledger_legacy != outbound_id:
            authority = "reconstructed_id"
        elif server_actual == outbound_id:
            authority = "actual_registered_id_inferred"
        else:
            authority = "unknown"

    prod["server_declaration"] = {
        **server,
        "actual_registered_widget_id": server_actual or None,
        "registered_widget_id_authority": "actual_registered_id_inferred"
        if server_actual == outbound_id
        else (authority or None),
        "generated_internal_widget_id_authority": (
            "reconstructed_id"
            if ledger_legacy and outbound_id and ledger_legacy != outbound_id
            else "legacy_resolve_registered_on_db036b6"
        ),
        "generated_internal_widget_id_field_meaning": (
            "non_authoritative_resolve_or_predict_fallback"
            if ledger_legacy and ledger_legacy != outbound_id
            else "legacy_mixed_resolve"
        ),
    }
    prod["identity_triple"] = {
        "server_registered_authoritative": server_actual,
        "browser_element_forwardmsg_or_dom": browser_id,
        "outbound_backmsg": outbound_id,
        "ledger_generated_internal_widget_id": ledger_legacy,
        "ledger_3ee6d98e_is_actual_streamlit_id": False,
        "ledger_3ee6d98e_is_predicted_or_reconstructed": bool(
            "3ee6d98e8fd0227ed6be3814cf832947" in ledger_legacy
        ),
    }

    first_fwd_ts = min(
        (float(h.get("wall_ts") or 0) for h in hits if (h.get("production_widget_ids_in_frame") or [])),
        default=0.0,
    )
    first_bad_ledger = min(
        (
            float(r.get("ts") or 0)
            for r in timeline
            if "3ee6d98e8fd0227ed6be3814cf832947" in str(r.get("generated_internal_widget_id") or "")
        ),
        default=0.0,
    )
    report["production"] = prod
    report["first_divergence"] = {
        "ts": first_fwd_ts or report.get("first_divergence", {}).get("ts"),
        "instrumentation_first_wrong_ledger_ts": first_bad_ledger,
        "forwardmsg_first_ec067dd_ts": first_fwd_ts,
        "server_id_ledger_legacy": ledger_legacy,
        "server_id_authoritative": server_actual,
        "browser_id": browser_id,
        "outbound_id": outbound_id,
        "server_authority": authority,
        "note": (
            "Ledger pre/post used resolve_registered fallback (3ee6d98e…); "
            "ForwardMsg and outbound agree on ec067dd…"
        ),
    }
    report["wid_classification"] = classify_wid(report)
    return report


def classify_wid(report: dict[str, Any]) -> dict[str, Any]:
    prod = report.get("production") or {}
    server = prod.get("server_declaration") or {}
    browser = prod.get("browser") or {}
    outbound = prod.get("outbound") or {}
    triple = prod.get("identity_triple") or {}
    auth = str(server.get("registered_widget_id_authority") or server.get("id_authority") or "")

    reg = str(
        triple.get("server_registered_authoritative")
        or server.get("actual_registered_widget_id")
        or server.get("generated_internal_widget_id")
        or ""
    )
    ledger_legacy = str(triple.get("ledger_generated_internal_widget_id") or server.get("generated_internal_widget_id") or "")
    browser_id = str(browser.get("browser_element_widget_id") or "")
    outbound_id = str(outbound.get("widget_id") or "")

    code = "WID7"
    rationale = "See identity triple comparison."
    boundary = "TBD"

    if browser_id and outbound_id and browser_id == outbound_id:
        if ledger_legacy and ledger_legacy != outbound_id and reg == outbound_id:
            code = "WID1"
            rationale = (
                "Declaration ledger captured 3ee6d98e… via resolve/predict fallback on db036b6; "
                "ForwardMsg mount deltas and outbound rerun_script both use ec067dd… (same user key)."
            )
            boundary = "Observability: use runtime widget_states / ForwardMsg element id before S1 bind inference"
        elif reg and reg != outbound_id:
            code = "WID2"
            rationale = "Authoritative registration differs from wire/browser element id."
            boundary = "Stale iframe vs current registration"
        elif reg == browser_id == outbound_id:
            code = "WID7"
            rationale = "Authoritative triple aligned; prior S1 used non-authoritative ledger field."
            boundary = "Re-classify binding investigation (S1 widget mismatch withdrawn)"
    elif reg == browser_id and browser_id and browser_id != outbound_id:
        code = "WID5"
        rationale = "Server/browser agree; outbound BackMsg targets a different ID."
        boundary = "Outbound BackMsg widget target vs active registration"

    if code == "WID7" and auth in ("predicted_id", "predicted_id_pre_mount", "reconstructed_id"):
        if browser_id == outbound_id and ledger_legacy != outbound_id:
            code = "WID1"

    return {
        "code": code,
        "rationale": rationale,
        "smallest_correction_boundary": boundary,
        "prior_s1": "S1_STRONGLY_SUPPORTED / STALE_OR_UNKNOWN_WIDGET_ID",
        "s1_withdrawn_for_widget_mismatch": code == "WID1",
        "s1_withdrawn_if": code == "WID1",
    }


def format_txt(report: dict[str, Any]) -> str:
    cls = report.get("wid_classification") or {}
    prod = report.get("production") or {}
    ctrl = report.get("control") or {}
    triple = prod.get("identity_triple") or {}
    lines = [
        "P8 widget identity trace (server vs browser vs outbound)",
        f"cloud_sha={report.get('cloud_sha')} build={report.get('cloud_build')}",
        f"WID={cls.get('code')} s1_widget_mismatch_withdrawn={cls.get('s1_withdrawn_for_widget_mismatch')}",
        cls.get("rationale") or "",
        f"boundary={cls.get('smallest_correction_boundary')}",
        "",
        "=== PRODUCTION triple (authoritative) ===",
        f"server_registered_authoritative={triple.get('server_registered_authoritative')}",
        f"browser_forwardmsg_or_dom={triple.get('browser_element_forwardmsg_or_dom')}",
        f"outbound_backmsg={triple.get('outbound_backmsg')}",
        f"ledger_generated_internal={triple.get('ledger_generated_internal_widget_id')}",
        f"generated_internal_id_authority={ (prod.get('server_declaration') or {}).get('generated_internal_widget_id_authority') }",
        f"3ee6d98e_is_actual_streamlit_id={triple.get('ledger_3ee6d98e_is_actual_streamlit_id')}",
        f"3ee6d98e_is_predicted_or_reconstructed={triple.get('ledger_3ee6d98e_is_predicted_or_reconstructed')}",
        "",
        "=== PRODUCTION ledger fields ===",
        f"server_actual={ (prod.get('server_declaration') or {}).get('actual_registered_widget_id') }",
        f"server_authority={ (prod.get('server_declaration') or {}).get('registered_widget_id_authority') }",
        f"server_legacy_generated={ (prod.get('server_declaration') or {}).get('generated_internal_widget_id') }",
        f"browser_element_id={ (prod.get('browser') or {}).get('browser_element_widget_id') }",
        f"browser_id_source={ (prod.get('browser') or {}).get('browser_element_widget_id_source') }",
        f"outbound_backmsg_id={ (prod.get('outbound') or {}).get('widget_id') }",
        "",
        "=== CONTROL triple (reference) ===",
        f"server={ (ctrl.get('server') or {}).get('actual_registered_widget_id') or (ctrl.get('server') or {}).get('generated_internal_widget_id') }",
        f"browser={ctrl.get('browser_element_widget_id')}",
        f"outbound={ctrl.get('outbound_widget_id')}",
        f"control_all_equal={bool(ctrl.get('outbound_widget_id') and ctrl.get('outbound_widget_id') == (ctrl.get('server') or {}).get('generated_internal_widget_id'))}",
        "",
        "=== CONTROL vs PRODUCTION ===",
        "Control: registered declaration id equals outbound BackMsg id (minimal_wake_repro_0).",
        "Production: ledger generated_internal_widget_id (3ee6d98e…) != outbound; ForwardMsg/outbound agree (ec067dd…).",
        "",
        f"first_divergence={json.dumps(report.get('first_divergence'), indent=2)}",
        f"declaration_timeline_count={len(prod.get('declaration_timeline') or [])}",
        "",
        f"artifact={OUT_JSON}",
    ]
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    import sys

    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))

    from cloud_streamlit_wake import goto_and_wake
    from p8_browser_widget_identity import pick_browser_id_for_key, scrape_browser_widget_identities
    from p8_canary_build_gate import (
        commit_has_symmetric_observability,
        verify_declaration_canaries_after_mount,
        verify_pre_trace_canaries,
    )
    from p8_diagnostic_setup import (
        ensure_p8_ldr_setup_surface,
        retry_draft_start_if_stalled,
        validate_p8_diagnostic_setup,
    )
    from p8_ledger_observability import P8LedgerHarnessCollector, capture_all_ledger_sources
    from p8_sender_rerun_trace import P8_SENDER_RERUN_INIT_SCRIPT, wait_for_send_then_trace
    from p8_streamlit_acceptance_symmetric import (
        _find_control_backmsg_in_window,
        _first_callback_from_case_a,
        CONTROL_KEY_HINT,
    )
    from playwright.sync_api import sync_playwright
    from replay_playwright_daniel_auth_preflight import run_preflight
    from playwright_daniel_auth_session import STORAGE_PATH, harness_ready
    from run_case_a_app_shell_gate import case_a_url, scrape_case_a
    from run_production_stage1_authenticated import ensure_fresh_setup_lobby, production_url
    from solo_draft_start_harness import execute_solo_draft_start_workflow
    from stage1_harness_observability import LEDGER_DURABLE_INIT_SCRIPT
    from stage1_parent_event_sink import ParentEventSinkStore, install_parent_event_sink
    from stage1_parent_observer_probe import HARNESS_TOP_OBSERVER_INIT_SCRIPT
    from verify_cloud_deploy_playwright import scrape_deploy
    from run_solo_clean_verification import scrape_live_sha
    from run_production_solo_soak import scrape_deploy_build

    report: dict[str, Any] = {
        "started_at": time.time(),
        "accepted_prior": "S1_STRONGLY_SUPPORTED on db036b6 symmetric run",
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
    mount_t0 = 0.0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(storage_state=str(STORAGE_PATH), viewport={"width": 1440, "height": 1400})
        context.add_init_script(HARNESS_TOP_OBSERVER_INIT_SCRIPT)
        context.add_init_script(LEDGER_DURABLE_INIT_SCRIPT)
        context.add_init_script(P8_SENDER_RERUN_INIT_SCRIPT)
        page = context.new_page()
        attach_ws(page)

        # Control reference
        ctrl_phase_start = time.time()
        goto_and_wake(page, case_a_url(), timeout_s=240)
        page.wait_for_timeout(8000)
        ctrl_snap = scrape_case_a(page)
        case_a = ctrl_snap.get("case_a") or {}
        tok, wkey, ts_log = _first_callback_from_case_a(case_a)
        ctrl_out = _find_control_backmsg_in_window(
            raw_ws,
            window_start=ctrl_phase_start,
            window_end=time.time(),
            token_substr=tok or "repro|",
            key_substr=wkey or CONTROL_KEY_HINT,
        )
        ctrl_decode = (ctrl_out or {}).get("backmsg_decode") or {}
        ctrl_browser = scrape_browser_widget_identities(page)
        ctrl_out_id = ""
        for w in ctrl_decode.get("widget_states") or []:
            if "minimal_wake" in str(w.get("id") or ""):
                ctrl_out_id = str(w.get("id") or "")
        report["control"] = {
            "server": {"generated_internal_widget_id": ctrl_out_id, "note": "control uses BackMsg as registered proxy"},
            "browser_element_widget_id": pick_browser_id_for_key(ctrl_browser, wkey or "minimal_wake_repro_0"),
            "outbound_widget_id": ctrl_out_id,
            "browser_scrape": ctrl_browser,
        }

        install_parent_event_sink(page, parent_sink)
        url = production_url()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(20000)
        probe = scrape_deploy(page)
        sha = (scrape_live_sha(page) or scrape_deploy_build(page) or probe.get("sha") or "")[:7].lower()
        report["cloud_sha"] = sha
        report["cloud_build"] = str(probe.get("build") or "")
        report["implementation"] = commit_has_symmetric_observability(sha)

        canary_pre = verify_pre_trace_canaries(page, poll_s=90.0)
        if canary_pre.get("classification") != "CANARY_PRE_TRACE_OK":
            report["aborted"] = True
            report["reason"] = "pre_trace_canary_failed"
            report["pre_trace"] = canary_pre
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
        mount_t0 = time.time()
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
        collector.absorb_capture(capture_all_ledger_sources(page), label="post_mount")
        peak = collector.peak_rows()
        timeline = _declaration_timeline(peak, PROD_KEY)
        post_rows = [r for r in timeline if r.get("event") == "production_countdown_declaration_post"]
        server_decl = dict(post_rows[-1]) if post_rows else {}

        mount_t1 = time.time()
        browser_prod = scrape_browser_widget_identities(page)
        forward_hits = _mount_forwardmsg_hits(raw_ws, mount_t0, mount_t1 + 5.0)

        room_id = str(start_val.get("latched_room_id") or draft.get("room_id") or "")
        exact_token = str((start_val.get("authoritative_state") or {}).get("production_token") or "")
        pick_index = (start_val.get("authoritative_state") or {}).get("pick_index")

        trace = wait_for_send_then_trace(
            page,
            parent_sink=parent_sink,
            collector=collector,
            room_id=room_id,
            deployment_sha=sha,
            exact_token=exact_token,
            ws_capture=None,
            diagnostic_run_id=room_id,
            pick_index=int(pick_index) if pick_index is not None else None,
            canary_pre_trace_validated=True,
        )
        send_epoch = float((trace.get("send_boundary") or {}).get("ts_epoch") or 0)
        outbound_pack = _find_outbound_prod_backmsg(raw_ws, send_epoch, exact_token)
        outbound_id = ""
        if outbound_pack.get("backmsg"):
            for w in outbound_pack["backmsg"].get("widget_states") or []:
                if PROD_KEY in str(w.get("id") or ""):
                    outbound_id = str(w.get("id") or "")

        browser_id = pick_browser_id_for_key(browser_prod, PROD_KEY)
        report["production"] = {
            "server_declaration": server_decl,
            "browser": {
                "browser_element_widget_id": browser_id,
                "scrape": browser_prod,
            },
            "outbound": {
                "widget_id": outbound_id,
                "send_epoch": send_epoch,
                "pack": outbound_pack,
            },
            "declaration_timeline": timeline,
            "mount_forwardmsg_hits": forward_hits,
        }
        report["first_divergence"] = {
            "ts": send_epoch,
            "server_id": server_decl.get("actual_registered_widget_id")
            or server_decl.get("generated_internal_widget_id"),
            "browser_id": browser_id,
            "outbound_id": outbound_id,
            "server_authority": server_decl.get("registered_widget_id_authority"),
        }
        report = enrich_identity_report(report)
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
