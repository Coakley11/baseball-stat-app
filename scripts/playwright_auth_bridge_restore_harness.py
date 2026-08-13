"""Shared harness: restore Cloud auth via persisted browser bridge (no app changes)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CAPTURE_RESULT = ROOT / "data" / "capture_playwright_daniel_auth_once.result.json"


class BridgeSuiteSidConflictError(ValueError):
    """Explicit Stage 1 and root-audit bridge SIDs disagree."""


def resolve_bridge_suite_sid_with_source(*, capture_path: Path | None = None) -> tuple[str, str]:
    """Return (suite_sid, source). STAGE1_BRIDGE_SUITE_SID wins over ROOT_AUDIT."""
    stage1 = str(os.environ.get("STAGE1_BRIDGE_SUITE_SID") or "").strip()
    root_audit = str(os.environ.get("ROOT_AUDIT_BRIDGE_SUITE_SID") or "").strip()
    if stage1:
        if root_audit and root_audit != stage1:
            strict = str(os.environ.get("STAGE1_BRIDGE_SID_STRICT") or "").strip().lower() in ("1", "true", "yes")
            if strict:
                raise BridgeSuiteSidConflictError(
                    f"STAGE1_BRIDGE_SUITE_SID ({stage1[:8]}…) conflicts with ROOT_AUDIT_BRIDGE_SUITE_SID ({root_audit[:8]}…)"
                )
        return stage1, "STAGE1_BRIDGE_SUITE_SID"
    if root_audit:
        return root_audit, "ROOT_AUDIT_BRIDGE_SUITE_SID"
    if str(os.environ.get("ROOT_AUDIT_USE_CAPTURE_BRIDGE") or os.environ.get("STAGE1_USE_CAPTURE_BRIDGE") or "1").strip().lower() in (
        "0",
        "false",
        "no",
    ):
        return "", "none"
    cap_path = capture_path or CAPTURE_RESULT
    if not cap_path.is_file():
        return "", "none"
    try:
        data = json.loads(cap_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "", "capture_read_error"
    bp = (data.get("strict_capture") or {}).get("bridge_persistence") or {}
    sid = str(data.get("suite_sid") or "").strip()
    if sid and bp.get("persistence_succeeded"):
        return sid, "capture_result"
    return "", "capture_incomplete"


def resolve_bridge_suite_sid(*, capture_path: Path | None = None) -> str:
    sid, _src = resolve_bridge_suite_sid_with_source(capture_path=capture_path)
    return sid


def bridge_preflight_rejects_stale_session(*, bridge_sid: str, url_sid: str, authenticated: bool) -> str:
    """Return failure reason when bridge/session evidence mismatches."""
    if not bridge_sid:
        return "bridge_sid_missing"
    if url_sid and url_sid != bridge_sid:
        return "url_suite_sid_mismatch"
    if not authenticated:
        return "authenticated_session_not_bound"
    return ""


def resolve_real_accounts_wake(*, bridge_restore_mode: bool) -> bool:
    from bridge_hydration_waiter import resolve_real_accounts_wake as _resolve

    return _resolve(bridge_restore_mode=bridge_restore_mode)


_TIMEOUT_FORENSICS_CHECKPOINTS = (
    "load_browser_auth_tokens_lookup",
    "load_browser_auth_tokens",
    "restore_auth_session_entry",
    "restore_auth_session_exit",
    "restore_auth_session_exception",
    "apply_authenticated_user_exit",
    "restore_auth_session_after_apply",
)

_SAFE_CHECKPOINT_FIELDS = (
    "event_id",
    "timestamp",
    "event_ts",
    "ts",
    "script_run_seq",
    "event_index",
    "diagnostic_run_id",
    "run_id",
    "streamlit_session_id",
    "suite_sid_prefix",
    "rejection_reason",
    "skip_or_failure_reason",
    "exception_class",
    "auth_status",
    "auth_code",
    "message_sanitized",
    "access_token_present",
    "refresh_token_present",
    "browser_tokens_loaded",
    "token_record_found",
    "production_row_found",
    "production_record_complete",
    "record_status",
    "status",
    "row_id_prefix",
    "matching_row_id_prefix",
    "readback_row_id_prefix",
    "created_at",
    "updated_at",
    "expires_at",
    "expiration_state",
    "environment_fingerprint",
    "authenticated_before",
    "authenticated_after",
    "restore_attempt_seq",
    "apply_authenticated_user_ok",
    "apply_return_ok",
    "hydration_attempted",
    "persistence_attempted",
    "persistence_succeeded",
    "readback_record_complete",
    "invalid_rows_for_key",
)

_SECRET_KEY_FRAGMENTS = (
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "password",
    "secret",
    "bearer",
    "id_token",
)


def _is_secret_field_name(key: str) -> bool:
    kl = str(key or "").lower()
    if kl.endswith("_present") or kl.endswith("_ok") or kl.endswith("_prefix") or kl.endswith("_count"):
        return False
    if kl in ("access_token_present", "refresh_token_present", "browser_tokens_loaded"):
        return False
    return any(frag in kl for frag in _SECRET_KEY_FRAGMENTS)


def sanitize_hydration_checkpoint_snapshot(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """Copy safe diagnostic fields only — never token/cookie/secret values."""
    if not isinstance(row, dict):
        return None
    out: dict[str, Any] = {}
    for key in _SAFE_CHECKPOINT_FIELDS:
        if key not in row:
            continue
        if _is_secret_field_name(key):
            continue
        val = row.get(key)
        if isinstance(val, str) and len(val) > 240:
            out[key] = val[:240]
        else:
            out[key] = val
    # Boolean presence aliases already covered; never copy raw token-like values.
    for key, val in row.items():
        if key in out or _is_secret_field_name(key):
            continue
        if key in ("checkpoint", "event"):
            out[key] = str(val or "")[:120]
    if "token_record_found" not in out:
        if row.get("production_row_found") is not None:
            out["token_record_found"] = bool(row.get("production_row_found"))
        elif row.get("browser_tokens_loaded") is not None:
            out["token_record_found"] = bool(row.get("browser_tokens_loaded"))
    env = row.get("environment_fingerprint") or row.get("environment")
    if "environment_fingerprint" not in out:
        if isinstance(env, str) and env:
            out["environment_fingerprint"] = env[:64]
        elif isinstance(env, dict):
            fp = str(env.get("url_fingerprint") or env.get("fingerprint") or "").strip()
            if fp:
                out["environment_fingerprint"] = fp[:64]
    return out


def build_auth_restore_boundary_at_timeout(
    *,
    load_ok: bool,
    lookup_row: dict[str, Any] | None,
    restore_entry: dict[str, Any] | None,
    restore_exit: dict[str, Any] | None,
    restore_exception: dict[str, Any] | None,
    apply_exit: dict[str, Any] | None,
    after_apply: dict[str, Any] | None,
    bound: dict[str, Any] | None,
    start_enabled: bool,
) -> dict[str, Any]:
    lookup = lookup_row or {}
    bound = bound or {}
    return {
        "bridge_load_ok": bool(load_ok),
        "lookup_found": bool(lookup_row),
        "access_token_present": bool(lookup.get("access_token_present")),
        "refresh_token_present": bool(lookup.get("refresh_token_present")),
        "restore_entry_seen": bool(restore_entry),
        "restore_exit_seen": bool(restore_exit),
        "restore_exception_seen": bool(restore_exception),
        "apply_exit_seen": bool(apply_exit),
        "restore_after_apply_seen": bool(after_apply),
        "authenticated_at_timeout": bound.get("is_authenticated") is True,
        "auth_session_complete_at_timeout": bound.get("auth_session_complete") is True,
        "start_enabled_at_timeout": bool(start_enabled),
    }


def build_hydration_timeout_forensics(
    ledger: list[dict[str, Any]],
    *,
    streamlit_session_id: str,
    diagnostic_run_id: str,
    bound: dict[str, Any] | None,
    load_ok: bool,
    start_enabled: bool,
    url_sid: str = "",
    suite_sid: str = "",
    checkpoint: dict[str, Any] | None = None,
    dom: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Observability-only snapshots for AUTH_HYDRATE timeout (no secrets)."""
    from bridge_hydration_waiter import latest_hydration_checkpoint

    rows: dict[str, dict[str, Any] | None] = {}
    for cp in _TIMEOUT_FORENSICS_CHECKPOINTS:
        raw = latest_hydration_checkpoint(
            ledger,
            cp,
            streamlit_session_id=streamlit_session_id,
            diagnostic_run_id=diagnostic_run_id,
        )
        rows[cp] = sanitize_hydration_checkpoint_snapshot(raw)

    bound_safe = {
        k: (bound or {}).get(k)
        for k in (
            "session_flag_present",
            "is_authenticated",
            "auth_session_complete",
            "current_restore_blocked_reason",
            "apply_authenticated_user_ok",
            "field_sources",
        )
    }
    boundary = build_auth_restore_boundary_at_timeout(
        load_ok=load_ok,
        lookup_row=rows.get("load_browser_auth_tokens_lookup"),
        restore_entry=rows.get("restore_auth_session_entry"),
        restore_exit=rows.get("restore_auth_session_exit"),
        restore_exception=rows.get("restore_auth_session_exception"),
        apply_exit=rows.get("apply_authenticated_user_exit"),
        after_apply=rows.get("restore_auth_session_after_apply"),
        bound=bound,
        start_enabled=start_enabled,
    )
    # Re-derive presence from sanitized lookup (may be None when row absent).
    lookup = rows.get("load_browser_auth_tokens_lookup") or {}
    if rows.get("load_browser_auth_tokens_lookup") is None:
        boundary["access_token_present"] = False
        boundary["refresh_token_present"] = False
        boundary["lookup_found"] = False
    else:
        boundary["access_token_present"] = bool(lookup.get("access_token_present"))
        boundary["refresh_token_present"] = bool(lookup.get("refresh_token_present"))
        boundary["lookup_found"] = True

    cp = checkpoint or {}
    dom = dom or {}
    return {
        "streamlit_session_id": str(streamlit_session_id or "")[:36],
        "diagnostic_run_id": str(diagnostic_run_id or "")[:64],
        "url_suite_sid_prefix": str(url_sid or "")[:8],
        "bridge_suite_sid_prefix": str(suite_sid or "")[:8],
        "checkpoint_probe": str(cp.get("probe_checkpoint") or "")[:80],
        "dom_streamlit_session_id": str(dom.get("streamlit_session_id") or "")[:36],
        "checkpoints": rows,
        "bound_current_auth_at_timeout": bound_safe,
        "auth_restore_boundary_at_timeout": boundary,
    }


