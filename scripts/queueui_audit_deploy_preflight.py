"""Strict Cloud SHA preflight for QUEUEUI root predicate audit."""

from __future__ import annotations

from typing import Any

QUEUEUIAUDIT_DEPLOY_BLOCK = (
    "QUEUEUIAUDIT_DEPLOY_BLOCK — REQUIRED APPLICATION DIAGNOSTIC BUILD NOT LIVE"
)
AUDIT_EXECUTION_NOT_RUN = "NOT_RUN"
DEFAULT_REQUIRED_DIAGNOSTIC_SHA = "4359938"
APPLICATION_DIAGNOSTIC_SHA = "4359938"


def normalize_sha(sha: str) -> str:
    return str(sha or "").strip().lower()[:7]


def verify_cloud_build_for_audit(
    *,
    live_sha: str,
    required_sha: str,
    application_diagnostic_sha: str = APPLICATION_DIAGNOSTIC_SHA,
) -> dict[str, Any]:
    """Exact equality required; no room creation or ROOT classification when blocked."""
    req = normalize_sha(required_sha)
    live = normalize_sha(live_sha)
    app = normalize_sha(application_diagnostic_sha)
    if not req:
        return {
            "passed": False,
            "audit_execution_status": AUDIT_EXECUTION_NOT_RUN,
            "first_boundary": QUEUEUIAUDIT_DEPLOY_BLOCK,
            "reason": "required_cloud_sha_unset",
            "required_cloud_sha": req,
            "live_cloud_sha": live,
            "application_diagnostic_sha": app,
        }
    if req != app:
        return {
            "passed": False,
            "audit_execution_status": AUDIT_EXECUTION_NOT_RUN,
            "first_boundary": QUEUEUIAUDIT_DEPLOY_BLOCK,
            "reason": "required_sha_must_match_application_diagnostic_sha",
            "required_cloud_sha": req,
            "live_cloud_sha": live,
            "application_diagnostic_sha": app,
        }
    if live != req:
        return {
            "passed": False,
            "audit_execution_status": AUDIT_EXECUTION_NOT_RUN,
            "first_boundary": QUEUEUIAUDIT_DEPLOY_BLOCK,
            "reason": "deployed_cloud_sha_not_equal_to_required",
            "required_cloud_sha": req,
            "live_cloud_sha": live,
            "application_diagnostic_sha": app,
        }
    return {
        "passed": True,
        "audit_execution_status": "READY",
        "first_boundary": "",
        "reason": "",
        "required_cloud_sha": req,
        "live_cloud_sha": live,
        "application_diagnostic_sha": app,
    }


def build_deploy_block_report(
    *,
    preflight: dict[str, Any],
    harness_sha: str,
    harness_sha_short: str,
    deploy_commit_pin: str = "",
    poll_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "audit": "queueui_root_predicate",
        "audit_execution_status": preflight.get("audit_execution_status"),
        "first_boundary": preflight.get("first_boundary"),
        "root_audit_status": "NOT RUN — REQUIRED DIAGNOSTIC BUILD WAS NOT DEPLOYED",
        "root_classification": None,
        "queueuiroot_classification": None,
        "required_cloud_sha": preflight.get("required_cloud_sha"),
        "live_cloud_sha": preflight.get("live_cloud_sha"),
        "application_diagnostic_sha": preflight.get("application_diagnostic_sha"),
        "deploy_commit_txt_pin": normalize_sha(deploy_commit_pin),
        "harness_sha": harness_sha,
        "harness_sha_short": harness_sha_short,
        "preflight": preflight,
        "deployment_poll": poll_evidence or {},
        "stage1a_core": "PASS",
        "stage1a_queue": "NOT_RUN — BLOCKED_BEFORE_EXPIRATION",
        "queue_campaign_ran": False,
        "expiration_wait": False,
    }
