"""QUEUEUI root predicate audit harness protocol (no application behavior changes)."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from queueui_audit_deploy_preflight import (
    APPLICATION_DIAGNOSTIC_SHA,
    QUEUEUIAUDIT_DEPLOY_BLOCK,
    normalize_sha,
    verify_cloud_build_for_audit,
)

INVALID_PROTOCOL_RUN = "INVALID_PROTOCOL_RUN"
QUEUEUIAUDIT_UNEXPECTED_EXPIRATION_ACTIVITY = (
    "QUEUEUIAUDIT_UNEXPECTED_EXPIRATION_ACTIVITY"
)
QUEUEUIAUDIT_PRESTART_STATE_NOT_CLEAN = (
    "QUEUEUIAUDIT_PRESTART_STATE_NOT_CLEAN"
)
QUEUEUIAUDIT_ROOM_CREATION_NOT_PROVEN = "QUEUEUIAUDIT_ROOM_CREATION_NOT_PROVEN"
QUEUEUIAUDIT_ROOM_LATCH_NOT_PROVEN = "QUEUEUIAUDIT_ROOM_LATCH_NOT_PROVEN"
OPERATOR_VERIFIED_DEPLOY_ENV = "QUEUEUI_AUDIT_OPERATOR_VERIFIED_DEPLOY"
MIN_PREDICATE_SCRIPT_RUN_SEQ = 3
PREDICATE_EVENT = "production_stage1_queueui_predicate_audit"

_FORBIDDEN_EVENT_EXACT = frozenset(
    {
        "production_stage1_try_claim_about_to_call",
        "production_stage1_autopick_about_to_enter",
        "production_stage1_post_commit_state_entered",
    }
)

_FORBIDDEN_EVENT_PREFIXES = ("production_stage1_token_claim_",)

_START_HANDLER_ENTERED = "production_stage1_start_handler_entered"
_START_HANDLER_EXITED = "production_stage1_start_handler_exited"

_EVENT_ID_INDEX_RE = re.compile(r"^[^:]+:(\d+):")

_POST_CLICK_LEDGER_EVENTS = frozenset(
    {
        "production_stage1_start_callback_entered",
        "production_stage1_start_callback_exited",
        "production_stage1_pending_start_observed",
        "production_stage1_pending_start_consumed",
        "production_stage1_start_handler_entered",
        "production_stage1_start_handler_exited",
        "production_stage1_room_creation_entered",
        "production_stage1_room_creation_exited",
        "production_stage1_room_state_write",
        PREDICATE_EVENT,
    }
)


def ledger_event_index(row: dict[str, Any]) -> int:
    eid = str(row.get("event_id") or "")
    m = _EVENT_ID_INDEX_RE.match(eid)
    if not m:
        return -1
    try:
        return int(m.group(1))
    except ValueError:
        return -1


def _row_matches_baseline_identity(row: dict[str, Any], baseline: dict[str, Any]) -> bool:
    base_sid = str(baseline.get("streamlit_session_id") or "")
    row_sid = str(row.get("streamlit_session_id") or "")
    if base_sid and row_sid and row_sid != base_sid:
        return False
    base_run = str(baseline.get("diagnostic_run_id") or "")
    row_run = str(row.get("run_id") or "")
    if base_run and row_run and row_run != base_run:
        return False
    return True


def _ledger_extrema(ledger: list[dict[str, Any]]) -> dict[str, Any]:
    max_seq = 0
    max_ts = 0.0
    max_event_index = -1
    event_ids: list[str] = []
    for i, row in enumerate(ledger):
        if not isinstance(row, dict):
            continue
        seq = int(row.get("script_run_seq") or 0)
        if seq > max_seq:
            max_seq = seq
        ts = float(row.get("ts") or 0)
        if ts > max_ts:
            max_ts = ts
        eid = str(row.get("event_id") or "")
        if eid:
            event_ids.append(eid)
        idx = ledger_event_index(row)
        if idx > max_event_index:
            max_event_index = idx
    return {
        "highest_script_run_seq": max_seq,
        "latest_ledger_ts": max_ts,
        "ledger_row_count": len(ledger),
        "baseline_ledger_index_max": len(ledger) - 1 if ledger else -1,
        "baseline_event_index_max": max_event_index,
        "baseline_event_ids": event_ids,
    }


def capture_audit_baseline(
    ledger: list[dict[str, Any]],
    identity: dict[str, Any],
    lobby: dict[str, Any],
    *,
    preclick_captured_at: float | None = None,
    click_ts: float | None = None,
) -> dict[str, Any]:
    ext = _ledger_extrema(ledger)
    wake = lobby.get("wake") if isinstance(lobby.get("wake"), dict) else {}
    captured = float(preclick_captured_at if preclick_captured_at is not None else (click_ts or 0))
    return {
        "streamlit_session_id": str(identity.get("streamlit_session_id") or ""),
        "diagnostic_run_id": str(identity.get("diagnostic_run_id") or ""),
        **ext,
        "ledger_row_count_at_click": ext["ledger_row_count"],
        "preclick_baseline_captured_at": captured,
        "click_ts": captured,
        "click_dispatch_started_at": 0.0,
        "click_dispatch_completed_at": 0.0,
        "room_id_at_baseline": str(
            lobby.get("visible_room_id") or lobby.get("python_room_id") or ""
        ).strip(),
        "lifecycle_at_baseline": str(lobby.get("inferred_status") or lobby.get("lifecycle") or ""),
        "persistent_wake_token": str(wake.get("token") or "").strip(),
        "persistent_wake_phase": str(wake.get("phase") or "").strip(),
        "persistent_wake_actionable": str(wake.get("actionable") or "").strip(),
        "first_post_click_script_run_seq_min": ext["highest_script_run_seq"],
    }


def record_click_dispatch_times(
    baseline: dict[str, Any],
    *,
    dispatch_started_at: float,
    dispatch_completed_at: float,
) -> dict[str, Any]:
    """Attach dispatch timestamps without mutating frozen pre-click index fields."""
    baseline["click_dispatch_started_at"] = float(dispatch_started_at)
    baseline["click_dispatch_completed_at"] = float(dispatch_completed_at)
    return baseline


def update_first_post_click_script_run_seq(
    baseline: dict[str, Any], post_start_rows: list[dict[str, Any]]
) -> None:
    dispatch_started = float(baseline.get("click_dispatch_started_at") or 0)
    candidates: list[int] = []
    max_idx = int(baseline.get("baseline_event_index_max") or -1)
    for row in post_start_rows:
        seq = int(row.get("script_run_seq") or 0)
        if not seq:
            continue
        idx = ledger_event_index(row)
        if idx > max_idx:
            candidates.append(seq)
            continue
        ts = float(row.get("ts") or 0)
        if dispatch_started and ts >= dispatch_started:
            candidates.append(seq)
    if candidates:
        baseline["first_post_click_script_run_seq_min"] = min(candidates)


def row_is_post_start(row: dict[str, Any], baseline: dict[str, Any], row_index: int) -> bool:
    """Identity + monotonic ledger index gate for post–Start Draft rows."""
    if not isinstance(row, dict):
        return False
    if not _row_matches_baseline_identity(row, baseline):
        return False

    max_event_index = int(baseline.get("baseline_event_index_max") or -1)
    row_event_index = ledger_event_index(row)
    if row_event_index >= 0:
        if row_event_index > max_event_index:
            return True
        if row_event_index <= max_event_index:
            return False

    ledger_index_max = int(baseline.get("baseline_ledger_index_max") or -1)
    if row_index > ledger_index_max:
        dispatch_started = float(baseline.get("click_dispatch_started_at") or 0)
        ts = float(row.get("ts") or 0)
        if dispatch_started and ts and ts < dispatch_started:
            return False
        return True

    count_at_click = int(baseline.get("ledger_row_count_at_click") or 0)
    if row_index >= count_at_click:
        dispatch_started = float(baseline.get("click_dispatch_started_at") or 0)
        ts = float(row.get("ts") or 0)
        if dispatch_started and ts and ts < dispatch_started:
            return False
        return True
    return False


def refine_post_start_rows(
    post: list[dict[str, Any]], baseline: dict[str, Any]
) -> list[dict[str, Any]]:
    """Identity/index/ts gating only; do not drop same-run handler rows by seq alone."""
    update_first_post_click_script_run_seq(baseline, post)
    return list(post)


def partition_ledger_by_baseline(
    ledger: list[dict[str, Any]], baseline: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pre: list[dict[str, Any]] = []
    post: list[dict[str, Any]] = []
    for i, row in enumerate(ledger):
        if row_is_post_start(row, baseline, i):
            post.append(row)
        else:
            pre.append(row)
    post = refine_post_start_rows(post, baseline)
    return pre, post


def first_forbidden_in_rows(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in rows:
        hit = forbidden_protocol_event(row)
        if hit:
            return {"event": hit, "row": row}
    return None


def first_forbidden_after_baseline(
    ledger: list[dict[str, Any]], baseline: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
    pre, post = partition_ledger_by_baseline(ledger, baseline)
    stale = first_forbidden_in_rows(pre)
    violation = first_forbidden_in_rows(post)
    return violation, pre, post


def first_forbidden_protocol_violation(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Legacy: entire ledger scan (prefer first_forbidden_after_baseline)."""
    return first_forbidden_in_rows(rows)


