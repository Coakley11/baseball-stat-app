"""Verify Cloud deploy contains Stage 1 boundary canaries before P8 expiration trace."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent

CANARY_INTRO_COMMIT = "118215f"
ACCEPTABLE_CANARY_SHAS = frozenset({"118215f", "1d1d63b", "4c517f2"})


def git_head_short() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=ROOT,
                text=True,
                timeout=5,
            )
            .strip()
            .lower()[:7]
        )
    except Exception:
        return ""


def local_deploy_pin() -> str:
    try:
        line = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0]
        return line.split("#", 1)[0].strip().lower()[:7]
    except Exception:
        return ""


def commit_has_canary_implementation(sha: str) -> dict[str, Any]:
    """Confirm canary module and hooks exist at commit (not deploy_commit.txt alone)."""
    sha = str(sha or "").strip()[:7]
    out: dict[str, Any] = {
        "sha": sha,
        "ancestor_of_canary_intro": False,
        "file_live_draft_stage1_boundary_canaries_py": False,
        "streamlit_global_canary_hook": False,
        "streamlit_ldr_branch_canary_hook": False,
        "micro_core_declaration_canaries": False,
        "ok": False,
    }
    if not sha:
        return out
    try:
        subprocess.check_call(
            ["git", "merge-base", "--is-ancestor", CANARY_INTRO_COMMIT, sha],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        out["ancestor_of_canary_intro"] = True
    except subprocess.CalledProcessError:
        out["ancestor_of_canary_intro"] = sha in ACCEPTABLE_CANARY_SHAS
    except Exception as exc:
        out["git_error"] = type(exc).__name__

    try:
        subprocess.check_call(
            ["git", "cat-file", "-e", f"{sha}:live_draft_stage1_boundary_canaries.py"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        out["file_live_draft_stage1_boundary_canaries_py"] = True
    except Exception:
        out["file_live_draft_stage1_boundary_canaries_py"] = False

    try:
        subprocess.check_call(
            [
                "git",
                "grep",
                "-q",
                "emit_production_global_script_run_canary",
                sha,
                "--",
                "streamlit_app.py",
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        out["streamlit_global_canary_hook"] = True
    except Exception:
        out["streamlit_global_canary_hook"] = False

    try:
        subprocess.check_call(
            [
                "git",
                "grep",
                "-q",
                "emit_production_live_draft_branch_canary",
                sha,
                "--",
                "streamlit_app.py",
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        out["streamlit_ldr_branch_canary_hook"] = True
    except Exception:
        out["streamlit_ldr_branch_canary_hook"] = False

    try:
        subprocess.check_call(
            [
                "git",
                "grep",
                "-q",
                "production_countdown_declaration_pre",
                sha,
                "--",
                "solo_countdown_wake_micro_core.py",
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        out["micro_core_declaration_canaries"] = True
    except Exception:
        out["micro_core_declaration_canaries"] = False

    out["ok"] = (
        out["file_live_draft_stage1_boundary_canaries_py"]
        and out["streamlit_global_canary_hook"]
        and out["streamlit_ldr_branch_canary_hook"]
        and out["micro_core_declaration_canaries"]
        and (out["ancestor_of_canary_intro"] or sha in ACCEPTABLE_CANARY_SHAS)
    )
    return out


def commit_has_symmetric_observability(sha: str) -> dict[str, Any]:
    """Confirm ultra-early canary + declaration identity instrumentation at commit."""
    sha = str(sha or "").strip()[:7]
    out: dict[str, Any] = {
        "sha": sha,
        "file_widget_identity_py": False,
        "declaration_identity_fields": False,
        "ultra_early_global_canary_hook": False,
        "forwardmsg_decode_helper": False,
        "symmetric_harness": False,
        "ok": False,
    }
    if not sha:
        return out

    def _cat(path: str) -> bool:
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

    def _grep(pattern: str, *paths: str) -> bool:
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

    out["file_widget_identity_py"] = _cat("live_draft_stage1_widget_identity.py")
    out["declaration_identity_fields"] = _grep(
        "generated_internal_widget_id",
        sha,
        "live_draft_stage1_boundary_canaries.py",
        "live_draft_stage1_widget_identity.py",
    )
    out["ultra_early_global_canary_hook"] = _grep(
        "ultra_early_bootstrap",
        sha,
        "streamlit_app.py",
    )
    out["forwardmsg_decode_helper"] = _grep(
        "summarize_first_meaningful_inbound",
        sha,
        "scripts/p8_streamlit_backmsg_decode.py",
    )
    out["symmetric_harness"] = _cat("scripts/p8_streamlit_acceptance_symmetric.py")
    out["ok"] = all(
        [
            out["file_widget_identity_py"],
            out["declaration_identity_fields"],
            out["ultra_early_global_canary_hook"],
            out["forwardmsg_decode_helper"],
            out["symmetric_harness"],
            commit_has_canary_implementation(sha).get("ok"),
        ]
    )
    return out


def declaration_rows_have_identity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Ledger rows must carry declaration identity fields (not deploy_commit.txt alone)."""
    need = (
        "generated_internal_widget_id",
        "page_script_hash",
        "fragment_id",
        "streamlit_session_id_safe",
        "diagnostic_run_id",
    )
    pre = [r for r in rows if r.get("event") == "production_countdown_declaration_pre"]
    post = [r for r in rows if r.get("event") == "production_countdown_declaration_post"]
    sample = (post or pre)[-1] if (post or pre) else {}
    present = {k: bool(str(sample.get(k) or "").strip()) for k in need}
    return {
        "sample_event": str(sample.get("event") or ""),
        "fields_present": present,
        "ok": all(present.values()),
    }


