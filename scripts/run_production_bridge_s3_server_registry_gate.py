"""Production: S3 server registry gate — wire ID → register → state apply → R1–R7."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "production_bridge_s3_server_registry_gate.json"
SETUP_ONLY_OUT = ROOT / "data" / "production_bridge_s3_setup_only_gate.json"
OOB_SETUP_ONLY_OUT = ROOT / "data" / "production_bridge_s3_oob_setup_only_gate.json"
OOB_CHANNEL_DISCOVERY_PASS = "OOB_CHANNEL_DISCOVERY_PASS"
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"


def _harness_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
    except Exception:
        return ""


def _expected_streamlit_session_id(report: dict[str, Any]) -> str:
    start = report.get("start_latch") if isinstance(report.get("start_latch"), dict) else {}
    bridge = report.get("bridge_hydration") if isinstance(report.get("bridge_hydration"), dict) else {}
    return str(start.get("streamlit_session_id") or bridge.get("streamlit_session_id") or "")[:64]


def _apply_oob_discovery_to_report(
    report: dict[str, Any],
    *,
    page,
    expected_streamlit_sid: str,
    connected_server_uri: str = "",
) -> dict[str, Any]:
    from stage1_s3_oob_readback import extract_oob_freshness_from_snapshot, run_oob_discovery_pipeline
    from stage1_s3_r3_observability_classify import classify_oob_channel_unavailable
    from stage1_s3_server_registry_scrape import scrape_s3_server_diag_ledger, scrape_s3_server_diag_readiness

    readiness_pre = scrape_s3_server_diag_readiness(page, expected_streamlit_session_id=expected_streamlit_sid)
    ledger_pre = scrape_s3_server_diag_ledger(page)
    discovery = run_oob_discovery_pipeline(
        readiness_scrape=readiness_pre,
        ledger_scrape=ledger_pre,
        expected_streamlit_sid=expected_streamlit_sid,
        page=page,
        connected_server_uri=connected_server_uri or None,
        require_connected_server_uri=True,
    )
    oob_channel = dict(discovery.get("resolved_channel") or {})
    initial_oob_fetch = dict(discovery.get("initial_fetch") or {})
    pre_oob_snapshot = dict(discovery.get("pre_oob_snapshot") or initial_oob_fetch.get("snapshot") or {})
    pre_oob_fresh = extract_oob_freshness_from_snapshot(pre_oob_snapshot)
    report["s3_readiness_candidate_inventory"] = {
        "candidate_count": readiness_pre.get("candidate_count"),
        "candidates": readiness_pre.get("candidates"),
        "selected_candidate_index": readiness_pre.get("selected_candidate_index"),
        "selection_reason": readiness_pre.get("selection_reason"),
    }
    report["s3_oob_discovery"] = discovery
    report["s3_oob_channel_pre_sibling"] = oob_channel
    report["s3_oob_initial_fetch"] = initial_oob_fetch
    report["s3_oob_freshness_pre_sibling_click"] = pre_oob_fresh
    report["pre_sibling_oob_generation"] = pre_oob_fresh.get("snapshot_generation")
    unavailable = None
    if not discovery.get("ok"):
        note = str(
            discovery.get("snapshot_validation_note")
            or discovery.get("identity_note")
            or discovery.get("selection_reason")
            or "oob_channel_missing_or_unreadable"
        )
        unavailable = classify_oob_channel_unavailable(
            channel=oob_channel,
            initial_fetch=initial_oob_fetch,
            note=note,
        )
    return {
        "discovery": discovery,
        "oob_channel": oob_channel,
        "initial_oob_fetch": initial_oob_fetch,
        "pre_oob_snapshot": pre_oob_snapshot,
        "pre_oob_fresh": pre_oob_fresh,
        "readiness_pre": readiness_pre,
        "ledger_pre": ledger_pre,
        "unavailable": unavailable,
    }


def _wire_from_sibling_step(sibling_step: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Extract sibling widget id + authoritative wire fragment from sibling capture.

    When the capture requested target-widget correlation (expected_widget_id set), never fall
    back to the first decoded rerun_script fragment — that recreates the false-R2A race.
    """
    tr = dict(sibling_step.get("streamlit_transport") or {})
    strict = dict(tr.get("strict_backmsg") or {})
    expected = str(
        sibling_step.get("expected_widget_id")
        or strict.get("expected_widget_id")
        or ""
    ).strip()
    correlation_requested = bool(expected) or bool(strict.get("target_correlation_requested"))

    ids = list(strict.get("activated_widget_ids") or [])
    # Prefer the expected registered widget id when present.
    if expected:
        wire = expected
    else:
        wire = str(ids[0] if ids else "")

    wire_target = str(strict.get("wire_rerun_target_fragment_id") or "").strip()
    if correlation_requested:
        if not strict.get("target_trigger_backmsg_seen"):
            wire_target = ""
        else:
            wire_target = str(
                strict.get("target_trigger_fragment_id") or strict.get("wire_rerun_target_fragment_id") or ""
            ).strip()
        return wire, wire_target, strict

    # Legacy callers without target correlation: first wire field, then first rerun frame.
    if not wire_target:
        for fr in strict.get("decoded_outbound_frames") or []:
            if not isinstance(fr, dict):
                continue
            dec = fr.get("decode") if isinstance(fr.get("decode"), dict) else {}
            if dec.get("backmsg_oneof_type") != "rerun_script":
                continue
            cs = dec.get("client_state") if isinstance(dec.get("client_state"), dict) else {}
            wire_target = str(cs.get("fragment_id") or "").strip()
            if wire_target:
                break
    return wire, wire_target, strict