def prestart_ledger_signals(
    ledger: list[dict[str, Any]],
    *,
    streamlit_session_id: str = "",
    diagnostic_run_id: str = "",
) -> dict[str, Any]:
    scoped: list[dict[str, Any]] = []
    for row in ledger:
        if not isinstance(row, dict):
            continue
        if streamlit_session_id:
            sid = str(row.get("streamlit_session_id") or "")
            if sid and sid != streamlit_session_id:
                continue
        if diagnostic_run_id:
            rid = str(row.get("run_id") or "")
            if rid and rid != diagnostic_run_id:
                continue
        scoped.append(row)
    if not scoped:
        scoped = list(ledger)
    max_seq = 0
    for row in scoped:
        max_seq = max(max_seq, int(row.get("script_run_seq") or 0))
    start_in_flight = False
    restore_blocked = ""
    for row in scoped:
        if max_seq and int(row.get("script_run_seq") or 0) != max_seq:
            continue
        preds = row.get("predicates")
        if isinstance(preds, dict) and preds.get("start_in_flight") is True:
            start_in_flight = True
        restore = row.get("restore")
        if isinstance(restore, dict):
            reason = str(restore.get("restore_blocked_reason") or "").strip()
            if reason:
                restore_blocked = reason
    return {
        "start_in_flight": start_in_flight,
        "restore_blocked_reason": restore_blocked,
        "latest_script_run_seq": max_seq,
    }


