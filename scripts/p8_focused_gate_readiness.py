"""Focused P8 gate runtime presence checks (git-at-SHA, harness-only)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FOCUSED_GATE_SHA = "a5516e4"
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
                readiness = evaluate_cloud_binding_readiness(runtime_dom, local_pin=pin)
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