def _wait_post_registration(page, *, max_wait_s: float = 90.0) -> dict[str, Any]:
    from stage1_s3_server_registry_scrape import (
        evaluate_post_registration_from_ledger,
        scrape_s3_server_diag_ledger,
    )

    deadline = time.time() + max_wait_s
    last: dict[str, Any] = {"found": False}
    while time.time() < deadline:
        snap = scrape_s3_server_diag_ledger(page)
        last = snap
        post, binding, _pre = evaluate_post_registration_from_ledger(snap)
        payload = snap.get("payload") if isinstance(snap.get("payload"), dict) else {}
        if (
            snap.get("found")
            and str(post.get("registered_widget_id") or "").startswith("$$ID-")
            and bool(binding.get("sessionstate_binding_ok"))
        ):
            return {"ok": True, "scrape": snap, "post_registration": post, "s3_diag_binding": binding}
        page.wait_for_timeout(800)
    post, binding, _pre = evaluate_post_registration_from_ledger(last)
    return {"ok": False, "scrape": last, "post_registration": post, "s3_diag_binding": binding}


def _capture_pause_strict(page, *, room_id: str) -> dict[str, Any]:
    from p8_proven_pause_delivery import (
        PAUSE_DELIVERY_RESOLVED,
        dispatch_proven_pause_click,
        wait_for_authoritative_pause_control,
        wait_for_pause_server_proof,
    )
    from stage1_streamlit_click_transport import capture_streamlit_click_transport, clear_ws_boundary_log

    out: dict[str, Any] = {"step": "pause_strict_backmsg", "started_ts": time.time()}
    hydration = wait_for_authoritative_pause_control(page, max_wait_s=30.0, room_id=room_id)
    out["pause_hydration"] = hydration
    if not hydration.get("ready"):
        out["setup_abort"] = "PAUSE_UI_NOT_READY"
        out["finished_ts"] = time.time()
        return out
    pre_click_ts = time.time()
    out["pre_click_timestamp"] = pre_click_ts
    out["ws_clear"] = clear_ws_boundary_log(page)
    click = dispatch_proven_pause_click(page)
    out["pause_click"] = click
    click_ts = float(click.get("click_timestamp") or pre_click_ts)
    page.wait_for_timeout(650)
    transport = capture_streamlit_click_transport(
        page,
        click_ts=pre_click_ts - 0.05,
        frame_url_hint=str(click.get("click_frame_url") or ""),
    )
    out["streamlit_transport"] = transport
    server = wait_for_pause_server_proof(page, click_ts=click_ts, max_wait_s=22.0)
    out["pause_server_proof"] = server
    out["trusted_dom_click"] = bool(click.get("trusted_dom_click"))
    out["pause_resolved"] = bool(server.get("paused_recognized"))
    out["pause_classification"] = PAUSE_DELIVERY_RESOLVED if out["pause_resolved"] else "PAUSE_NOT_RESOLVED"
    out["finished_ts"] = time.time()
    return out


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from p8_canonical_production_start import establish_single_solo_live_draft
    from p8_proven_pause_delivery import wait_for_authoritative_pause_control
    from p8_proven_start_delivery import install_proven_start_context_scripts
    from playwright.sync_api import sync_playwright
    from playwright_auth_bridge_restore_harness import resolve_bridge_suite_sid_with_source, wait_bridge_auth_hydrated
    from playwright_daniel_auth_session import append_suite_sid_to_url
    from run_production_stage1_authenticated import resolve_required_cloud_sha
    from stage1_pause_sibling_transport_capture import capture_sibling_pre_pause_transport
    from stage1_preflight_cleanup import run_stage1_preflight_cleanup
    from stage1_s3_r2_subclassify import (
        classify_s3_r2_subclass,
        classify_sibling_oob_r2_from_snapshot,
        resolve_sibling_owner_fragment_id,
        wire_target_in_preclick_storage,
    )
    from stage1_s3_export_freshness import (
        compare_export_freshness,
        extract_export_freshness_from_scrape,
    )
    from stage1_s3_oob_readback import (
        authoritative_rows_from_oob_snapshot,
        compare_oob_freshness,
        extract_oob_channel_from_readiness_scrape,
        extract_oob_freshness_from_snapshot,
        fetch_oob_snapshot_via_page,
        run_oob_discovery_pipeline,
        wait_for_oob_generation_after,
        wait_for_oob_pause_evidence_settled_after,
        wait_for_oob_settled_after,  # retained for historical/regression callers
    )
    from stage1_s3_r3_observability_classify import (
        BUTTON_DISPATCH_S3_R3O0_SERVER_EXPORT_NOT_REFRESHED_AFTER_PAUSE,
        classify_export_freshness_after_pause,
        classify_oob_channel_unavailable,
        classify_oob_freshness_after_pause,
        classify_oob_freshness_after_sibling,
        classify_pause_instrumentation_failure,
        classify_s3_with_observability,
    )
    from stage1_s3_server_registry_classify import classify_s3_server_registry
    from stage1_s3_server_registry_scrape import (
        evaluate_post_registration_from_ledger,
        scrape_frame_dom_diagnostics,
        scrape_s3_server_diag_ledger,
        scrape_s3_server_diag_readiness,
    )
    from stage1_s3_setup_localize import (
        ABORTED_S3_POST_REGISTRATION_NOT_READY,
        build_setup_readiness_table,
        classify_setup_failure,
        setup_ready_for_sibling_click,
    )
    from stage1_pause_sibling_scrape import scrape_pause_sibling_probe
    from stage1_sibling_setup_stable import wait_for_sibling_setup_stable
    from streamlit_app_frame import describe_page_frames, resolve_streamlit_app_frame

    if str(os.environ.get("STAGE1_USE_CAPTURE_BRIDGE") or "").strip().lower() in ("0", "false"):
        print(json.dumps({"ok": False, "classification": "ABORTED_CAPTURE_BRIDGE_DISABLED"}))
        return 1

    setup_only = str(os.environ.get("STAGE1_S3_SETUP_ONLY") or "").strip().lower() in ("1", "true", "yes")
    oob_setup_only = str(os.environ.get("STAGE1_S3_OOB_SETUP_ONLY") or "").strip().lower() in ("1", "true", "yes")
    if oob_setup_only:
        artifact_out = OOB_SETUP_ONLY_OUT
    elif setup_only:
        artifact_out = SETUP_ONLY_OUT
    else:
        artifact_out = OUT
    out_path = artifact_out

    bridge_sid, bridge_source = resolve_bridge_suite_sid_with_source()
    if not bridge_sid:
        print(json.dumps({"ok": False, "classification": "ABORTED_NO_BRIDGE_SID"}))
        return 1

    required = (resolve_required_cloud_sha() or os.environ.get("REQUIRED_CLOUD_SHA") or "").strip().lower()[:7]
    timer = str(os.environ.get("SOLO_DIAG_TIMER") or "120").strip() or "120"
    url = append_suite_sid_to_url(
        f"{BASE}/?active_page=Live%20Draft%20Room&solo_component_diag=1&solo_diag_timer={timer}&solo_stage1_parent_boundary=1",
        bridge_sid,
    )
    report: dict[str, Any] = {
        "mode": "production_bridge_s3_server_registry_gate",
        "harness_sha": _harness_sha(),
        "required_cloud_sha": required,
        "accepted_boundary": "BUTTON_DISPATCH_E2B_S3_TRIGGER_SENT_SERVER_NOT_APPLIED",
        "bridge_suite_sid_prefix": bridge_sid[:8],
        "bridge_suite_sid_source": bridge_source,
        "sequence": [
            "start_latch",
            "pause_control_center_ready",
            "setup_dom_layers",
            "post_registration_and_binding",
        ]
        + ([] if setup_only or oob_setup_only else ["sibling_strict_click", "pause_positive_control", "classify_r3_chain"])
        + (["oob_channel_discovery"] if oob_setup_only else []),
        "setup_only_mode": setup_only,
        "oob_setup_only_mode": oob_setup_only,
        "started_at": time.time(),
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        install_proven_start_context_scripts(context)
        page = context.new_page()
        from stage1_s3_connected_server_uri import ConnectedServerUriCapture

        connected_uri_capture = ConnectedServerUriCapture()
        connected_uri_capture.attach(page)
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(12000)
        connected_uri_resolution = connected_uri_capture.resolve()
        report["streamlit_connected_server_uri"] = str(connected_uri_resolution.get("uri") or "")
        report["streamlit_connected_server_uri_source"] = str(connected_uri_resolution.get("source") or "")
        report["streamlit_connected_server_uri_endpoints"] = connected_uri_resolution.get("endpoint_summaries") or {}
        report["streamlit_connected_server_uri_ok"] = bool(connected_uri_resolution.get("ok"))
        connected_server_uri = str(report["streamlit_connected_server_uri"] or "")

        from p8_production_start_harness import scrape_stage1_ledger_rows
        from queueui_audit_protocol import scrape_deploy_marker_from_page

        deploy_sha, _ = scrape_deploy_marker_from_page(page)
        report["application_runtime_sha"] = str(deploy_sha or "")[:7]
        if required and str(report["application_runtime_sha"]).lower()[:7] != required:
            report["classification"] = "ABORTED_RUNTIME_SHA_MISMATCH"
            report["ok"] = False
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1

        bridge_pre = wait_bridge_auth_hydrated(page, bridge_sid, scrape_stage1_ledger_rows, timeout_s=240.0, preamble_mode="stage1")
        report["bridge_hydration"] = bridge_pre
        if not bridge_pre.get("authenticated_restored"):
            report["classification"] = bridge_pre.get("failure_classification") or "AUTH_HYDRATE7"
            report["ok"] = False
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1

        cleanup = run_stage1_preflight_cleanup(page, max_wait_s=180.0)
        report["preflight_cleanup"] = cleanup
        if not cleanup.get("ok"):
            report["classification"] = "ABORTED_SETUP_LOBBY"
            report["ok"] = False
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1

        canonical = establish_single_solo_live_draft(page, context, setup_url=url, prior_room_id="", max_wait_s=90.0)
        room_id = str(canonical.get("room_id") or "").upper()
        report["canonical_start"] = dict(canonical)
        report["start_latch"] = {
            "room_id": room_id,
            "room_latch_pass": canonical.get("room_latch_pass"),
            "start_click_count": canonical.get("start_click_count"),
            "start_classification": canonical.get("start_classification"),
            "streamlit_session_id": canonical.get("streamlit_session_id"),
            "diagnostic_run_id": canonical.get("diagnostic_run_id"),
            "authoritative_room_status": canonical.get("authoritative_room_status"),
            "countdown_mounted": canonical.get("countdown_mounted"),
        }
        if not room_id or not canonical.get("room_latch_pass"):
            report["classification"] = "ABORTED_START_LATCH"
            report["ok"] = False
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1

        pause_ready = wait_for_authoritative_pause_control(page, max_wait_s=45.0, room_id=room_id)
        report["pause_control_ready"] = dict(pause_ready)
        report["app_frame_inventory"] = describe_page_frames(page)
        report["app_frame_url"] = str(resolve_streamlit_app_frame(page).url or "")[:240]

        setup_stable = wait_for_sibling_setup_stable(
            page,
            room_id=room_id,
            pause_ready=pause_ready,
            runtime_sha=str(report.get("application_runtime_sha") or ""),
            auth_restored=bool(bridge_pre.get("authenticated_restored")),
            start_latch_pass=bool(canonical.get("room_latch_pass")),
            max_wait_s=45.0,
            poll_interval_ms=600,
        )
        report["setup_stabilization"] = {
            "ok": setup_stable.get("ok"),
            "stable": setup_stable.get("stable"),
            "early_abort": setup_stable.get("early_abort"),
            "timed_out": setup_stable.get("timed_out"),
            "poll_count": setup_stable.get("poll_count"),
            "poll_history": setup_stable.get("poll_history"),
            "atomic_presence_final": setup_stable.get("atomic_presence_final"),
        }
        last = dict(setup_stable.get("last_poll") or {})
        sibling_layers = dict(last.get("sibling_setup_layers") or {})
        sibling_scrape = dict(last.get("sibling_probe_scrape") or {})
        s3_ledger_scrape = dict(last.get("s3_ledger_scrape") or {})
        post_reg = dict(last.get("post_registration") or {})
        binding = dict(last.get("s3_diag_binding") or {})
        pre_decl = dict(last.get("pre_declaration") or {})
        report["sibling_probe_scrape"] = sibling_scrape
        report["s3_ledger_scrape_initial"] = s3_ledger_scrape
        report["frame_dom_diagnostics"] = scrape_frame_dom_diagnostics(page)

        streamlit_sid = str(
            last.get("streamlit_session_id")
            or sibling_scrape.get("streamlit_session_id")
            or canonical.get("streamlit_session_id")
            or ""
        )[:64]
        post_reg_ready = bool(last.get("post_registration_ready"))
        binding_ok = bool(last.get("binding_ok"))
        report["sibling_setup_layers"] = sibling_layers
        setup_table = dict(
            setup_stable.get("setup_readiness_table")
            or build_setup_readiness_table(
                runtime_sha=str(report.get("application_runtime_sha") or ""),
                auth_restored=bool(bridge_pre.get("authenticated_restored")),
                start_latch_pass=bool(canonical.get("room_latch_pass")),
                room_id=room_id,
                streamlit_session_id=streamlit_sid,
                pause_control_ready=bool(pause_ready.get("ready")),
                sibling_layers=sibling_layers,
                s3_ledger_found=bool(s3_ledger_scrape.get("found")),
                post_registration_ready=post_reg_ready,
                binding_ok=binding_ok,
                server_wrapper_integrity_ok=binding.get("server_wrapper_integrity_ok"),
            )
        )
        report["post_registration_server_snapshot"] = post_reg
        report["s3_diag_binding_pre_click"] = binding
        report["pre_declaration_snapshot"] = pre_decl

        setup_abort = setup_stable.get("setup_abort")
        setup_note = setup_stable.get("setup_note")
        if setup_stable.get("ok"):
            setup_abort, setup_note = None, "setup_pass"
        report["setup_readiness_table"] = setup_table
        if setup_only and not oob_setup_only:
            report["finished_at"] = time.time()
            if setup_abort:
                report["classification"] = setup_abort
                report["classification_note"] = setup_note
                report["ok"] = False
            elif not setup_ready_for_sibling_click(setup_table):
                report["classification"] = ABORTED_S3_POST_REGISTRATION_NOT_READY
                report["classification_note"] = "setup_table_incomplete"
                report["ok"] = False
            else:
                report["classification"] = "SETUP_LOCALIZATION_PASS"
                report["classification_note"] = "setup_ready_for_full_s3_gate"
                report["ok"] = True
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(
                json.dumps(
                    {
                        "ok": bool(report.get("ok")),
                        "classification": report.get("classification"),
                        "artifact": str(out_path),
                        "setup_only": True,
                    }
                )
            )
            return 0 if report.get("ok") else 1

        if setup_abort:
            report["classification"] = setup_abort
            report["classification_note"] = setup_note
            report["ok"] = False
            report["finished_at"] = time.time()
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(out_path)}))
            return 1

        if not setup_ready_for_sibling_click(setup_table):
            report["classification"] = ABORTED_S3_POST_REGISTRATION_NOT_READY
            report["classification_note"] = "setup_table_incomplete"
            report["ok"] = False
            report["finished_at"] = time.time()
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(out_path)}))
            return 1

        post_reg = dict(post_reg)
        binding_pre = dict(binding)
        expected_sid = _expected_streamlit_session_id(report)

        if oob_setup_only:
            oob_step = _apply_oob_discovery_to_report(
                report,
                page=page,
                expected_streamlit_sid=expected_sid,
                connected_server_uri=connected_server_uri,
            )
            report["finished_at"] = time.time()
            if oob_step.get("unavailable") is not None:
                case, note, evidence = oob_step["unavailable"]
                report["classification"] = case
                report["classification_note"] = note
                report["oob_channel_evidence"] = evidence
                report["ok"] = False
            else:
                report["classification"] = OOB_CHANNEL_DISCOVERY_PASS
                report["classification_note"] = "oob_channel_ready_for_full_s3_gate"
                report["ok"] = True
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(
                json.dumps(
                    {
                        "ok": bool(report.get("ok")),
                        "classification": report.get("classification"),
                        "artifact": str(out_path),
                        "oob_setup_only": True,
                    }
                )
            )
            return 0 if report.get("ok") else 2

        oob_step = _apply_oob_discovery_to_report(
            report,
            page=page,
            expected_streamlit_sid=expected_sid,
            connected_server_uri=connected_server_uri,
        )
        if oob_step.get("unavailable") is not None:
            case, note, evidence = oob_step["unavailable"]
            report["classification"] = case
            report["classification_note"] = note
            report["oob_channel_evidence"] = evidence
            report["ok"] = False
            report["finished_at"] = time.time()
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(out_path)}))
            return 2

        oob_channel = dict(oob_step.get("oob_channel") or {})
        initial_oob_fetch = dict(oob_step.get("initial_oob_fetch") or {})
        pre_oob_snapshot = dict(oob_step.get("pre_oob_snapshot") or {})
        pre_oob_fresh = dict(oob_step.get("pre_oob_fresh") or {})
        ledger_pre = dict(oob_step.get("ledger_pre") or {})

        pre_sibling_scrape = ledger_pre if ledger_pre.get("found") else scrape_s3_server_diag_ledger(page)
        pre_sibling_fresh = extract_export_freshness_from_scrape(pre_sibling_scrape, local_scrape_ts=time.time())
        report["s3_export_freshness_pre_sibling_click"] = pre_sibling_fresh
        report["pre_click_export_generation"] = pre_sibling_fresh.get("export_generation")
        report["pre_sibling_oob_generation"] = pre_oob_fresh.get("snapshot_generation")

        sibling_expected_widget_id = str(post_reg.get("registered_widget_id") or "").strip()
        sibling_step = capture_sibling_pre_pause_transport(
            page,
            expected_widget_id=sibling_expected_widget_id,
        )
        report["sibling_strict_transport"] = sibling_step
        report["sibling_expected_widget_id"] = sibling_expected_widget_id

        static_url_path = str(oob_channel.get("static_url_path") or "")
        sibling_oob_wait = wait_for_oob_generation_after(
            page,
            static_url_path=static_url_path,
            min_generation=int(pre_oob_fresh.get("snapshot_generation") or 0),
            max_wait_s=30.0,
            connected_server_uri=connected_server_uri,
            require_connected_server_uri=True,
        )
        report["s3_oob_wait_after_sibling"] = sibling_oob_wait
        sibling_oob_snapshot = dict((sibling_oob_wait.get("fetch") or {}).get("snapshot") or {})
        post_sibling_oob_fresh = extract_oob_freshness_from_snapshot(sibling_oob_snapshot)
        report["s3_oob_freshness_post_sibling_click"] = post_sibling_oob_fresh
        report["s3_oob_freshness_sibling_delta"] = compare_oob_freshness(pre_oob_fresh, post_sibling_oob_fresh)
        stale_sibling_oob = classify_oob_freshness_after_sibling(
            pre_sibling_generation=int(pre_oob_fresh.get("snapshot_generation") or 0),
            post_sibling_freshness=post_sibling_oob_fresh,
        )
        if stale_sibling_oob is not None:
            case, note, evidence = stale_sibling_oob
            report["classification"] = case
            report["classification_note"] = note
            report["oob_freshness_evidence"] = evidence
            report["ok"] = False
            report["finished_at"] = time.time()
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(out_path)}))
            return 2

        post_sibling_scrape = scrape_s3_server_diag_ledger(page)
        post_sibling_fresh = extract_export_freshness_from_scrape(post_sibling_scrape, local_scrape_ts=time.time())
        report["s3_export_freshness_post_sibling_click"] = post_sibling_fresh
        report["post_sibling_export_generation"] = post_sibling_fresh.get("export_generation")
        report["s3_export_freshness_sibling_delta"] = compare_export_freshness(pre_sibling_fresh, post_sibling_fresh)
        wire_id, wire_target, strict_backmsg = _wire_from_sibling_step(sibling_step)
        report["wire_widget_id"] = wire_id
        report["wire_rerun_target_fragment_id"] = wire_target
        report["wire_fragment_id"] = wire_target  # legacy alias
        report["other_fragment_ids_observed"] = list(strict_backmsg.get("other_fragment_ids_observed") or [])
        report["wire_target_in_preclick_fragment_storage"] = wire_target_in_preclick_storage(wire_target, post_reg)
        report["sibling_user_key"] = f"stage1_pause_sibling_return_{room_id}_diag"
        report["browser_console_fragment_batch"] = sibling_step.get("browser_console_fragment_batch")
        report["target_backmsg_consistency"] = dict(
            sibling_step.get("target_backmsg_consistency")
            or strict_backmsg.get("target_backmsg_consistency")
            or {}
        )
        report["target_trigger_backmsg_seen"] = strict_backmsg.get("target_trigger_backmsg_seen")
        report["first_rerun_fragment_id"] = strict_backmsg.get("first_rerun_fragment_id")

        # Target-widget correlation requested: do not invent R2A/R2B from an unrelated first frame.
        if sibling_expected_widget_id and not strict_backmsg.get("target_trigger_backmsg_seen"):
            from stage1_s3_r3_observability_classify import (
                BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_INSTRUMENTATION_FAILURE,
            )

            report["classification"] = BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_INSTRUMENTATION_FAILURE
            report["classification_note"] = "sibling_target_trigger_backmsg_not_observed"
            report["observability_evidence"] = {
                "expected_widget_id": sibling_expected_widget_id,
                "target_trigger_backmsg_seen": False,
                "first_rerun_fragment_id": strict_backmsg.get("first_rerun_fragment_id"),
                "all_rerun_fragment_ids": list(strict_backmsg.get("all_rerun_fragment_ids") or []),
                "target_backmsg_consistency": report.get("target_backmsg_consistency"),
                "note": "harness_transport_observability_abort_not_r2_product_diagnosis",
            }
            report["ok"] = False
            report["finished_at"] = time.time()
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(out_path)}))
            return 2

        pause_step = _capture_pause_strict(page, room_id=room_id)
        report["pause_positive_control"] = pause_step
        report["pre_pause_export_generation"] = post_sibling_fresh.get("export_generation") or pre_sibling_fresh.get(
            "export_generation"
        )
        report["pre_pause_oob_generation"] = post_sibling_oob_fresh.get("snapshot_generation") or pre_oob_fresh.get(
            "snapshot_generation"
        )

        pause_oob_wait: dict[str, Any] = {"ok": False}
        pause_oob_snapshot: dict[str, Any] = {}
        post_pause_oob_fresh: dict[str, Any] = {}
        pause_evidence_settle: dict[str, Any] = {}
        if pause_step.get("pause_resolved"):
            pause_transport = dict(pause_step.get("streamlit_transport") or {})
            pause_strict = dict(pause_transport.get("strict_backmsg") or {})
            pause_widget_ids = list(pause_strict.get("activated_widget_ids") or [])
            pause_widget_id = str(pause_widget_ids[0] if pause_widget_ids else "")
            pause_evidence_settle = wait_for_oob_pause_evidence_settled_after(
                page,
                static_url_path=static_url_path,
                min_generation=int(report.get("pre_pause_oob_generation") or 0),
                streamlit_session_id=str(report.get("streamlit_session_id") or "")[:64],
                pause_widget_id=pause_widget_id,
                connected_server_uri=connected_server_uri,
                require_connected_server_uri=True,
            )
            report["s3_oob_pause_evidence_settle_after_pause"] = pause_evidence_settle
            # Retain prior field name as telemetry alias of the new settle result.
            report["s3_oob_settle_after_pause"] = {
                k: pause_evidence_settle.get(k)
                for k in (
                    "ok",
                    "settle_reason",
                    "min_generation_required",
                    "first_advanced_generation",
                    "first_snapshot_generation_after_pause",
                    "final_generation",
                    "final_snapshot_generation",
                    "final_publish_source",
                    "poll_count",
                    "wait_s",
                    "stable_poll_count",
                    "generations_observed",
                    "publish_sources_observed",
                )
            }
            pause_oob_wait = pause_evidence_settle
            report["s3_oob_wait_after_pause"] = pause_oob_wait
            pause_oob_snapshot = dict(pause_evidence_settle.get("final_snapshot") or {})
            post_pause_oob_fresh = extract_oob_freshness_from_snapshot(pause_oob_snapshot)
            report["s3_oob_freshness_post_pause"] = post_pause_oob_fresh
            report["s3_oob_freshness_pause_delta"] = compare_oob_freshness(
                post_sibling_oob_fresh if post_sibling_oob_fresh else pre_oob_fresh,
                post_pause_oob_fresh,
            )
            if not pause_evidence_settle.get("ok"):
                from stage1_s3_r3_observability_classify import (
                    BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_NOT_REFRESHED_AFTER_PAUSE,
                )

                report["classification"] = BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_NOT_REFRESHED_AFTER_PAUSE
                report["classification_note"] = str(pause_evidence_settle.get("settle_reason") or "pause_evidence_settle_failed")
                report["ok"] = False
                report["finished_at"] = time.time()
                out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
                browser.close()
                print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(out_path)}))
                return 2
            stale_pause_oob = classify_oob_freshness_after_pause(
                pause_resolved=True,
                pre_pause_generation=int(report.get("pre_pause_oob_generation") or 0),
                post_pause_freshness=post_pause_oob_fresh,
            )
            if stale_pause_oob is not None:
                case, note, evidence = stale_pause_oob
                report["classification"] = case
                report["classification_note"] = note
                report["oob_freshness_evidence"] = evidence
                report["ok"] = False
                report["finished_at"] = time.time()
                out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
                browser.close()
                print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(out_path)}))
                return 2
        else:
            report["s3_oob_freshness_post_pause"] = post_pause_oob_fresh

        page.wait_for_timeout(800)
        s3_after = scrape_s3_server_diag_ledger(page)
        post_pause_fresh = extract_export_freshness_from_scrape(s3_after, local_scrape_ts=time.time())
        report["s3_export_freshness_post_pause"] = post_pause_fresh
        dom_stale = classify_export_freshness_after_pause(
            pause_resolved=bool(pause_step.get("pause_resolved")),
            pre_pause_export_generation=int(report.get("pre_pause_export_generation") or 0),
            post_pause_freshness=post_pause_fresh,
        )
        report["s3_export_freshness_dom_stale_after_pause"] = (
            dict(dom_stale[2])
            if dom_stale is not None
            else {"classification": BUTTON_DISPATCH_S3_R3O0_SERVER_EXPORT_NOT_REFRESHED_AFTER_PAUSE, "skipped_for_oob_authority": True}
        )
        report["s3_server_diag_after_pause"] = s3_after
        payload = s3_after.get("payload") if isinstance(s3_after.get("payload"), dict) else {}
        ledger = (payload.get("ledger") or {}) if isinstance(payload, dict) else {}
        oob_authoritative_snapshot = pause_oob_snapshot if pause_oob_snapshot else sibling_oob_snapshot
        # Authority = rolling accumulated Pause-evidence rows (not the final bounded snapshot alone).
        if pause_evidence_settle.get("ok") and isinstance(pause_evidence_settle.get("accumulated_rows"), list):
            authoritative_rows = list(pause_evidence_settle.get("accumulated_rows") or [])
            auth_source = "oob_pause_evidence_accumulator"
        else:
            authoritative_rows = authoritative_rows_from_oob_snapshot(oob_authoritative_snapshot)
            auth_source = "oob_snapshot"
        auth_evidence = {
            "source": auth_source,
            "row_count": len(authoritative_rows),
            "authoritative_server_rows": authoritative_rows,
            "snapshot_generation": oob_authoritative_snapshot.get("snapshot_generation"),
            "publish_source": oob_authoritative_snapshot.get("publish_source"),
            "deepest_target_phase": pause_evidence_settle.get("deepest_target_phase"),
            "target_relevant_row_count": pause_evidence_settle.get("target_relevant_row_count"),
            "settle_reason": pause_evidence_settle.get("settle_reason"),
        }
        report["authoritative_server_evidence"] = auth_evidence
        report["s3_oob_authoritative_snapshot"] = oob_authoritative_snapshot
        s3_rows = list(authoritative_rows)
        unrouted_rows = list(oob_authoritative_snapshot.get("unrouted_rows") or [])
        binding_post = payload.get("s3_diag_binding") if isinstance(payload.get("s3_diag_binding"), dict) else {}
        report["s3_diag_binding_post_pause"] = binding_post
        report["fragment_owner_history"] = list(payload.get("fragment_owner_history") or [])[-16:]

        pre = pre_decl if isinstance(pre_decl, dict) else {}
        render_meta = dict((payload.get("post_registration") or {}))  # noqa: may include last render from pause ledger
        sibling_export = dict(sibling_step.get("scrape_after") or sibling_step.get("scrape_before") or {})
        sib_after = scrape_pause_sibling_probe(page)
        report["sibling_scrape_after"] = sib_after

        # Telemetry only: retain chronological REGISTER_RESULT values (must not drive R5/R6).
        register_result_telemetry: list[dict[str, Any]] = []
        for r in s3_rows:
            if r.get("phase") != "REGISTER_RESULT":
                continue
            register_result_telemetry.append(
                {
                    "event_id": r.get("event_id"),
                    "ts": r.get("ts"),
                    "register_widget_result_value": r.get("register_widget_result_value"),
                    "register_widget_value_changed": r.get("register_widget_value_changed"),
                    "script_run_seq": r.get("script_run_seq") or r.get("full_app_run_seq"),
                    "declaration_invocation_id": r.get("declaration_invocation_id"),
                    "user_key": r.get("user_key"),
                    "metadata_id": r.get("metadata_id"),
                }
            )
        report["register_result_telemetry"] = register_result_telemetry

        from stage1_s3_same_run_register_correlation import (
            S3_REGISTER_RESULT_SAME_RUN_NOT_OBSERVED,
            correlate_sibling_same_run_registration,
            register_result_for_classifier,
            st_button_for_classifier,
        )

        owner_fragment_preview = resolve_sibling_owner_fragment_id(
            post_reg, list(sibling_oob_snapshot.get("module_ledger_rows") or s3_rows)
        )
        same_run_corr = correlate_sibling_same_run_registration(
            s3_rows,
            wire_widget_id=str(wire_id or sibling_expected_widget_id or ""),
            user_key=str(post_reg.get("user_key") or ""),
            target_fragment_id=str(
                owner_fragment_preview
                or ((post_reg.get("widget_metadata") or {}).get("fragment_id") or "")
                or wire_target
                or ""
            ),
        )
        report["sibling_same_run_registration_correlation"] = same_run_corr
        reg_result = register_result_for_classifier(same_run_corr)
        reg_value_changed = same_run_corr.get("register_widget_value_changed")
        st_btn = st_button_for_classifier(same_run_corr)
        # Scrape may supplement C only when same-run button event absent (still not for B).
        if st_btn is None and sib_after.get("probe_found"):
            sib_payload = sib_after.get("payload") if isinstance(sib_after.get("payload"), dict) else {}
            lr = dict(sib_payload.get("last") or {})
            lr_render = dict(sib_payload.get("last_render") or {})
            inv = str(same_run_corr.get("declaration_invocation_id") or "")
            if inv and str(lr_render.get("declaration_invocation_id") or "") == inv and lr_render.get("st_button_returned") is not None:
                st_btn = bool(lr_render.get("st_button_returned"))
            elif inv and str(lr.get("declaration_invocation_id") or "") == inv and lr.get("st_button_returned") is not None:
                st_btn = bool(lr.get("st_button_returned"))

        owner_fragment = owner_fragment_preview
        report["sibling_owner_fragment_id"] = owner_fragment
        report["browser_candidate_wire_target_fragment"] = wire_target
        report["browser_candidate_owner_fragment"] = owner_fragment
        report["browser_candidate_wire_target_in_preclick_fragment_storage"] = wire_target_in_preclick_storage(
            wire_target, post_reg
        )

        instrumentation = classify_pause_instrumentation_failure(
            pause_resolved=bool(pause_step.get("pause_resolved")),
            authoritative_rows=authoritative_rows,
        )
        if instrumentation is not None:
            case, note, evidence = instrumentation
            report["classification"] = case
            report["classification_note"] = note
            report["observability_evidence"] = evidence
            report["ok"] = False
            report["finished_at"] = time.time()
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(out_path)}))
            return 2

        # R2 product classification requires proven target-trigger BackMsg for the sibling widget.
        if sibling_expected_widget_id and not strict_backmsg.get("target_trigger_backmsg_seen"):
            from stage1_s3_r3_observability_classify import (
                BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_INSTRUMENTATION_FAILURE,
            )

            report["classification"] = BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_INSTRUMENTATION_FAILURE
            report["classification_note"] = "sibling_target_trigger_backmsg_not_observed"
            report["ok"] = False
            report["finished_at"] = time.time()
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(out_path)}))
            return 2

        sibling_oob_r2 = classify_sibling_oob_r2_from_snapshot(
            oob_snapshot=sibling_oob_snapshot,
            wire_rerun_target_fragment_id=wire_target,
            owner_fragment_id=owner_fragment,
            wire_target_in_preclick_fragment_storage=wire_target_in_preclick_storage(wire_target, post_reg),
            strict_backmsg=strict_backmsg,
            wire_widget_id=wire_id,
            post_registration=post_reg,
        )
        if sibling_oob_r2 is not None:
            case, note, evidence = sibling_oob_r2
            report["classification"] = case
            report["classification_note"] = note
            report["r2_oob_evidence"] = evidence
            report["ok"] = False
            report["finished_at"] = time.time()
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(out_path)}))
            return 2

        # R5/R6 require same-run RegisterWidgetResult — never use pre-click setup false.
        if same_run_corr.get("server_applied_sibling") and reg_result is None:
            report["classification"] = S3_REGISTER_RESULT_SAME_RUN_NOT_OBSERVED
            report["classification_note"] = str(same_run_corr.get("first_missing_boundary") or "register_result_absent")
            report["register_widget_value_changed"] = reg_value_changed
            report["ok"] = False
            report["finished_at"] = time.time()
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(out_path)}))
            return 2

        base_case, base_note = classify_s3_server_registry(
            wire_widget_id=wire_id,
            wire_fragment_id=wire_target,
            post_registration=post_reg,
            strict_backmsg=strict_backmsg,
            s3_ledger_rows=s3_rows,
            sibling_python_effect=bool(sibling_step.get("sibling_python_effect")),
            register_widget_result=reg_result,
            st_button_returned=st_btn,
            pause_resolved=bool(pause_step.get("pause_resolved")),
        )
        click_ts = float(sibling_step.get("click_timestamp") or 0)
        r2_case, r2_note, r2_evidence = classify_s3_r2_subclass(
            wire_widget_id=wire_id,
            wire_rerun_target_fragment_id=wire_target,
            post_registration=post_reg,
            strict_backmsg=strict_backmsg,
            s3_ledger_rows=s3_rows,
            appsession_ingress_rows=[r for r in s3_rows if str(r.get("phase", "")).startswith("APPSESSION_")],
            sibling_click_ts=click_ts or None,
        )
        obs_case, obs_note, obs_evidence = classify_s3_with_observability(
            module_rows=s3_rows,
            authoritative_rows=authoritative_rows,
            pause_resolved=bool(pause_step.get("pause_resolved")),
            strict_backmsg=strict_backmsg,
            wire_widget_id=wire_id,
            sibling_python_effect=bool(sibling_step.get("sibling_python_effect")),
            register_widget_result=reg_result,
            st_button_returned=st_btn,
            binding_ok=binding_pre.get("sessionstate_binding_ok"),
            unrouted_rows=unrouted_rows,
        )
        if obs_case == "BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT":
            report["r3o0_row_inventory"] = {
                "runtime_rows": [r for r in authoritative_rows if r.get("phase") == "RUNTIME_BACKMSG_ENTRY"],
                "appsession_rows": [r for r in authoritative_rows if str(r.get("phase", "")).startswith("APPSESSION_")],
                "safe_sessionstate_rows": [r for r in authoritative_rows if r.get("phase") == "SAFE_SESSIONSTATE_RECEIVE_ENTRY"],
                "underlying_sessionstate_rows": [
                    r for r in authoritative_rows if r.get("phase") in ("SERVER_RECEIVE_ENTRY", "SERVER_STATE_APPLIED")
                ],
                "critical_ledger_rows": list(ledger.get("critical_server_rows") or []),
                "local_ledger_rows": list(ledger.get("local_rows") or []),
                "module_ledger_rows": list(ledger.get("module_rows") or []),
                "merged_authoritative_rows": authoritative_rows,
                "unrouted_rows": unrouted_rows,
                "live_wrapper_integrity": dict(binding_post.get("server_wrapper_integrity") or {}),
            }
            case, note = obs_case, obs_note
            report["observability_evidence"] = obs_evidence
            report["classification_legacy_base"] = base_case
            report["register_widget_value_changed"] = reg_value_changed
            report["classification"] = case
            report["classification_note"] = note
            report["pre_declaration_snapshot"] = pre
            report["wire_id_equals_post_registration"] = bool(wire_id and post_reg.get("registered_widget_id") == wire_id)
            report["room_id"] = room_id
            report["streamlit_session_id"] = sibling_step.get("streamlit_session_id")
            report["ok"] = False
            report["finished_at"] = time.time()
            out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(out_path)}))
            return 2
        if str(r2_case).startswith("BUTTON_DISPATCH_S3_R2") and r2_case not in (
            "BUTTON_DISPATCH_S3_R2C_OWNER_MATCH_AFTER_RECHECK",
        ):
            case, note = r2_case, r2_note
            report["r2_subclass_evidence"] = r2_evidence
            report["classification_observability"] = {"case": obs_case, "note": obs_note, "evidence": obs_evidence}
        else:
            case, note = obs_case, obs_note
            report["r2_subclass_evidence"] = r2_evidence
            report["observability_evidence"] = obs_evidence
        report["classification_legacy_base"] = base_case
        report["register_widget_value_changed"] = reg_value_changed
        report["classification"] = case
        report["classification_note"] = note
        report["pre_declaration_snapshot"] = pre
        report["wire_id_equals_post_registration"] = bool(wire_id and post_reg.get("registered_widget_id") == wire_id)
        report["room_id"] = room_id
        report["streamlit_session_id"] = sibling_step.get("streamlit_session_id")
        report["ok"] = not str(case).endswith("INCOMPLETE_EVIDENCE") and not str(case).startswith("ABORTED")
        report["finished_at"] = time.time()
        out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        browser.close()

    print(json.dumps({"ok": report.get("ok"), "classification": report.get("classification"), "artifact": str(out_path)}))
    return 0 if report.get("ok") else (1 if str(report.get("classification", "")).startswith("ABORTED") else 2)


if __name__ == "__main__":
    raise SystemExit(main())
