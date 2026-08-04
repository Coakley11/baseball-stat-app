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
            application_diagnostic_sha=APPLICATION_DIAGNOSTIC_SHA,
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
            application_diagnostic_sha=APPLICATION_DIAGNOSTIC_SHA,
        )
        out["preflight"] = preflight
        return out

    preflight = verify_cloud_build_for_audit(
        live_sha="",
        required_sha=required,
        application_diagnostic_sha=APPLICATION_DIAGNOSTIC_SHA,
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
    for row in rows:
        if not isinstance(row, dict):
            continue
        hit = forbidden_protocol_event(row)
        if hit:
            return {"event": hit, "row": row}
    return None


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
) -> dict[str, Any]:
    if protocol_violation:
        return {
            "audit_execution_status": INVALID_PROTOCOL_RUN,
            "first_boundary": QUEUEUIAUDIT_UNEXPECTED_EXPIRATION_ACTIVITY,
            "completed": False,
            "reason": "forbidden_expiration_token_autopick_or_commit_activity",
            "forbidden_event": protocol_violation.get("event"),
        }

    seqs = distinct_predicate_script_run_seq(ledger_rows)
    rid = str(room_id or "").strip()
    latch_ok = bool(server_latch.get("ok"))

    if not latch_ok or not rid:
        return {
            "audit_execution_status": "INCOMPLETE",
            "first_boundary": "QUEUEUIAUDIT_ROOM_LATCH_NOT_PROVEN",
            "completed": False,
            "reason": "server_latch_or_room_id_missing",
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