def evaluate_prestart_isolation(
    lobby: dict[str, Any],
    ledger: list[dict[str, Any]],
    *,
    setup_stable: dict[str, Any],
    streamlit_session_id: str = "",
    diagnostic_run_id: str = "",
    auth_preflight_passed: bool | None = None,
) -> dict[str, Any]:
    """Return passed=False when authoritative Start Draft must not be clicked."""
    reasons: list[str] = []
    if auth_preflight_passed is False:
        reasons.append("auth_preflight_failed")
    wake = lobby.get("wake") if isinstance(lobby.get("wake"), dict) else {}
    wake_token = str(wake.get("token") or "").strip()
    if lobby.get("visible_room_id") or lobby.get("python_room_id"):
        reasons.append("stale_room_id_visible")
    if str(lobby.get("python_room_present") or "") == "1":
        reasons.append("python_room_present")
    if int(lobby.get("pause_draft_count") or 0) >= 1 or lobby.get("has_pause"):
        reasons.append("active_draft_controls_visible")
    if wake_token and "|" in wake_token:
        reasons.append("stale_persistent_wake_token")
    if str(wake.get("actionable") or "") in ("1", "true"):
        reasons.append("persistent_wake_actionable")
    sig = prestart_ledger_signals(
        ledger,
        streamlit_session_id=streamlit_session_id,
        diagnostic_run_id=diagnostic_run_id,
    )
    if sig.get("start_in_flight"):
        reasons.append("start_in_flight_flag")
    if sig.get("restore_blocked_reason"):
        reasons.append(f"restore_blocked:{sig['restore_blocked_reason']}")
    if not setup_stable.get("ok"):
        reasons.append("setup_page_not_stable_two_script_runs")
    try:
        from stage1_preflight_cleanup import is_clean_setup_lobby

        if not is_clean_setup_lobby(lobby):
            reasons.append("not_clean_setup_lobby")
    except ImportError:
        if not lobby.get("has_start_new"):
            reasons.append("start_new_not_visible")
    return {
        "passed": not reasons,
        "reasons": reasons,
        "lobby_snapshot": lobby,
        "setup_stable": setup_stable,
        "ledger_signals": sig,
    }


