"""Focused P8 gate runtime presence checks (git-at-SHA, harness-only)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FOCUSED_GATE_SHA = "a5516e4"
BOOTREG1_HOTFIX_SHA = "cff25b8"
HANDOFF_BASE_SHA = "22ce3e3"
ROOM_LATCH_SHA = "a2e6eb2"


def _grep_at(sha: str, pattern: str, *paths: str) -> bool:
    try:
        subprocess.check_call(
            ["git", "grep", "-q", pattern, sha, "--", *paths],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        return True
    except Exception:
        return False


def _cat_at(sha: str, path: str) -> bool:
    try:
        subprocess.check_call(
            ["git", "cat-file", "-e", f"{sha}:{path}"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return True
    except Exception:
        return False


def commit_has_bootreg1_hotfix(sha: str) -> dict[str, Any]:
    from p8_canary_build_gate import git_sha_is_ancestor, git_short_sha

    short = git_short_sha(sha)
    checks = {
        "runtime_is_cff25b8_or_descendant": bool(
            short
            and (
                short == BOOTREG1_HOTFIX_SHA[:7]
                or git_sha_is_ancestor(BOOTREG1_HOTFIX_SHA[:7], short)
            )
        ),
        "raw_value_before_ledger_branch": _grep_at(
            short, "raw_value = raw_component_value", "solo_countdown_wake_micro_core.py"
        ),
        "coerced_initialized_before_ledger_if": _grep_at(
            short, "coerced = (", "solo_countdown_wake_micro_core.py"
        )
        and _grep_at(short, "if stage1_production_ledger_enabled(st, session):", "solo_countdown_wake_micro_core.py"),
        "bootreg1_regression_test_present": _cat_at(short, "tests/test_bootreg1_micro_core_coerced.py"),
    }
    return {"sha": short, "checks": checks, "ok": all(checks.values())}


def commit_has_focused_p8_gate(sha: str) -> dict[str, Any]:
    from p8_canary_build_gate import commit_has_binding_correction, git_sha_is_ancestor, git_short_sha

    short = git_short_sha(sha)
    binding = commit_has_binding_correction(short)
    checks = {
        "runtime_is_a5516e4_or_descendant": bool(
            short
            and (
                short == FOCUSED_GATE_SHA[:7]
                or git_sha_is_ancestor(FOCUSED_GATE_SHA[:7], short)
            )
        ),
        "focused_binding_module": _cat_at(short, "live_draft_solo_p8_focused_binding.py"),
        "solo_p8_focused_binding_query": _grep_at(
            short, "solo_p8_focused_binding", "live_draft_solo_p8_focused_binding.py"
        ),
        "harness_run_id_validation": _grep_at(
            short, "solo_p8_harness_run_id", "live_draft_solo_p8_focused_binding.py"
        ),
        "diagnostic_authorization": _grep_at(
            short, "focused_authorized", "live_draft_solo_p8_focused_binding.py"
        ),
        "diagnostic_only_handoff_metadata": _grep_at(
            short, "diagnostic_only", "live_draft_prod_callback_handoff.py"
        ),
        "focused_stop_after_observation": _grep_at(
            short,
            "observation_complete_stop_before_actionable_flush",
            "live_draft_stage1_post_bind_flush.py",
        ),
        "blocked_actionable_flush": _grep_at(
            short, "note_focused_flush_blocked", "live_draft_solo_persistent_wake.py"
        ),
        "blocked_pre_claim_gate": _grep_at(
            short, "note_focused_preclaim_blocked", "live_draft_stage1_process_token_gate.py"
        ),
        "focused_handoff_terminal_event": _grep_at(
            short,
            "production_stage1_p8_focused_handoff_terminal",
            "live_draft_solo_p8_focused_binding.py",
        ),
        "durable_callback_handoff_22ce3e3_ancestry": bool(
            short
            and (
                short == HANDOFF_BASE_SHA[:7]
                or git_sha_is_ancestor(HANDOFF_BASE_SHA[:7], short)
            )
            and binding.get("prod_callback_handoff_module")
        ),
        "room_latch_ancestry": bool(
            short and (short == ROOM_LATCH_SHA[:7] or git_sha_is_ancestor(ROOM_LATCH_SHA[:7], short))
        ),
        "p8c7_durable_handoff_gate": _grep_at(
            short, 'source == "durable_callback_handoff"', "live_draft_stage1_post_bind_flush.py"
        ),
        "p8b_return_value_bind": _grep_at(
            short, "return_value_session_bind", "live_draft_solo_persistent_wake.py"
        ),
        "n7_timer_reset_ancestry": _grep_at(short, "live_draft_reset_timer", "live_draft_timer_logic.py")
        or _grep_at(short, "reset_timer", "live_draft_solo_persistent_wake.py"),
    }
    return {
        "sha": short,
        "checks": checks,
        "binding_implementation": binding,
        "ok": all(checks.values()),
    }


def poll_focused_gate_deploy_readiness(
    *,
    required_sha: str,
    cap_s: float = 900.0,
    poll_s: float = 25.0,
    nav_timeout_s: int = 90,
    on_poll_attempt: Any | None = None,
) -> dict[str, Any]:
    """Lightweight deploy poll (short nav timeout, bounded wall clock)."""
    import time

    from cloud_streamlit_wake import goto_and_wake
    from p8_canary_build_gate import (
        evaluate_cloud_binding_readiness,
        local_deploy_pin,
        scrape_cloud_runtime_deploy_probe,
    )
    from playwright.sync_api import sync_playwright
    from run_production_solo_soak import scrape_deploy_build
    from run_solo_clean_verification import scrape_live_sha
    from verify_cloud_deploy_playwright import scrape_deploy

    base = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
    url = f"{base}?active_page=Live%20Draft%20Room&solo_component_diag=1&solo_diag_timer=10"
    pin = local_deploy_pin()
    req = str(required_sha or pin or "")[:7].lower()
    report: dict[str, Any] = {
        "mode": "focused_gate_lightweight_poll",
        "required_sha": req,
        "local_deploy_pin": pin,
        "cap_s": cap_s,
        "nav_timeout_s": nav_timeout_s,
        "attempts": [],
        "live_sha": "",
        "live_build": "",
        "ok": False,
        "focused_gate_presence": {},
        "elapsed_s": 0.0,
    }
    t0 = time.time()
    attempt = 0
    while time.time() - t0 < cap_s:
        attempt += 1
        row: dict[str, Any] = {"attempt": attempt, "ts": time.time(), "elapsed_s": round(time.time() - t0, 1)}
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                goto_and_wake(page, url, timeout_s=nav_timeout_s)
                page.wait_for_timeout(5000)
                probe = scrape_deploy(page)
                runtime_dom = scrape_cloud_runtime_deploy_probe(page)
                sha = (
                    runtime_dom.get("runtime_git_head_short")
                    or runtime_dom.get("marker_sha")
                    or (scrape_live_sha(page) or scrape_deploy_build(page) or probe.get("sha") or "")
                )[:7].lower()
                build = str(runtime_dom.get("marker_build") or probe.get("build") or "")
                row["sha"] = sha
                row["build"] = build
                row["runtime_probe"] = runtime_dom
                readiness = evaluate_cloud_binding_readiness(
                    runtime_git_head_short=str(runtime_dom.get("runtime_git_head_short") or sha),
                    marker_sha=str(runtime_dom.get("marker_sha") or sha),
                    marker_build=build,
                    deploy_pin=pin,
                    runtime_deploy_raw=str(runtime_dom.get("runtime_deploy_commit_raw") or ""),
                )
                row["binding_readiness"] = readiness
                presence = commit_has_focused_p8_gate(sha)
                row["focused_gate_presence"] = presence
                row["readiness_ok"] = bool(readiness.get("ok"))
                row["focused_gate_ok"] = bool(presence.get("ok"))
                browser.close()
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"[:300]
        report["attempts"].append(row)
        report["live_sha"] = str(row.get("sha") or report.get("live_sha") or "")
        report["live_build"] = str(row.get("build") or report.get("live_build") or "")
        if on_poll_attempt:
            on_poll_attempt(row, report)
        if row.get("focused_gate_ok") and row.get("readiness_ok"):
            report["ok"] = True
            report["focused_gate_presence"] = row.get("focused_gate_presence") or {}
            break
        time.sleep(poll_s)
    report["elapsed_s"] = round(time.time() - t0, 1)
    report["poll_count"] = len(report["attempts"])
    if report["attempts"]:
        last = report["attempts"][-1]
        report["binding_readiness"] = last.get("binding_readiness") or {}
        if not report.get("focused_gate_presence"):
            report["focused_gate_presence"] = last.get("focused_gate_presence") or {}
    return report


def poll_bootreg1_focused_readiness(
    *,
    required_sha: str = BOOTREG1_HOTFIX_SHA,
    cap_s: float = 900.0,
    poll_s: float = 25.0,
    nav_timeout_s: int = 90,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Bounded poll: cff25b8+ runtime, BOOTREG1 + focused gate git-at-SHA, LDR boot smoke."""
    import json
    import time

    from cloud_streamlit_wake import goto_and_wake
    from p8_canary_build_gate import (
        evaluate_cloud_binding_readiness,
        local_deploy_pin,
        scrape_cloud_runtime_deploy_probe,
    )
    from p8_focused_binding_heartbeat import diagnostic_run_id, log_line, write_heartbeat
    from playwright.sync_api import sync_playwright
    from run_production_solo_soak import all_frames_text, scrape_deploy_build
    from run_solo_clean_verification import scrape_live_sha
    from verify_cloud_deploy_playwright import scrape_deploy

    root_out = out_path or (ROOT / "data" / "p8_bootreg1_focused_readiness_poll.json")
    base = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
    url = f"{base}?active_page=Live%20Draft%20Room&solo_component_diag=1&solo_diag_timer=10"
    pin = local_deploy_pin()
    req = str(required_sha or pin or BOOTREG1_HOTFIX_SHA)[:7].lower()
    report: dict[str, Any] = {
        "mode": "bootreg1_focused_lightweight_poll",
        "diagnostic_run_id": diagnostic_run_id(),
        "required_sha": req,
        "local_deploy_pin": pin,
        "cap_s": cap_s,
        "nav_timeout_s": nav_timeout_s,
        "attempts": [],
        "live_sha": "",
        "live_build": "",
        "ok": False,
        "classification": "",
        "boot_smoke": {},
        "bootreg1_presence": {},
        "focused_gate_presence": {},
        "elapsed_s": 0.0,
    }
    log_line("bootreg1_focused_readiness_poll start")
    write_heartbeat("bootreg1_focused_readiness_start", required_cloud_sha=req)

    t0 = time.time()
    attempt = 0
    while time.time() - t0 < cap_s:
        attempt += 1
        row: dict[str, Any] = {"attempt": attempt, "ts": time.time(), "elapsed_s": round(time.time() - t0, 1)}
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                goto_and_wake(page, url, timeout_s=nav_timeout_s)
                page.wait_for_timeout(8000)
                probe = scrape_deploy(page)
                runtime_dom = scrape_cloud_runtime_deploy_probe(page)
                sha = (
                    runtime_dom.get("runtime_git_head_short")
                    or runtime_dom.get("marker_sha")
                    or (scrape_live_sha(page) or scrape_deploy_build(page) or probe.get("sha") or "")
                )[:7].lower()
                build = str(runtime_dom.get("marker_build") or probe.get("build") or "")
                text = all_frames_text(page)
                boot = {
                    "unbound_coerced_error": "UnboundLocalError" in text and "coerced" in text,
                    "ldr_heading": "Live Draft Room" in text,
                    "start_setup": "Start New Live Draft" in text,
                    "script_execution_error": "Script execution error" in text,
                    "text_len": len(text),
                }
                boot["ok"] = (
                    not boot["unbound_coerced_error"]
                    and not boot["script_execution_error"]
                    and boot["ldr_heading"]
                    and boot["start_setup"]
                    and boot["text_len"] > 500
                )
                row.update(
                    {
                        "sha": sha,
                        "build": build,
                        "runtime_probe": runtime_dom,
                        "boot_smoke": boot,
                        "binding_readiness": evaluate_cloud_binding_readiness(
                            runtime_git_head_short=str(
                                runtime_dom.get("runtime_git_head_short") or sha
                            ),
                            marker_sha=str(runtime_dom.get("marker_sha") or sha),
                            marker_build=build,
                            deploy_pin=pin,
                            runtime_deploy_raw=str(
                                runtime_dom.get("runtime_deploy_commit_raw") or ""
                            ),
                        ),
                        "bootreg1_presence": commit_has_bootreg1_hotfix(sha),
                        "focused_gate_presence": commit_has_focused_p8_gate(sha),
                    }
                )
                row["bootreg1_ok"] = bool((row.get("bootreg1_presence") or {}).get("ok"))
                row["focused_gate_ok"] = bool((row.get("focused_gate_presence") or {}).get("ok"))
                row["binding_ok"] = bool((row.get("binding_readiness") or {}).get("ok"))
                row["readiness_ok"] = (
                    row["bootreg1_ok"] and row["focused_gate_ok"] and row["binding_ok"] and boot["ok"]
                )
                browser.close()
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"[:400]

        report["attempts"].append(row)
        obs = str(row.get("sha") or "")
        report["live_sha"] = obs or report.get("live_sha", "")
        report["live_build"] = str(row.get("build") or report.get("live_build") or "")
        write_heartbeat(
            "bootreg1_focused_readiness_poll",
            required_cloud_sha=req,
            observed_cloud_sha=obs,
            extra={
                "attempt": attempt,
                "build": row.get("build"),
                "readiness_ok": row.get("readiness_ok"),
                "bootreg1_ok": row.get("bootreg1_ok"),
                "focused_gate_ok": row.get("focused_gate_ok"),
            },
        )
        log_line(
            f"bootreg1 poll attempt={attempt} sha={obs} build={row.get('build')} "
            f"ready={row.get('readiness_ok')}"
        )

        if row.get("readiness_ok"):
            report["ok"] = True
            report["boot_smoke"] = row.get("boot_smoke") or {}
            report["bootreg1_presence"] = row.get("bootreg1_presence") or {}
            report["focused_gate_presence"] = row.get("focused_gate_presence") or {}
            report["binding_readiness"] = row.get("binding_readiness") or {}
            write_heartbeat("bootreg1_focused_readiness_pass", required_cloud_sha=req, observed_cloud_sha=obs)
            break
        time.sleep(poll_s)

    report["elapsed_s"] = round(time.time() - t0, 1)
    report["poll_count"] = len(report["attempts"])
    if not report["ok"]:
        live = str(report.get("live_sha") or "")
        from p8_canary_build_gate import git_sha_is_ancestor, git_short_sha

        short = git_short_sha(live)
        on_hotfix = bool(
            short
            and (
                short == BOOTREG1_HOTFIX_SHA[:7]
                or git_sha_is_ancestor(BOOTREG1_HOTFIX_SHA[:7], short)
            )
        )
        if not on_hotfix:
            report["classification"] = "INVALID_BOOTREG1_HOTFIX_NOT_DEPLOYED"
            report["invalid_poll_supersession"] = (
                "Earlier poll attempts with empty observed SHA (broken evaluate_cloud_binding_readiness "
                "kwargs) are invalid; a later successful poll supersedes them."
            )
        elif report["attempts"]:
            last = report["attempts"][-1]
            report["boot_smoke"] = last.get("boot_smoke") or {}
            report["bootreg1_presence"] = last.get("bootreg1_presence") or {}
            report["focused_gate_presence"] = last.get("focused_gate_presence") or {}
            report["binding_readiness"] = last.get("binding_readiness") or {}
        write_heartbeat(
            "bootreg1_focused_readiness_fail",
            required_cloud_sha=req,
            observed_cloud_sha=live,
            extra={"classification": report.get("classification")},
        )
    root_out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report
