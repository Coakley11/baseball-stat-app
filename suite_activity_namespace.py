"""
Activity namespace + app-key normalization shared by Baseball and Command Center.

Ensures writes and reads use the same Supabase ``app`` / ``user_id`` / workspace keys.
"""

from __future__ import annotations

from typing import Any

# Logical app keys Command Center understands.
ACTIVITY_APP_ALIASES: dict[str, str] = {
    "math": "applied_intelligence",
    "applied_intelligence": "applied_intelligence",
    "baseball-stat-app": "baseball",
    "baseball_stat_app": "baseball",
    "Baseball Analytics": "baseball",
    "baseball analytics": "baseball",
    "baseball analytics app": "baseball",
}

DRAFT_ACTIVITY_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "live_draft_created",
        "live_draft_pick",
        "completed_live_draft",
        "draft_analysis_created",
        "draft_analysis_attempted",
    }
)

_TABLE_EVENTS = "suite_activity_events"
_TABLE_RESUME = "suite_resume_items"
_TABLE_STATE = "suite_app_state"


def normalize_activity_app_key(raw: str) -> str:
    """Map storage / display names to canonical suite app ids."""
    key = str(raw or "").strip()
    if not key:
        return ""
    if key in ACTIVITY_APP_ALIASES:
        return ACTIVITY_APP_ALIASES[key]
    try:
        from suite_workspace import logical_storage_app_key

        logical = logical_storage_app_key(key)
        return ACTIVITY_APP_ALIASES.get(logical, logical)
    except ImportError:
        if "__" in key:
            return key.split("__", 1)[0]
        return key


def stamp_activity_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
    """Tag writes with workspace + external owner for cross-app reads."""
    out = dict(metrics or {})
    try:
        from suite_user import get_external_user_id

        out.setdefault("suite_external_id", get_external_user_id())
    except ImportError:
        pass
    try:
        from suite_workspace import get_active_workspace_id

        out.setdefault("workspace_id", get_active_workspace_id())
    except ImportError:
        pass
    return out


def activity_namespace_diagnostics(*, st: Any | None = None) -> dict[str, Any]:
    """Read/write namespace fields for developer panels."""
    out: dict[str, Any] = {
        "suite_external_id": "",
        "account_user_id": "",
        "cloud_user_id": "",
        "account_mode": "",
        "active_workspace_id": "",
        "cloud_app_key_baseball": "",
        "workspace_storage_app_keys": [],
        "events_table": _TABLE_EVENTS,
        "resume_table": _TABLE_RESUME,
        "state_table": _TABLE_STATE,
    }
    try:
        from suite_user import account_mode, get_account_user_id, get_external_user_id

        out["suite_external_id"] = get_external_user_id()
        out["account_user_id"] = get_account_user_id()
        out["account_mode"] = account_mode()
    except ImportError:
        pass
    try:
        from suite_storage_supabase import _cloud_user_id

        out["cloud_user_id"] = _cloud_user_id() or ""
    except ImportError:
        pass
    try:
        from suite_workspace import get_active_workspace_id, scoped_cloud_app_id, workspace_storage_app_keys

        ws = get_active_workspace_id(st)
        out["active_workspace_id"] = ws
        out["cloud_app_key_baseball"] = scoped_cloud_app_id("baseball", ws)
        out["workspace_storage_app_keys"] = sorted(workspace_storage_app_keys(ws))
    except ImportError:
        pass
    try:
        from suite_storage_config import cloud_storage_enabled

        out["cloud_storage_enabled"] = cloud_storage_enabled()
    except ImportError:
        out["cloud_storage_enabled"] = False
    return out


def build_activity_write_diagnostics(
    *,
    event_type: str = "",
    resume_title: str = "",
    resume_key: str = "",
    page: str = "",
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge last write trace + namespace + draft payload for Baseball dev panel."""
    row: dict[str, Any] = dict(activity_namespace_diagnostics())
    m = dict(metrics or {})
    row.update(
        {
            "event_type": event_type,
            "event_title": resume_title,
            "resume_key": resume_key,
            "page": page,
            "team_matchup": str(m.get("team_matchup") or ""),
            "teams": m.get("teams") if isinstance(m.get("teams"), list) else [],
            "draft_room_id": str(m.get("draft_room_id") or ""),
            "room_code": str(m.get("room_code") or ""),
            "activity_type": str(m.get("activity_type") or event_type),
        }
    )
    try:
        from suite_activity_client import last_record_trace

        trace = last_record_trace()
        if trace:
            row.update(
                {
                    "write_success": bool(trace.get("recorded")),
                    "supabase_write_ok": bool(trace.get("supabase_write_ok")),
                    "write_path": str(trace.get("write_path") or ""),
                    "write_error": str(trace.get("error") or ""),
                    "written_timestamp": str(trace.get("timestamp") or ""),
                    "written_event_id": str(trace.get("event_id") or ""),
                }
            )
    except ImportError:
        pass
    try:
        from baseball_activity import last_activity_trace

        local = last_activity_trace()
        if local:
            row.setdefault("event_type", str(local.get("event_type") or ""))
            row.setdefault("written_timestamp", str(local.get("timestamp") or ""))
    except ImportError:
        pass
    return row