def prestart_not_clean_report_fields(prestart: dict[str, Any]) -> dict[str, Any]:
    return {
        "audit_execution_status": "NOT_RUN",
        "first_boundary": QUEUEUIAUDIT_PRESTART_STATE_NOT_CLEAN,
        "root_classification": None,
        "queueuiroot_classification": None,
        "root_audit_status": "NOT RUN — PRESTART STATE NOT CLEAN (NO QUEUEUIROOT)",
        "prestart_isolation": prestart,
        "stage1a_core": "PASS",
        "stage1a_queue": "NOT_RUN — BLOCKED_BEFORE_EXPIRATION",
        "queue_campaign_ran": False,
        "expiration_wait": False,
    }


def distinct_global_script_run_seqs(ledger: list[dict[str, Any]]) -> list[int]:
    seen: set[int] = set()
    for row in ledger:
        if str(row.get("event") or "") != "production_global_script_run_canary":
            continue
        seq = int(row.get("script_run_seq") or 0)
        if seq:
            seen.add(seq)
    return sorted(seen)


def queueui_root_predicate_audit_url_base() -> str:
    """Production LDR URL for QUEUEUI audit — no shortened diag timer."""
    return (
        "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
        "?active_page=Live%20Draft%20Room"
        "&solo_component_diag=1&solo_stage1_parent_boundary=1"
    )


def queueui_audit_url_excludes_solo_diag_timer(url: str) -> bool:
    q = parse_qs(urlparse(url).query)
    return "solo_diag_timer" not in q


def scrape_deploy_marker_from_page(page) -> tuple[str, str]:
    """Return (sha, source). Prefer DOM probe, then visible caption / HTML patterns."""
    sha = ""
    source = ""
    try:
        from run_production_solo_soak import scrape_deploy_build

        sha = normalize_sha(scrape_deploy_build(page))
        if sha:
            return sha, "dom_solo_deploy_build"
    except Exception:
        pass
    try:
        from cloud_streamlit_wake import scrape_deploy_sha_from_page

        sha = normalize_sha(scrape_deploy_sha_from_page(page))
        if sha:
            return sha, "dom_scrape_deploy_sha"
    except Exception:
        pass
    try:
        from cloud_streamlit_wake import all_frames_text

        text = all_frames_text(page)
        m = re.search(r"solo-deploy-build\s+([0-9a-f]{7})\b", text, re.I)
        if m:
            return normalize_sha(m.group(1)), "visible_deploy_caption"
        m = re.search(r"baseball-dev-([0-9a-f]{7})\b", text, re.I)
        if m:
            return normalize_sha(m.group(1)), "visible_build_caption"
    except Exception:
        pass
    try:
        html = page.content()
        for pattern, src in (
            (r'id="solo-deploy-build"[^>]*data-sha="([0-9a-f]{7})"', "dom_html_data_sha"),
            (r"solo-deploy-build sha=([0-9a-f]{7})", "dom_html_comment"),
            (r"baseball-dev-([0-9a-f]{7})", "dom_html_build_label"),
        ):
            m = re.search(pattern, html, re.I)
            if m:
                return normalize_sha(m.group(1)), src
    except Exception:
        pass
    return "", "dom_scrape_empty"


def operator_verified_deploy_authorized(*, required: str, deploy_pin: str) -> bool:
    req = normalize_sha(required)
    pin = normalize_sha(deploy_pin)
    env_req = normalize_sha(os.environ.get("REQUIRED_CLOUD_SHA", ""))
    flag = str(os.environ.get(OPERATOR_VERIFIED_DEPLOY_ENV) or "").strip().lower()
    if flag not in ("1", "true", "yes"):
        return False
    return bool(req and pin == req and env_req == req)