def attach_hydration_timeout_forensics(
    out: dict[str, Any],
    *,
    ledger: list[dict[str, Any]],
    streamlit_session_id: str,
    diagnostic_run_id: str,
    bound: dict[str, Any] | None,
    load_ok: bool,
    start_enabled: bool,
    url_sid: str = "",
    suite_sid: str = "",
    checkpoint: dict[str, Any] | None = None,
    dom: dict[str, Any] | None = None,
) -> None:
    """Mutate timeout result with final-poll scoped evidence (classification unchanged)."""
    from bridge_hydration_waiter import detect_restore_rerun_anomaly, summarize_hydration_sequence

    st_sid = str(streamlit_session_id or "")[:36]
    run_id = str(diagnostic_run_id or "")[:64]
    out["hydration_sequence"] = summarize_hydration_sequence(
        ledger, streamlit_session_id=st_sid, diagnostic_run_id=run_id
    )
    out["rerun_anomaly"] = detect_restore_rerun_anomaly(ledger, streamlit_session_id=st_sid)
    forensics = build_hydration_timeout_forensics(
        ledger,
        streamlit_session_id=st_sid,
        diagnostic_run_id=run_id,
        bound=bound,
        load_ok=load_ok,
        start_enabled=start_enabled,
        url_sid=url_sid,
        suite_sid=suite_sid,
        checkpoint=checkpoint,
        dom=dom,
    )
    out["bound_current_auth_at_timeout"] = forensics["bound_current_auth_at_timeout"]
    out["hydration_timeout_forensics"] = forensics
    out["auth_restore_boundary_at_timeout"] = forensics["auth_restore_boundary_at_timeout"]