def ledger_events(rows: list[dict[str, Any]]) -> list[str]:
    return [str(r.get("event") or "") for r in rows if isinstance(r, dict)]


def scrape_peak_ledger(page) -> list[dict[str, Any]]:
    from p8_ledger_observability import capture_all_ledger_sources

    cap = capture_all_ledger_sources(page, audit={})
    return list(cap.get("merged_incoming") or [])


def verify_pre_trace_canaries(
    page,
    *,
    poll_s: float = 45.0,
    interval_ms: int = 1500,
) -> dict[str, Any]:
    """Prove global + LDR branch canaries are emitted and captured before expiration trace."""
    from p8_diagnostic_setup import ensure_p8_ldr_setup_surface

    report: dict[str, Any] = {
        "global_canary_seen": False,
        "branch_canary_seen": False,
        "global_canary_rows": [],
        "branch_canary_rows": [],
        "classification": "",
    }
    t0 = time.time()
    peak: list[dict[str, Any]] = []
    while time.time() - t0 < poll_s:
        peak = scrape_peak_ledger(page)
        ev = ledger_events(peak)
        if "production_global_script_run_canary" in ev:
            report["global_canary_seen"] = True
            report["global_canary_rows"] = [
                r for r in peak if r.get("event") == "production_global_script_run_canary"
            ][:5]
            break
        page.wait_for_timeout(interval_ms)

    if not report["global_canary_seen"]:
        report["classification"] = "INVALID_CANARY_DEPLOY_OR_CAPTURE"
        report["reason"] = "no_production_global_script_run_canary_on_initial_load"
        return report

    ensure_p8_ldr_setup_surface(page, setup_url=page.url.split("?")[0] + "/")
    t1 = time.time()
    while time.time() - t1 < poll_s:
        peak = scrape_peak_ledger(page)
        ev = ledger_events(peak)
        if "production_live_draft_branch_canary" in ev:
            report["branch_canary_seen"] = True
            report["branch_canary_rows"] = [
                r for r in peak if r.get("event") == "production_live_draft_branch_canary"
            ][:5]
            break
        page.wait_for_timeout(interval_ms)

    if not report["branch_canary_seen"]:
        report["classification"] = "INVALID_CANARY_DEPLOY_OR_CAPTURE"
        report["reason"] = "no_production_live_draft_branch_canary_on_ldr_entry"
        return report

    report["classification"] = "CANARY_PRE_TRACE_OK"
    report["peak_ledger_row_count"] = len(peak)
    return report


