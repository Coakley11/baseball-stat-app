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
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"


def _harness_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
    except Exception:
        return ""


def _wire_from_sibling_step(sibling_step: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    tr = dict(sibling_step.get("streamlit_transport") or {})
    strict = dict(tr.get("strict_backmsg") or {})
    ids = list(strict.get("activated_widget_ids") or [])
    wire = str(ids[0] if ids else "")
    wire_target = str(strict.get("wire_rerun_target_fragment_id") or "").strip()
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
    from stage1_s3_r2_subclassify import classify_s3_r2_subclass, wire_target_in_preclick_storage
    from stage1_s3_r3_observability_classify import classify_s3_with_observability
    from stage1_s3_server_registry_classify import classify_s3_server_registry
    from stage1_s3_server_registry_scrape import (
        evaluate_post_registration_from_ledger,
        scrape_frame_dom_diagnostics,
        scrape_s3_server_diag_ledger,
    )
    from stage1_s3_setup_localize import (
        ABORTED_S3_POST_REGISTRATION_NOT_READY,
        build_setup_readiness_table,
        classify_setup_failure,
        setup_ready_for_sibling_click,
    )
    from stage1_pause_sibling_scrape import scrape_pause_sibling_probe
    from stage1_sibling_setup_scrape import scrape_sibling_setup_layers
    from streamlit_app_frame import describe_page_frames, resolve_streamlit_app_frame

    if str(os.environ.get("STAGE1_USE_CAPTURE_BRIDGE") or "").strip().lower() in ("0", "false"):
        print(json.dumps({"ok": False, "classification": "ABORTED_CAPTURE_BRIDGE_DISABLED"}))
        return 1

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
            "sibling_strict_click",
            "pause_positive_control",
            "classify_r3_chain",
        ],
        "started_at": time.time(),
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        install_proven_start_context_scripts(context)
        page = context.new_page()
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(12000)

        from p8_production_start_harness import scrape_stage1_ledger_rows
        from queueui_audit_protocol import scrape_deploy_marker_from_page

        deploy_sha, _ = scrape_deploy_marker_from_page(page)
        report["application_runtime_sha"] = str(deploy_sha or "")[:7]
        if required and str(report["application_runtime_sha"]).lower()[:7] != required:
            report["classification"] = "ABORTED_RUNTIME_SHA_MISMATCH"
            report["ok"] = False
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1

        bridge_pre = wait_bridge_auth_hydrated(page, bridge_sid, scrape_stage1_ledger_rows, timeout_s=240.0, preamble_mode="stage1")
        report["bridge_hydration"] = bridge_pre
        if not bridge_pre.get("authenticated_restored"):
            report["classification"] = bridge_pre.get("failure_classification") or "AUTH_HYDRATE7"
            report["ok"] = False
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1

        cleanup = run_stage1_preflight_cleanup(page, max_wait_s=180.0)
        report["preflight_cleanup"] = cleanup
        if not cleanup.get("ok"):
            report["classification"] = "ABORTED_SETUP_LOBBY"
            report["ok"] = False
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
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
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            return 1

        pause_ready = wait_for_authoritative_pause_control(page, max_wait_s=45.0, room_id=room_id)
        report["pause_control_ready"] = dict(pause_ready)
        report["app_frame_inventory"] = describe_page_frames(page)
        frame = resolve_streamlit_app_frame(page)
        report["app_frame_url"] = str(frame.url or "")[:240]

        sibling_layers = scrape_sibling_setup_layers(page, frame=frame)
        report["sibling_setup_layers"] = sibling_layers
        sibling_scrape = scrape_pause_sibling_probe(page, frame=frame)
        report["sibling_probe_scrape"] = sibling_scrape
        s3_ledger_scrape = scrape_s3_server_diag_ledger(page, frame=frame)
        report["s3_ledger_scrape_initial"] = s3_ledger_scrape
        report["frame_dom_diagnostics"] = scrape_frame_dom_diagnostics(page)

        post_reg, binding, pre_decl = evaluate_post_registration_from_ledger(s3_ledger_scrape)
        if s3_ledger_scrape.get("found") and not str(post_reg.get("registered_widget_id") or "").startswith("$$ID-"):
            post_wait = _wait_post_registration(page, max_wait_s=45.0)
            report["post_registration_poll"] = post_wait
            if isinstance(post_wait.get("scrape"), dict):
                s3_ledger_scrape = dict(post_wait["scrape"])
                post_reg = dict(post_wait.get("post_registration") or {})
                pre_click_payload = post_wait.get("scrape", {}).get("payload") if isinstance(post_wait.get("scrape"), dict) else {}
                if isinstance(pre_click_payload, dict):
                    binding = dict(pre_click_payload.get("s3_diag_binding") or {}) if isinstance(pre_click_payload.get("s3_diag_binding"), dict) else binding
                    pre_decl = dict(pre_click_payload.get("pre_declaration") or {}) if isinstance(pre_click_payload.get("pre_declaration"), dict) else pre_decl

        streamlit_sid = str(
            sibling_scrape.get("streamlit_session_id")
            or canonical.get("streamlit_session_id")
            or s3_ledger_scrape.get("payload", {}).get("ledger", {}).get("streamlit_session_id")
            or ""
        )[:64]
        setup_table = build_setup_readiness_table(
            runtime_sha=str(report.get("application_runtime_sha") or ""),
            auth_restored=bool(bridge_pre.get("authenticated_restored")),
            start_latch_pass=bool(canonical.get("room_latch_pass")),
            room_id=room_id,
            streamlit_session_id=streamlit_sid,
            pause_control_ready=bool(pause_ready.get("ready")),
            sibling_layers=sibling_layers,
            s3_ledger_found=bool(s3_ledger_scrape.get("found")),
            post_registration_ready=str(post_reg.get("registered_widget_id") or "").startswith("$$ID-"),
            binding_ok=bool(binding.get("sessionstate_binding_ok")),
        )
        report["setup_readiness_table"] = setup_table
        report["post_registration_server_snapshot"] = post_reg
        report["s3_diag_binding_pre_click"] = binding
        report["pre_declaration_snapshot"] = pre_decl

        setup_abort, setup_note = classify_setup_failure(
            pause_ready=pause_ready,
            sibling_layers=sibling_layers,
            s3_ledger_scrape=s3_ledger_scrape,
            post_registration=post_reg,
            binding=binding,
        )
        if setup_abort:
            report["classification"] = setup_abort
            report["classification_note"] = setup_note
            report["ok"] = False
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(OUT)}))
            return 1

        if not setup_ready_for_sibling_click(setup_table):
            report["classification"] = ABORTED_S3_POST_REGISTRATION_NOT_READY
            report["classification_note"] = "setup_table_incomplete"
            report["ok"] = False
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            browser.close()
            print(json.dumps({"ok": False, "classification": report["classification"], "artifact": str(OUT)}))
            return 1

        post_reg = dict(post_reg)
        binding_pre = dict(binding)

        sibling_step = capture_sibling_pre_pause_transport(page)
        report["sibling_strict_transport"] = sibling_step
        wire_id, wire_target, strict_backmsg = _wire_from_sibling_step(sibling_step)
        report["wire_widget_id"] = wire_id
        report["wire_rerun_target_fragment_id"] = wire_target
        report["wire_fragment_id"] = wire_target  # legacy alias
        report["other_fragment_ids_observed"] = list(strict_backmsg.get("other_fragment_ids_observed") or [])
        report["wire_target_in_preclick_fragment_storage"] = wire_target_in_preclick_storage(wire_target, post_reg)
        report["sibling_user_key"] = f"stage1_pause_sibling_return_{room_id}_diag"
        report["browser_console_fragment_batch"] = sibling_step.get("browser_console_fragment_batch")

        pause_step = _capture_pause_strict(page, room_id=room_id)
        report["pause_positive_control"] = pause_step

        page.wait_for_timeout(1200)
        s3_after = scrape_s3_server_diag_ledger(page)
        report["s3_server_diag_after_pause"] = s3_after
        payload = s3_after.get("payload") if isinstance(s3_after.get("payload"), dict) else {}
        ledger = (payload.get("ledger") or {}) if isinstance(payload, dict) else {}
        s3_rows = list(ledger.get("rows") or [])
        binding_post = payload.get("s3_diag_binding") if isinstance(payload.get("s3_diag_binding"), dict) else {}
        report["s3_diag_binding_post_pause"] = binding_post
        report["fragment_owner_history"] = list(payload.get("fragment_owner_history") or [])[-16:]

        pre = pre_decl if isinstance(pre_decl, dict) else {}
        render_meta = dict((payload.get("post_registration") or {}))  # noqa: may include last render from pause ledger
        sibling_export = dict(sibling_step.get("scrape_after") or sibling_step.get("scrape_before") or {})
        sib_after = scrape_pause_sibling_probe(page)
        report["sibling_scrape_after"] = sib_after

        reg_result = None
        reg_value_changed = None
        for r in s3_rows:
            if r.get("phase") == "REGISTER_RESULT":
                v = r.get("register_widget_result_value")
                if isinstance(v, bool):
                    reg_result = v
                reg_value_changed = r.get("register_widget_value_changed")
        st_btn = None
        if sib_after.get("probe_found"):
            sib_payload = sib_after.get("payload") if isinstance(sib_after.get("payload"), dict) else {}
            lr = dict(sib_payload.get("last") or {})
            lr_render = dict(sib_payload.get("last_render") or {})
            if lr.get("st_button_returned") is not None:
                st_btn = bool(lr.get("st_button_returned"))
            elif lr.get("returned_true") is not None:
                st_btn = bool(lr.get("returned_true"))
            elif lr_render.get("st_button_returned") is not None:
                st_btn = bool(lr_render.get("st_button_returned"))

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
            pause_resolved=bool(pause_step.get("pause_resolved")),
            strict_backmsg=strict_backmsg,
            wire_widget_id=wire_id,
            sibling_python_effect=bool(sibling_step.get("sibling_python_effect")),
            register_widget_result=reg_result,
            st_button_returned=st_btn,
            binding_ok=binding_pre.get("sessionstate_binding_ok"),
        )
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
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        browser.close()

    print(json.dumps({"ok": report.get("ok"), "classification": report.get("classification"), "artifact": str(OUT)}))
    return 0 if report.get("ok") else (1 if str(report.get("classification", "")).startswith("ABORTED") else 2)


if __name__ == "__main__":
    raise SystemExit(main())
