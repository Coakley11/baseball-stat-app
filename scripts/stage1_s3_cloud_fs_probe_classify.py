"""Harness classification for Cloud fs probe scrape results."""

from __future__ import annotations

import json
from typing import Any

CLOUD_FS_PROBE_CHECKOUT_AND_STATIC_CONFIG_PRESENT = "CLOUD_FS_PROBE_CHECKOUT_AND_STATIC_CONFIG_PRESENT"
CLOUD_FS_PROBE_CHECKOUT_STALE_OR_ASSET_MISSING = "CLOUD_FS_PROBE_CHECKOUT_STALE_OR_ASSET_MISSING"
CLOUD_FS_PROBE_STATIC_CONFIG_NOT_EFFECTIVE = "CLOUD_FS_PROBE_STATIC_CONFIG_NOT_EFFECTIVE"
CLOUD_FS_PROBE_UNAVAILABLE = "CLOUD_FS_PROBE_UNAVAILABLE"
PROBE_ASSET_INTRO_SHA = "6394eb6"


def extract_fs_probe_payload(scrape: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(scrape, dict):
        return {}
    if scrape.get("found") and isinstance(scrape.get("payload"), dict):
        return dict(scrape["payload"])
    data_json = scrape.get("data-json") or scrape.get("data_json")
    if isinstance(data_json, str) and data_json.strip():
        try:
            parsed = json.loads(data_json)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    for key, value in scrape.items():
        if key.startswith("data-") and key.endswith("-json"):
            try:
                parsed = json.loads(str(value))
                return dict(parsed) if isinstance(parsed, dict) else {}
            except Exception:
                continue
    return {}


def classify_cloud_fs_probe_scrape(scrape: dict[str, Any] | None) -> tuple[str, str, dict[str, Any]]:
    scrape = dict(scrape or {})
    if not scrape.get("found"):
        return CLOUD_FS_PROBE_UNAVAILABLE, "fs_probe_marker_not_mounted", {"scrape": scrape}
    payload = extract_fs_probe_payload(scrape)
    if not payload:
        return CLOUD_FS_PROBE_UNAVAILABLE, "fs_probe_payload_unreadable", {"scrape": scrape}
    evidence = {
        "git_head": payload.get("git_head"),
        "git_head_short": payload.get("git_head_short"),
        "git_branch": payload.get("git_branch"),
        "deploy_pin": payload.get("deploy_pin"),
        "app_runtime_deploy_marker": payload.get("app_runtime_deploy_marker"),
        "repo_static_probe_exists": payload.get("repo_static_probe_exists"),
        "repo_static_probe_sentinel_ok": payload.get("repo_static_probe_sentinel_ok"),
        "effective_enable_static_serving": payload.get("effective_enable_static_serving"),
        "git_head_contains_probe_asset": payload.get("git_head_contains_probe_asset"),
    }
    if payload.get("repo_static_probe_exists") and payload.get("effective_enable_static_serving") is True and (
        payload.get("git_head_contains_probe_asset") or str(payload.get("git_head_short") or "").lower() == PROBE_ASSET_INTRO_SHA
    ):
        return CLOUD_FS_PROBE_CHECKOUT_AND_STATIC_CONFIG_PRESENT, "checkout_asset_and_static_config_present", evidence
    if not payload.get("repo_static_probe_exists") or not payload.get("git_head_contains_probe_asset"):
        return CLOUD_FS_PROBE_CHECKOUT_STALE_OR_ASSET_MISSING, "checkout_stale_or_repo_static_probe_missing", evidence
    if payload.get("effective_enable_static_serving") is not True:
        return CLOUD_FS_PROBE_STATIC_CONFIG_NOT_EFFECTIVE, "enable_static_serving_not_effective", evidence
    return CLOUD_FS_PROBE_UNAVAILABLE, "fs_probe_classification_inconclusive", evidence
