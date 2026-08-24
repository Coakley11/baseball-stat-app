"""Production gate: Context A → Pause → same-fragment probe → Francisco (F1–F4)."""

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
sys.path.insert(0, str(SCRIPTS))

OUT = ROOT / "data" / "production_bridge_rec_fragment_exec_gate.json"
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"


def _harness_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
    except Exception:
        return ""


def _queue_url(bridge_sid: str) -> str:
    timer = str(os.environ.get("SOLO_DIAG_TIMER") or "120").strip() or "120"
    from playwright_daniel_auth_session import append_suite_sid_to_url

    base = (
        f"{BASE}/?active_page=Live%20Draft%20Room"
        f"&solo_component_diag=1&solo_diag_timer={timer}&solo_stage1_parent_boundary=1"
    )
    return append_suite_sid_to_url(base, bridge_sid)


def main() -> int:
    from cloud_streamlit_wake import goto_and_wake
    from p8_canonical_production_start import establish_single_solo_live_draft
    from p8_proven_pause_delivery import PAUSE_DELIVERY_RESOLVED
    from p8_proven_start_delivery import install_proven_start_context_scripts
    from playwright.sync_api import sync_playwright
    from playwright_auth_bridge_restore_harness import (
        BridgeSuiteSidConflictError,
        resolve_bridge_suite_sid_with_source,
        wait_bridge_auth_hydrated,
    )
    from run_production_stage1_authenticated import (
        queue_setup_pause_for_seeding,
        redact_url,
        resolve_required_cloud_sha,
        scrape_queue_container_state,
    )
    from stage1_active_queue_surface import ACTIVE_QUEUE_SURFACE_RESOLVED, wait_for_active_queue_surface
    from stage1_application_phase import EXPECTED_PHASE_AUTH_ONLY, EXPECTED_PHASE_SETUP_LOBBY, classify_ldr_phase_from_page
    from stage1_parent_event_sink import ParentEventSinkStore, install_parent_event_sink
    from stage1_preflight_cleanup import run_stage1_preflight_cleanup
    from stage1_queue_seed_harness import wait_for_min_add_to_queue_controls
    from stage1_rec_fragment_exec_gate import (
        click_fragment_widget_probe,
        click_francisco_add_to_queue,
        classify_fragment_gate,
        prove_fragment_probe_rendered,
        snapshot_fragment_exec_context,
    )
    from stage1_run_binding import control_only_pause_binding_passes

    try:
        bridge_sid, bridge_source = resolve_bridge_suite_sid_with_source()
    except BridgeSuiteSidConflictError as exc:
        print(json.dumps({"ok": False, "classification": "ABORTED_BRIDGE_SID_CONFLICT", "detail": str(exc)}))
        return 1
    if not bridge_sid:
        print(json.dumps({"ok": False, "classification": "ABORTED_NO_BRIDGE_SID"}))
        return 1

    required = (resolve_required_cloud_sha() or os.environ.get("REQUIRED_CLOUD_SHA") or "f7e153f").strip().lower()[:7]
    url = _queue_url(bridge_sid)
    chronology: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "mode": "production_bridge_rec_fragment_exec_gate",
        "harness_sha": _harness_sha(),
        "expected_harness_sha": _harness_sha(),
        "required_cloud_sha": required,
        "expected_application_deploy_build": "baseball-dev-c6b36c1",
        "bridge_suite_sid_prefix": bridge_sid[:8],
        "bridge_suite_sid_source": bridge_source,
        "setup_url_redacted": redact_url(url),
        "started_at": time.time(),
        "artifact_path": str(OUT),
        "chronology": chronology,
    }

    room_id = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        report["proven_context_scripts"] = install_proven_start_context_scripts(context)
        parent_sink_store = ParentEventSinkStore()
        page = context.new_page()
        report["parent_event_sink_install"] = install_parent_event_sink(page, parent_sink_store)
        goto_and_wake(page, url, timeout_s=240)
        page.wait_for_timeout(15000)
        from p8_production_start_harness import scrape_stage1_ledger_rows
        from playwright_auth_bridge_restore_harness import resolve_real_accounts_wake

        settle_s = float(os.environ.get("BRIDGE_POST_CAPTURE_SETTLE_S", "8"))
        if settle_s > 0:
            page.wait_for_timeout(int(settle_s * 1000))
        if resolve_real_accounts_wake(bridge_restore_mode=True):
            try:
                page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
                page.wait_for_timeout(3000)
            except Exception:
                pass
        hydrate_timeout = float(os.environ.get("BRIDGE_HYDRATION_TIMEOUT_S", "240"))
        bridge_pre = wait_bridge_auth_hydrated(
            page,
            bridge_sid,
            scrape_stage1_ledger_rows,
            timeout_s=hydrate_timeout,
            poll_interval_s=float(os.environ.get("BRIDGE_HYDRATION_POLL_S", "2")),
            initial_settle_ms=0,
            preamble_mode="stage1",
            expected_application_phase=EXPECTED_PHASE_AUTH_ONLY,
        )
        report["bridge_hydration_auth_only"] = bridge_pre
        report["application_runtime_sha"] = str(bridge_pre.get("deployment_sha") or "")[:7]
        try:
            from queueui_audit_protocol import scrape_deploy_marker_from_page

            _sha, _src = scrape_deploy_marker_from_page(page)
            if _sha:
                report["application_runtime_sha"] = str(_sha)[:7]
            from run_production_solo_soak import scrape_deploy_build

            report["application_deploy_build"] = str(scrape_deploy_build(page) or "")
        except Exception:
            report["application_deploy_build"] = f"baseball-dev-{report['application_runtime_sha']}"
        if str(report.get("harness_sha") or "")[:7] != "0ff0781":
            report["harness_sha_warning"] = "expected_0ff0781"
        if str(report["application_runtime_sha"]).lower()[:7] != required:
            report["ok"] = False
            report["classification"] = "ABORTED_RUNTIME_SHA_MISMATCH"
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 1
        if not bridge_pre.get("authenticated_restored"):
            report["ok"] = False
            report["classification"] = bridge_pre.get("failure_classification") or "AUTH_HYDRATE7"
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 1
        report["application_phase_before_cleanup"] = classify_ldr_phase_from_page(page)
        cleanup = run_stage1_preflight_cleanup(page, max_wait_s=180.0)
        report["preflight_cleanup"] = cleanup
        if not cleanup.get("ok"):
            report["ok"] = False
            report["classification"] = "ABORTED_SETUP_LOBBY"
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 1
        bridge_setup = wait_bridge_auth_hydrated(
            page,
            bridge_sid,
            scrape_stage1_ledger_rows,
            timeout_s=hydrate_timeout,
            poll_interval_s=2.0,
            preamble_mode="stage1",
            expected_application_phase=EXPECTED_PHASE_SETUP_LOBBY,
        )
        report["bridge_hydration_setup_lobby"] = bridge_setup
        cleanup2 = run_stage1_preflight_cleanup(page, max_wait_s=120.0)
        report["preflight_cleanup_final"] = cleanup2
        if not cleanup2.get("ok") or not bridge_setup.get("authenticated_restored"):
            report["ok"] = False
            report["classification"] = "ABORTED_SETUP_LOBBY"
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 1
        canonical = establish_single_solo_live_draft(
            page,
            context,
            setup_url=url,
            prior_room_id="",
            fresh_lobby_cleanup=False,
            max_wait_s=90.0,
        )
        room_id = str(canonical.get("room_id") or canonical.get("created_room_id") or "").upper()
        report["start_latch"] = {"room_id": room_id, "room_latch_pass": canonical.get("room_latch_pass")}
        if not room_id or not canonical.get("room_latch_pass"):
            report["ok"] = False
            report["classification"] = "ABORTED_START_LATCH"
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 1
        chronology.append({"step": "start_latch", "room_id": room_id, "ts": time.time()})

        latch_ts = time.time()
        pause = queue_setup_pause_for_seeding(page, room_id=room_id, latch_completed_ts=latch_ts)
        report["pause_delivery"] = pause
        pause_ok = bool(pause.get("paused")) and pause.get("pause_classification") == PAUSE_DELIVERY_RESOLVED
        pause_click = pause.get("pause_click") if isinstance(pause.get("pause_click"), dict) else {}
        pause_obs = pause.get("pause_click_observability") if isinstance(pause.get("pause_click_observability"), dict) else {}
        pre_bind = pause_obs.get("pre_click_run_binding") if isinstance(pause_obs.get("pre_click_run_binding"), dict) else {}
        post_bind = pause_obs.get("post_click_run_binding") if isinstance(pause_obs.get("post_click_run_binding"), dict) else {}
        pause_dom = list(pause_click.get("browser_dom_click_events") or [])
        pause_install = pause_click.get("dom_click_capture_install") if isinstance(pause_click.get("dom_click_capture_install"), dict) else {}
        pause_binding_ok = control_only_pause_binding_passes(
            pre_bind,
            pause_delivery_resolved=pause_ok,
            dom_events_non_empty=bool(pause_dom),
            dom_install_ok=bool(pause_install.get("ok")),
        )
        pause_click = pause.get("pause_click") if isinstance(pause.get("pause_click"), dict) else {}
        pause_dom = pause_click.get("dom_click_capture") if isinstance(pause_click.get("dom_click_capture"), dict) else {}
        if not pause_dom.get("capture_target"):
            pause_dom = {
                "capture_target": "pause_draft",
                "trusted_dom_click": bool(pause_click.get("trusted_dom_click")),
                "browser_dom_click_events": list(pause_click.get("browser_dom_click_events") or []),
            }
        report["pause_control_A"] = {
            "pause_classification": pause.get("pause_classification"),
            "control_only_binding_pass": pause_binding_ok,
            "pre_click_run_binding": pre_bind,
            "post_click_run_binding": post_bind,
            "dom_click_capture": pause_dom,
            "browser_dom_click_events": list(pause_dom.get("browser_dom_click_events") or pause_click.get("browser_dom_click_events") or []),
        }
        chronology.append({"step": "pause_click", "ts": time.time(), "classification": pause.get("pause_classification")})
        if not pause_ok or not pause_binding_ok:
            report["ok"] = False
            report["classification"] = pause.get("pause_classification") or "QUEUEUI_PAUSE1"
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 2

        gate_start = {
            "latched_room_id": room_id,
            "in_progress": True,
            "room_latch_pass": True,
            "pause_ack_ts": float((pause.get("pause_timing") or {}).get("pause_click_dispatch_ts") or time.time()),
        }
        active = wait_for_active_queue_surface(
            page,
            start_val=gate_start,
            while_paused=True,
            auth_complete=True,
            run_id=str(canonical.get("application_diagnostic_run_id") or ""),
        )
        report["active_queue_surface_gate"] = active
        if not active.get("passed"):
            report["ok"] = False
            report["classification"] = active.get("classification") or "QUEUE_ACTIVE_PAGE8"
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 2

        add_wait = wait_for_min_add_to_queue_controls(page, min_controls=1, timeout_s=90.0, start_val=gate_start)
        report["add_control_wait"] = add_wait
        from stage1_rec_fragment_exec_gate import wait_for_rec_fragment_interactive_steady_state

        steady = wait_for_rec_fragment_interactive_steady_state(page, timeout_s=120.0)
        report["rec_fragment_steady_state"] = steady
        chronology.append(
            {
                "step": "heavy_paint_steady_state",
                "ts": time.time(),
                "ok": steady.get("ok"),
                "lifecycle": steady.get("lifecycle"),
            }
        )
        if not steady.get("ok"):
            report["ok"] = False
            report["classification"] = "ABORTED_FRAGMENT_NOT_STEADY_STATE"
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 2
        page.wait_for_timeout(2500)
        pre_surface_ctx = snapshot_fragment_exec_context(page)
        report["pre_interaction_exec_context"] = pre_surface_ctx
        chronology.append({"step": "recommendations_steady_fragment_interactive_live", "ts": time.time(), "ctx": "pre_probe"})

        probe_render_ok, probe_render_reason = prove_fragment_probe_rendered(pre_surface_ctx, room_id=room_id)
        report["fragment_probe_render_proof"] = {"ok": probe_render_ok, "reason": probe_render_reason}
        if not probe_render_ok:
            report["ok"] = False
            report["classification"] = "ABORTED_FRAGMENT_PROBE_NOT_RENDERED"
            report["finished_at"] = time.time()
            OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            context.close()
            browser.close()
            return 2

        probe_step = click_fragment_widget_probe(page)
        report["fragment_probe_control_B"] = probe_step
        chronology.append(
            {
                "step": "fragment_probe_click",
                "ts": time.time(),
                "callback_entered": probe_step.get("callback_entered"),
                "probe_result": probe_step.get("probe_result"),
                "trusted_dom_click": probe_step.get("trusted_dom_click"),
                "lifecycle_before": probe_step.get("lifecycle_before"),
                "lifecycle_after": probe_step.get("lifecycle_after"),
            }
        )

        probe_resolved = bool(probe_step.get("probe_callback_new_event") or probe_step.get("probe_result"))
        francisco_step: dict[str, Any] = {"skipped": True, "reason": "probe_callback_not_resolved"}
        if probe_resolved:
            francisco_step = click_francisco_add_to_queue(
                page,
                scrape_container_fn=scrape_queue_container_state,
                preferred_name=str(os.environ.get("STAGE1_SEED_PLAYER_NAME") or "Francisco Lindor"),
            )
            report["francisco_control_C"] = francisco_step
            chronology.append(
                {
                    "step": "francisco_click",
                    "ts": time.time(),
                    "callback_entered": francisco_step.get("callback_entered"),
                    "trusted_dom_click": francisco_step.get("trusted_dom_click"),
                    "mutation_proven": francisco_step.get("mutation_proven"),
                    "mutation_classification": francisco_step.get("mutation_classification"),
                }
            )
        else:
            report["francisco_control_C"] = francisco_step
            steady_lifecycle = steady.get("lifecycle") if isinstance(steady.get("lifecycle"), dict) else {}
            probe_trusted = bool(probe_step.get("trusted_dom_click"))
            probe_ledger = bool(probe_step.get("ledger_dom_observable"))
            if (
                steady.get("ok")
                and str(steady_lifecycle.get("paint_via_probe") or "")
                in ("full_page_interactive_live", "fragment_interactive_live")
                and probe_trusted
                and probe_ledger
                and not probe_step.get("callback_entered")
            ):
                report["classification"] = "QUEUE1C3A2F4"
                report["f4_note"] = "persists_on_c6b36c1_steady_fragment_interactive_live"
                report["ok"] = False
                report["finished_at"] = time.time()
                OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
                context.close()
                browser.close()
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "classification": report.get("classification"),
                            "room_id": room_id,
                            "harness_sha": report.get("harness_sha"),
                            "application_runtime_sha": report.get("application_runtime_sha"),
                            "f4_note": report.get("f4_note"),
                        }
                    )
                )
                return 2
            report["francisco_control_C"] = francisco_step

        if not probe_resolved:
            classification = report.get("classification") or "ABORTED_PROBE_NO_CALLBACK"
        else:
            classification = classify_fragment_gate(
                pause_ok=True,
                pause_dom=pause_dom,
                probe_step=probe_step,
                francisco_step=francisco_step,
                probe_render_ok=probe_render_ok,
            )
            mut_cls = francisco_step.get("mutation_classification")
            if mut_cls == "PLAYER_A_QUEUE_MUTATION_RESOLVED":
                classification = "PLAYER_A_QUEUE_MUTATION_RESOLVED"
        report["classification"] = classification
        report["provisional_prior"] = "QUEUE1C3A2F4"
        report["fragment_exec_comparison"] = {
            "pause_functional": True,
            "pause_trusted_dom_click": bool(pause_dom.get("trusted_dom_click")),
            "probe_callback_entered": probe_step.get("callback_entered"),
            "probe_trusted_click": probe_step.get("trusted_dom_click"),
            "probe_ledger_observable": probe_step.get("ledger_dom_observable"),
            "francisco_callback_entered": francisco_step.get("callback_entered"),
            "francisco_trusted_click": francisco_step.get("trusted_dom_click"),
            "francisco_mutation_proven": francisco_step.get("mutation_proven"),
            "francisco_ledger_observable": francisco_step.get("ledger_dom_observable"),
        }
        report["ok"] = classification in (
            "QUEUE1C3A2F4_RESOLVED",
            "PLAYER_A_QUEUE_MUTATION_RESOLVED",
            "QUEUE1C3A2F1",
            "QUEUE1C3A2F2",
            "QUEUE1C3A2F3",
            "QUEUE1C3A2F4",
        )
        report["finished_at"] = time.time()
        OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        context.close()
        browser.close()

    print(
        json.dumps(
            {
                "ok": report.get("ok"),
                "classification": report.get("classification"),
                "room_id": room_id,
                "harness_sha": report.get("harness_sha"),
                "application_runtime_sha": report.get("application_runtime_sha"),
            }
        )
    )
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