def verify_declaration_canaries_after_mount(
    page,
    *,
    poll_s: float = 90.0,
    interval_ms: int = 1500,
) -> dict[str, Any]:
    """After in-progress draft + countdown mount, require declaration pre/post ledger events."""
    report: dict[str, Any] = {
        "declaration_pre_seen": False,
        "declaration_post_seen": False,
        "declaration_pre_rows": [],
        "declaration_post_rows": [],
        "classification": "",
    }
    t0 = time.time()
    peak: list[dict[str, Any]] = []
    while time.time() - t0 < poll_s:
        peak = scrape_peak_ledger(page)
        ev = ledger_events(peak)
        pre_ok = "production_countdown_declaration_pre" in ev
        post_ok = "production_countdown_declaration_post" in ev
        if pre_ok:
            report["declaration_pre_seen"] = True
            report["declaration_pre_rows"] = [
                r for r in peak if r.get("event") == "production_countdown_declaration_pre"
            ][:3]
        if post_ok:
            report["declaration_post_seen"] = True
            report["declaration_post_rows"] = [
                r for r in peak if r.get("event") == "production_countdown_declaration_post"
            ][:3]
        if pre_ok and post_ok:
            report["classification"] = "CANARY_DECLARATION_OK"
            report["peak_ledger_row_count"] = len(peak)
            return report
        page.wait_for_timeout(interval_ms)

    report["classification"] = "INVALID_CANARY_DEPLOY_OR_CAPTURE"
    if not report["declaration_pre_seen"]:
        report["reason"] = "no_production_countdown_declaration_pre_after_mount"
    else:
        report["reason"] = "no_production_countdown_declaration_post_after_mount"
    return report


def poll_live_cloud_sha(
    *,
    max_attempts: int = 24,
    sleep_s: float = 25.0,
    require_canary_impl: bool = True,
    require_symmetric_observability: bool = False,
) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from playwright.sync_api import sync_playwright
    from run_production_solo_soak import scrape_deploy_build
    from run_solo_clean_verification import scrape_live_sha
    from verify_cloud_deploy_playwright import scrape_deploy

    base = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
    url = (
        f"{base}?active_page=Live%20Draft%20Room"
        "&solo_component_diag=1&solo_diag_timer=10&solo_stage1_parent_boundary=1"
    )
    report: dict[str, Any] = {
        "git_head": git_head_short(),
        "local_deploy_pin": local_deploy_pin(),
        "attempts": [],
        "live_sha": "",
        "live_build": "",
        "implementation_at_live_sha": {},
        "ok": False,
    }

    for i in range(max_attempts):
        row: dict[str, Any] = {"attempt": i, "ts": time.time()}
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                goto_and_wake(page, url, timeout_s=240)
                page.wait_for_timeout(8000)
                probe = scrape_deploy(page)
                sha = (scrape_live_sha(page) or scrape_deploy_build(page) or probe.get("sha") or "")[:7].lower()
                build = str(probe.get("build") or "")
                row["sha"] = sha
                row["build"] = build
                impl = commit_has_symmetric_observability(sha) if require_symmetric_observability else commit_has_canary_implementation(sha)
                row["implementation"] = impl
                row["symmetric_observability"] = require_symmetric_observability
                report["attempts"].append(row)
                report["live_sha"] = sha
                report["live_build"] = build
                report["implementation_at_live_sha"] = impl
                browser.close()
                if require_symmetric_observability and impl.get("ok"):
                    report["ok"] = True
                    return report
                if require_canary_impl and impl.get("ok"):
                    report["ok"] = True
                    return report
                if not require_canary_impl and sha:
                    report["ok"] = True
                    return report
        except Exception as exc:
            row["error"] = type(exc).__name__
            report["attempts"].append(row)
        time.sleep(sleep_s)

    return report
