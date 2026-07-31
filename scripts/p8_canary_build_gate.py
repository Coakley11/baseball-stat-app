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
        "actual_registered_widget_id",
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


def commit_has_binding_correction(sha: str) -> dict[str, Any]:
    """Verify BIND5 fix (18e7c15+): on_change parity, single mount, trace module."""
    sha = str(sha or "").strip()[:7]
    out: dict[str, Any] = {
        "sha": sha,
        "file_binding_trace_py": False,
        "micro_core_on_change_not_cleared_for_return_value": False,
        "micro_core_single_mount_guard": False,
        "micro_core_raw_return_cache": False,
        "persistent_wake_ldr_entry_guard": False,
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

    out["file_binding_trace_py"] = _cat("live_draft_component_binding_trace.py")
    out["micro_core_on_change_not_cleared_for_return_value"] = _grep(
        "mount_on_change = _prod_on_change",
        sha,
        "solo_countdown_wake_micro_core.py",
    )
    out["micro_core_single_mount_guard"] = _grep(
        "_solo_prod_mount_run_",
        sha,
        "solo_countdown_wake_micro_core.py",
    )
    out["micro_core_raw_return_cache"] = _grep(
        "_solo_prod_raw_return_",
        sha,
        "solo_countdown_wake_micro_core.py",
    )
    out["persistent_wake_ldr_entry_guard"] = _grep(
        "_solo_persistent_ldr_entry_run",
        sha,
        "live_draft_solo_persistent_wake.py",
    )
    out["ok"] = all(
        [
            out["file_binding_trace_py"],
            out["micro_core_on_change_not_cleared_for_return_value"],
            out["micro_core_single_mount_guard"],
            out["micro_core_raw_return_cache"],
            out["persistent_wake_ldr_entry_guard"],
        ]
    )
    return out


CALLBACK_OBS_ANCHOR_SHA = "919e196"


def commit_has_callback_observability(sha: str) -> dict[str, Any]:
    sha = str(sha or "").strip()[:7]
    out: dict[str, Any] = {
        "sha": sha,
        "file_prod_on_change_observability_py": False,
        "prod_on_change_entered_event": False,
        "callback_registration_event": False,
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

    out["file_prod_on_change_observability_py"] = _cat("live_draft_prod_on_change_observability.py")
    out["prod_on_change_entered_event"] = _grep(
        "production_stage1_prod_on_change_entered",
        "live_draft_prod_on_change_observability.py",
    )
    out["callback_registration_event"] = _grep(
        "production_stage1_callback_registration",
        "live_draft_prod_on_change_observability.py",
    )
    out["ok"] = (
        out["file_prod_on_change_observability_py"]
        and out["prod_on_change_entered_event"]
        and out["callback_registration_event"]
    )
    return out


BINDING_FIX_ANCHOR_SHA = "18e7c15"


def git_short_sha(sha: str) -> str:
    return str(sha or "").strip().lower()[:7]


def git_sha_is_ancestor(ancestor: str, descendant: str) -> bool:
    anc = git_short_sha(ancestor)
    des = git_short_sha(descendant)
    if not anc or not des:
        return False
    if anc == des:
        return True
    try:
        subprocess.check_call(
            ["git", "merge-base", "--is-ancestor", anc, des],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return True
    except subprocess.CalledProcessError:
        return False
    except Exception:
        return False


def expected_build_label_for_pin(pin: str) -> str:
    return f"baseball-dev-{git_short_sha(pin)}"


def parse_deploy_pin_token(raw: str) -> str:
    line = str(raw or "").splitlines()[0] if raw else ""
    return line.split("#", 1)[0].strip().lower()[:7]


def scrape_cloud_runtime_deploy_probe(page) -> dict[str, str]:
    """DOM markers: deploy pin (data-sha), build label, runtime git HEAD from fs probe."""
    from cloud_streamlit_wake import scrape_deploy_sha_from_page
    from verify_cloud_deploy_playwright import scrape_deploy

    out: dict[str, str] = {
        "marker_sha": "",
        "marker_build": "",
        "runtime_git_head": "",
        "runtime_git_head_short": "",
        "runtime_deploy_commit_raw": "",
    }
    try:
        probe = page.evaluate(
            """() => {
              function roots() {
                const r = [document];
                for (const f of document.querySelectorAll('iframe')) {
                  try { r.push(f.contentDocument); } catch (e) {}
                }
                return r.filter(Boolean);
              }
              const o = { deploy: {}, fs: {} };
              for (const root of roots()) {
                const el = root.querySelector('#solo-deploy-build');
                if (el && !o.deploy.sha) {
                  o.deploy = {
                    sha: (el.getAttribute('data-sha') || '').toLowerCase(),
                    build: el.getAttribute('data-build') || '',
                  };
                }
                const fs = root.querySelector('#solo-cloud-fs-probe');
                if (fs && !o.fs.git_head) {
                  o.fs = {
                    git_head: fs.getAttribute('data-git-head') || '',
                    deploy_raw: fs.getAttribute('data-deploy-commit-raw') || '',
                  };
                }
              }
              return o;
            }"""
        )
        if isinstance(probe, dict):
            dep = probe.get("deploy") or {}
            fs = probe.get("fs") or {}
            out["marker_sha"] = git_short_sha(dep.get("sha") or "")
            out["marker_build"] = str(dep.get("build") or "").strip()
            out["runtime_git_head"] = str(fs.get("git_head") or "").strip()
            out["runtime_git_head_short"] = git_short_sha(out["runtime_git_head"])
            out["runtime_deploy_commit_raw"] = str(fs.get("deploy_raw") or "")
    except Exception:
        pass
    if not out["marker_sha"]:
        harness = scrape_deploy(page)
        out["marker_sha"] = git_short_sha(harness.get("sha") or scrape_deploy_sha_from_page(page) or "")
        out["marker_build"] = str(harness.get("build") or "").strip()
    if not out["runtime_git_head_short"] and out["marker_sha"]:
        out["runtime_git_head_short"] = out["marker_sha"]
    return out


def evaluate_cloud_binding_readiness(
    *,
    runtime_git_head_short: str,
    marker_sha: str,
    marker_build: str,
    deploy_pin: str | None = None,
    runtime_deploy_raw: str = "",
) -> dict[str, Any]:
    """Cloud ready for BIND5 binding diagnostic — not deploy_commit.txt alone."""
    pin = git_short_sha(deploy_pin or local_deploy_pin())
    anchor = git_short_sha(BINDING_FIX_ANCHOR_SHA)
    runtime = git_short_sha(runtime_git_head_short)
    marker = git_short_sha(marker_sha)
    pin_from_runtime_raw = parse_deploy_pin_token(runtime_deploy_raw)
    expected_build = expected_build_label_for_pin(pin)
    impl_runtime = commit_has_binding_correction(runtime) if runtime else {}
    impl_at_marker = commit_has_binding_correction(marker) if marker else {}

    checks: dict[str, bool] = {
        "deploy_pin_marker_matches_local_pin": bool(pin and marker == pin),
        "deploy_pin_runtime_raw_matches_local_pin": bool(
            not pin_from_runtime_raw or pin_from_runtime_raw == pin
        ),
        "build_marker_matches_pin": marker_build == expected_build,
        "runtime_git_contains_binding_anchor": bool(
            runtime and (runtime == anchor or git_sha_is_ancestor(anchor, runtime))
        ),
        "binding_implementation_at_runtime_git": bool(impl_runtime.get("ok")),
    }
    ok = all(checks.values())
    return {
        "deploy_pin": pin,
        "binding_fix_anchor": anchor,
        "runtime_git_head_short": runtime,
        "marker_sha": marker,
        "marker_build": marker_build,
        "expected_build": expected_build,
        "checks": checks,
        "implementation_at_runtime_git": impl_runtime,
        "implementation_at_marker_sha": impl_at_marker,
        "ok": ok,
    }


def declaration_rows_have_identity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Ledger rows must carry declaration identity fields (not deploy_commit.txt alone)."""
    need = (
        "actual_registered_widget_id",
        "predicted_element_id",
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

    ensure_p8_ldr_setup_surface(page, setup_url=page.url)
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
    wait_for_deploy_pin: bool = False,
    wait_for_binding_readiness: bool = False,
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
        "binding_readiness": {},
        "ok": False,
    }
    pin = local_deploy_pin()
    wait_binding = wait_for_binding_readiness or wait_for_deploy_pin

    for i in range(max_attempts):
        row: dict[str, Any] = {"attempt": i, "ts": time.time()}
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                goto_and_wake(page, url, timeout_s=240)
                page.wait_for_timeout(8000)
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
                impl = commit_has_symmetric_observability(sha) if require_symmetric_observability else commit_has_canary_implementation(sha)
                row["implementation"] = impl
                row["symmetric_observability"] = require_symmetric_observability
                readiness = evaluate_cloud_binding_readiness(
                    runtime_git_head_short=runtime_dom.get("runtime_git_head_short") or sha,
                    marker_sha=runtime_dom.get("marker_sha") or "",
                    marker_build=build,
                    deploy_pin=pin,
                    runtime_deploy_raw=runtime_dom.get("runtime_deploy_commit_raw") or "",
                )
                row["binding_readiness"] = readiness
                report["attempts"].append(row)
                report["live_sha"] = sha
                report["live_build"] = build
                report["binding_readiness"] = readiness
                report["implementation_at_live_sha"] = readiness.get("implementation_at_runtime_git") or impl
                browser.close()
                if wait_binding:
                    if not readiness.get("ok"):
                        time.sleep(sleep_s)
                        continue
                    report["ok"] = True
                    return report
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