def resolve_deployment_verification(
    page,
    pre: dict[str, Any],
    *,
    required: str,
    deploy_pin: str,
) -> dict[str, Any]:
    """DOM-first deploy verification; optional explicit operator startup-log mode."""
    live, dom_source = scrape_deploy_marker_from_page(page)
    if not live:
        try:
            from cloud_streamlit_wake import ensure_app_awake

            ensure_app_awake(page, timeout_s=120)
            page.wait_for_timeout(8000)
            live, dom_source = scrape_deploy_marker_from_page(page)
        except Exception:
            pass

    app_diag = normalize_sha(deploy_pin) or normalize_sha(required)

    out: dict[str, Any] = {
        "required_cloud_sha": normalize_sha(required),
        "deploy_commit_txt_pin": normalize_sha(deploy_pin),
        "live_cloud_sha": live,
        "dom_scrape_source": dom_source,
        "dom_marker_absent": not bool(live),
        "operator_verified_deploy_used": False,
        "operator_verified_deploy_env": OPERATOR_VERIFIED_DEPLOY_ENV,
    }

    if live:
        preflight = verify_cloud_build_for_audit(
            live_sha=live,
            required_sha=required,
            application_diagnostic_sha=app_diag,
        )
        out["verification_method"] = "dom_or_caption_scrape"
        out["preflight"] = preflight
        return out

    if operator_verified_deploy_authorized(required=required, deploy_pin=deploy_pin):
        live = normalize_sha(required)
        out["live_cloud_sha"] = live
        out["operator_verified_deploy_used"] = True
        out["verification_method"] = "operator_verified_cloud_startup_logs"
        out["operator_verification_note"] = (
            "DOM deploy marker absent; REQUIRED_CLOUD_SHA matches deploy_commit.txt; "
            f"{OPERATOR_VERIFIED_DEPLOY_ENV} authorized pre-verified Cloud startup logs."
        )
        preflight = verify_cloud_build_for_audit(
            live_sha=live,
            required_sha=required,
            application_diagnostic_sha=app_diag,
        )
        out["preflight"] = preflight
        return out

    preflight = verify_cloud_build_for_audit(
        live_sha="",
        required_sha=required,
        application_diagnostic_sha=app_diag,
    )
    out["verification_method"] = "failed_dom_scrape_no_operator_authorization"
    out["preflight"] = preflight
    return out


def forbidden_protocol_event(row: dict[str, Any]) -> str | None:
    ev = str(row.get("event") or "")
    if not ev:
        return None
    if ev in _FORBIDDEN_EVENT_EXACT:
        return ev
    for prefix in _FORBIDDEN_EVENT_PREFIXES:
        if ev.startswith(prefix):
            return ev
    if ev == "production_stage1_next_deadline_created":
        ctx = " ".join(
            str(row.get(k) or "")
            for k in ("source", "stage", "reason", "operation", "checkpoint")
        ).lower()
        if any(tok in ctx for tok in ("expire", "expiration", "autopick", "claim", "token")):
            return ev
        prior = str(row.get("after_expiration") or row.get("expiration") or "").lower()
        if prior in ("1", "true", "yes"):
            return ev
    if "autopick" in ev.lower() and "commit" in ev.lower():
        return ev
    if ev == "production_stage1_pick_committed":
        src = str(row.get("source") or row.get("stage") or "").lower()
        if "autopick" in src or "expire" in src:
            return ev
    if ev in (
        "production_stage1_process_production_expire_token_entry",
        "production_stage1_token_action_complete",
        "production_stage1_next_pick_state_computed",
    ):
        return ev
    return None