def wait_bridge_auth_hydrated(
    page,
    suite_sid: str,
    scrape_ledger,
    *,
    timeout_s: float = 180.0,
    poll_interval_s: float = 2.0,
    initial_settle_ms: int = 0,
    preamble_mode: str = "stage1",
    expected_application_phase: str = "setup_lobby",
    standalone_start_consumed: bool = False,
) -> dict[str, Any]:
    from bridge_hydration_waiter import (
        AUTH_HYDRATE_FAIL_AUTH_API,
        bound_bridge_auth_only_passes,
        bound_bridge_hydration_passes,
        bridge_load_succeeded,
        detect_restore_rerun_anomaly,
        hydration_fail_fast_from_restore_exit,
        latest_hydration_checkpoint,
        summarize_hydration_sequence,
    )
    from stage1_application_phase import (
        EXPECTED_PHASE_AUTH_ONLY,
        EXPECTED_PHASE_SETUP_LOBBY,
        classify_hydration_timeout,
        classify_ldr_phase_from_page,
    )
    from playwright_auth_current_state_eval import evaluate_bound_current_auth_state
    from playwright_auth_observability import gather_page_observability, probe_dom_current_auth_state
    from playwright_auth_preflight_strict import inspect_start_control, suite_sid_from_url
    from queueui_audit_protocol import scrape_deploy_marker_from_page

    out: dict[str, Any] = {
        "bridge_restore_mode": True,
        "suite_sid": suite_sid,
        "suite_sid_prefix": suite_sid[:8] if suite_sid else "",
        "authenticated_restored": False,
        "failure": "",
        "failure_classification": "",
        "deployment_sha": "",
        "streamlit_session_id": "",
        "diagnostic_run_id": "",
        "preamble_mode": preamble_mode,
        "expected_application_phase": expected_application_phase,
        "hydration_polls": [],
        "first_divergence_from_isolated": "",
    }
    require_start = expected_application_phase == EXPECTED_PHASE_SETUP_LOBBY
    deadline = time.time() + timeout_s
    if initial_settle_ms > 0:
        page.wait_for_timeout(initial_settle_ms)
    poll_n = 0
    last_poll_ctx: dict[str, Any] = {
        "ledger": [],
        "bound": {},
        "dom": {},
        "checkpoint": {},
        "start": {},
        "st_sid": "",
        "run_id": "",
        "url_sid": "",
        "load_ok": False,
        "start_enabled": False,
    }
    while time.time() < deadline:
        poll_n += 1
        t_poll = time.time()
        if poll_n > 1:
            page.wait_for_timeout(int(max(poll_interval_s, 0.5) * 1000))
        deploy_sha, _ = scrape_deploy_marker_from_page(page)
        out["deployment_sha"] = str(deploy_sha or "")[:7]
        url_sid = suite_sid_from_url(page.url or "")
        reject = bridge_preflight_rejects_stale_session(
            bridge_sid=suite_sid, url_sid=url_sid, authenticated=False
        )
        if reject == "url_suite_sid_mismatch":
            out["failure"] = reject
            out["failure_classification"] = "AUTH_HYDRATE8"
            return out
        obs = gather_page_observability(page, harness_sid=suite_sid, strict_failure="")
        ledger = list(obs.get("ledger_rows_for_eval") or scrape_ledger(page) or [])
        cp = obs.get("checkpoint") or {}
        start = obs.get("start_surface") or inspect_start_control(page)
        fi = int(cp.get("start_frame_index") or start.get("frame_index") or 0)
        dom = probe_dom_current_auth_state(page, frame_index=fi) or cp.get("current_auth_dom") or {}
        run_id = str(cp.get("diagnostic_run_id") or "")[:64]
        st_sid = str(cp.get("streamlit_session_id") or "")[:36]
        out["streamlit_session_id"] = st_sid
        out["diagnostic_run_id"] = run_id

        restore_exit = latest_hydration_checkpoint(
            ledger, "restore_auth_session_exit", streamlit_session_id=st_sid, diagnostic_run_id=run_id
        )
        fail_fast = hydration_fail_fast_from_restore_exit(restore_exit)
        if fail_fast:
            out["failure"] = fail_fast
            out["failure_classification"] = "AUTH_HYDRATE3" if "AuthApiError" in fail_fast else "AUTH_HYDRATE8"
            out["restore_exit_snapshot"] = {
                k: restore_exit.get(k)
                for k in (
                    "skip_or_failure_reason",
                    "exception_class",
                    "auth_status",
                    "auth_code",
                    "message_sanitized",
                    "restore_attempt_seq",
                )
            } if restore_exit else {}
            out["hydration_sequence"] = summarize_hydration_sequence(
                ledger, streamlit_session_id=st_sid, diagnostic_run_id=run_id
            )
            out["rerun_anomaly"] = detect_restore_rerun_anomaly(ledger, streamlit_session_id=st_sid)
            return out

        bound = evaluate_bound_current_auth_state(
            current_auth_dom=dom,
            ledger_rows=ledger,
            diagnostic_run_id=run_id,
            streamlit_session_id=st_sid,
            start_enabled=bool(cp.get("start_enabled") or start.get("enabled")),
            start_visible=bool(cp.get("start_visible") or start.get("visible")),
        )
        load_ok = bridge_load_succeeded(ledger, streamlit_session_id=st_sid, diagnostic_run_id=run_id)
        start_enabled = bool(cp.get("start_enabled") or start.get("enabled"))
        start_visible = bool(cp.get("start_visible") if cp.get("start_visible") is not None else start.get("visible"))

        last_poll_ctx = {
            "ledger": ledger,
            "bound": bound,
            "dom": dom if isinstance(dom, dict) else {},
            "checkpoint": cp if isinstance(cp, dict) else {},
            "start": start if isinstance(start, dict) else {},
            "st_sid": st_sid,
            "run_id": run_id,
            "url_sid": url_sid,
            "load_ok": load_ok,
            "start_enabled": start_enabled,
        }

        poll_record = {
            "poll": poll_n,
            "elapsed_s": round(t_poll - (deadline - timeout_s), 2),
            "dom_bound": bool(dom.get("streamlit_session_id")),
            "load_ok": load_ok,
            "start_enabled": start_enabled,
            "is_authenticated": bound.get("is_authenticated"),
            "auth_session_complete": bound.get("auth_session_complete"),
            "restore_block": str(bound.get("current_restore_blocked_reason") or "")[:40],
        }
        out["hydration_polls"].append(poll_record)

        auth_only_ok = bound_bridge_auth_only_passes(
            bound,
            suite_sid=suite_sid,
            url_sid=url_sid or suite_sid,
            bridge_load_ok=load_ok,
        )
        if expected_application_phase == EXPECTED_PHASE_AUTH_ONLY and auth_only_ok:
            reject = bridge_preflight_rejects_stale_session(
                bridge_sid=suite_sid, url_sid=url_sid or suite_sid, authenticated=True
            )
            if reject:
                out["failure"] = reject
                return out
            out["authenticated_restored"] = True
            out["hydration_pass_mode"] = "auth_only"
            out["bound_current_auth"] = {
                k: bound.get(k)
                for k in (
                    "session_flag_present",
                    "is_authenticated",
                    "auth_session_complete",
                    "current_restore_blocked_reason",
                    "apply_authenticated_user_ok",
                    "field_sources",
                )
            }
            out["hydration_sequence"] = summarize_hydration_sequence(
                ledger, streamlit_session_id=st_sid, diagnostic_run_id=run_id
            )
            out["rerun_anomaly"] = detect_restore_rerun_anomaly(ledger, streamlit_session_id=st_sid)
            out["hydration_pass_poll"] = poll_n
            return out

        if bound_bridge_hydration_passes(
            bound,
            suite_sid=suite_sid,
            url_sid=url_sid or suite_sid,
            bridge_load_ok=load_ok,
            start_enabled=start_enabled,
            start_visible=start_visible,
            require_start=require_start,
        ):
            reject = bridge_preflight_rejects_stale_session(
                bridge_sid=suite_sid, url_sid=url_sid or suite_sid, authenticated=True
            )
            if reject:
                out["failure"] = reject
                return out
            out["authenticated_restored"] = True
            out["hydration_pass_mode"] = "setup_lobby"
            out["bound_current_auth"] = {
                k: bound.get(k)
                for k in (
                    "session_flag_present",
                    "is_authenticated",
                    "auth_session_complete",
                    "current_restore_blocked_reason",
                    "apply_authenticated_user_ok",
                    "field_sources",
                )
            }
            out["hydration_sequence"] = summarize_hydration_sequence(
                ledger, streamlit_session_id=st_sid, diagnostic_run_id=run_id
            )
            out["rerun_anomaly"] = detect_restore_rerun_anomaly(ledger, streamlit_session_id=st_sid)
            out["hydration_pass_poll"] = poll_n
            return out

    out["failure"] = "bridge_hydration_timeout"
    phase_info = classify_ldr_phase_from_page(page)
    out["application_phase_at_timeout"] = phase_info.get("application_phase")
    timeout_cls = classify_hydration_timeout(
        expected_application_phase=expected_application_phase,
        hydration_polls=out["hydration_polls"],
        application_phase=str(phase_info.get("application_phase") or ""),
        standalone_start_consumed=standalone_start_consumed,
    )
    out["failure_classification"] = timeout_cls.get("failure_classification") or "AUTH_HYDRATE7"
    out["hydration_timeout_root_cause"] = timeout_cls.get("root_cause")
    out["auth_complete_at_timeout"] = timeout_cls.get("auth_complete_at_timeout")
    if timeout_cls.get("mislabeled_as_auth_hydrate7"):
        out["first_divergence_from_isolated"] = timeout_cls.get("root_cause")
    elif out["hydration_polls"]:
        last = out["hydration_polls"][-1]
        if last.get("load_ok") and last.get("is_authenticated") and last.get("auth_session_complete"):
            out["first_divergence_from_isolated"] = (
                "timeout_despite_dom_auth_complete_likely_start_enabled_or_apply_predicate"
            )
    attach_hydration_timeout_forensics(
        out,
        ledger=list(last_poll_ctx.get("ledger") or []),
        streamlit_session_id=str(last_poll_ctx.get("st_sid") or out.get("streamlit_session_id") or ""),
        diagnostic_run_id=str(last_poll_ctx.get("run_id") or out.get("diagnostic_run_id") or ""),
        bound=dict(last_poll_ctx.get("bound") or {}),
        load_ok=bool(last_poll_ctx.get("load_ok")),
        start_enabled=bool(last_poll_ctx.get("start_enabled")),
        url_sid=str(last_poll_ctx.get("url_sid") or ""),
        suite_sid=suite_sid,
        checkpoint=dict(last_poll_ctx.get("checkpoint") or {}),
        dom=dict(last_poll_ctx.get("dom") or {}),
    )
    return out