def first_forbidden_protocol_violation(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return first_forbidden_in_rows(rows)


def distinct_predicate_script_run_seq(rows: list[dict[str, Any]]) -> list[int]:
    seen: set[int] = set()
    for row in rows:
        if str(row.get("event") or "") != PREDICATE_EVENT:
            continue
        seq = int(row.get("script_run_seq") or 0)
        if seq > 0:
            seen.add(seq)
    return sorted(seen)


def evaluate_audit_completion(
    *,
    ledger_rows: list[dict[str, Any]],
    server_latch: dict[str, Any],
    room_id: str,
    protocol_violation: dict[str, Any] | None,
    start_click_observed: bool = False,
    ledger_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if protocol_violation:
        return {
            "audit_execution_status": INVALID_PROTOCOL_RUN,
            "first_boundary": QUEUEUIAUDIT_UNEXPECTED_EXPIRATION_ACTIVITY,
            "completed": False,
            "reason": "forbidden_expiration_token_autopick_or_commit_activity",
            "forbidden_event": protocol_violation.get("event"),
        }

    summary = dict(ledger_summary or {})
    seqs = distinct_predicate_script_run_seq(ledger_rows)
    rid = str(room_id or "").strip()
    latch_ok = bool(server_latch.get("ok"))
    status = str(server_latch.get("server_status") or "").lower()

    if not start_click_observed:
        return {
            "audit_execution_status": "INCOMPLETE",
            "first_boundary": QUEUEUIAUDIT_ROOM_CREATION_NOT_PROVEN,
            "completed": False,
            "reason": "start_draft_click_not_observed",
            "distinct_predicate_script_run_seq": seqs,
        }
    if not summary.get("handler_entered") or not summary.get("handler_exited"):
        return {
            "audit_execution_status": "INCOMPLETE",
            "first_boundary": QUEUEUIAUDIT_ROOM_CREATION_NOT_PROVEN,
            "completed": False,
            "reason": "start_handler_enter_or_exit_not_proven",
            "distinct_predicate_script_run_seq": seqs,
        }
    if not latch_ok or not rid:
        return {
            "audit_execution_status": "INCOMPLETE",
            "first_boundary": QUEUEUIAUDIT_ROOM_LATCH_NOT_PROVEN,
            "completed": False,
            "reason": "server_latch_or_room_id_missing",
            "distinct_predicate_script_run_seq": seqs,
        }
    if status and status not in ("in_progress", "paused"):
        return {
            "audit_execution_status": "INCOMPLETE",
            "first_boundary": QUEUEUIAUDIT_ROOM_CREATION_NOT_PROVEN,
            "completed": False,
            "reason": f"room_lifecycle_not_active:{status}",
            "distinct_predicate_script_run_seq": seqs,
        }
    if len(seqs) < MIN_PREDICATE_SCRIPT_RUN_SEQ:
        return {
            "audit_execution_status": "INCOMPLETE",
            "first_boundary": "QUEUEUIAUDIT_INSUFFICIENT_PREDICATE_EVIDENCE",
            "completed": False,
            "reason": "fewer_than_three_predicate_script_run_seq",
            "distinct_predicate_script_run_seq": seqs,
        }

    return {
        "audit_execution_status": "COMPLETED",
        "first_boundary": "",
        "completed": True,
        "reason": "",
        "distinct_predicate_script_run_seq": seqs,
    }


def invalid_protocol_report_fields(violation: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "audit_execution_status": INVALID_PROTOCOL_RUN,
        "first_boundary": QUEUEUIAUDIT_UNEXPECTED_EXPIRATION_ACTIVITY,
        "root_classification": None,
        "queueuiroot_classification": None,
        "root_audit_status": "INVALID — HARNESS PROTOCOL VIOLATION (NO QUEUEUIROOT)",
        "forbidden_protocol_event": (violation or {}).get("event"),
        "stage1a_core": "PASS",
        "stage1a_queue": "NOT_RUN — BLOCKED_BEFORE_EXPIRATION",
        "queue_campaign_ran": False,
        "expiration_wait": False,
    }


def deploy_block_from_preflight(preflight: dict[str, Any]) -> dict[str, Any]:
    return {
        "audit_execution_status": preflight.get("audit_execution_status", "NOT_RUN"),
        "first_boundary": preflight.get("first_boundary", QUEUEUIAUDIT_DEPLOY_BLOCK),
        "root_audit_status": "NOT RUN — DEPLOY PREFLIGHT FAILED",
        "root_classification": None,
        "queueuiroot_classification": None,
    }
