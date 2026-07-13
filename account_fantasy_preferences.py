"""Account-scoped fantasy preferences — lightweight cross-device sync."""

from __future__ import annotations

import copy
import time
from datetime import datetime, timezone
from typing import Any

from fantasy_context_source import (
    USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY,
    USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
)
from fantasy_context_ui import FANTASY_RESEARCH_SYNC_KEY
from fantasy_position_sync import SYNC_POSITION_NEEDS_KEY

SCHEMA_VERSION = 1
PREFS_DOC_KEY = "fantasy_account_prefs"

SESSION_APPLIED_REV_KEY = "_account_fantasy_prefs_applied_revision"
SESSION_LOCAL_REV_KEY = "_account_fantasy_prefs_local_revision"
LAST_POLL_TS_KEY = "_account_fantasy_prefs_last_poll_ts"
LAST_SYNC_TRACE_KEY = "_account_fantasy_prefs_last_sync_trace"

POLL_INTERVAL_SEC = 8.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _cloud_sync_available() -> bool:
    try:
        from suite_storage_config import cloud_storage_enabled

        return bool(cloud_storage_enabled())
    except ImportError:
        return False


def _signed_in(session: dict[str, Any]) -> bool:
    try:
        from suite_auth import is_auth_enabled

        if not is_auth_enabled():
            return False
    except ImportError:
        return False
    uid = str(session.get("_suite_auth_user_id") or session.get("_suite_account_user_id") or "").strip()
    return bool(uid)


def _workspace_id(session: dict[str, Any]) -> str:
    try:
        from suite_workspace import normalize_workspace_id

        return normalize_workspace_id(str(session.get("_suite_active_workspace_id") or ""))
    except ImportError:
        return str(session.get("_suite_active_workspace_id") or "daniel").strip() or "daniel"


def _prefs_settings_app(session: dict[str, Any]) -> str:
    try:
        from suite_workspace import scoped_cloud_app_id

        base = scoped_cloud_app_id("baseball", _workspace_id(session))
    except ImportError:
        base = "baseball"
    return f"{base}_account_prefs"


def _device_id(session: dict[str, Any]) -> str:
    try:
        from baseball_persistent_state import _get_device_id  # noqa: SLF001

        import streamlit as st

        return str(_get_device_id(st) or "")
    except Exception:
        return str(session.get("_suite_device_id") or "unknown")


def _read_session_prefs_fields(session: dict[str, Any]) -> dict[str, Any]:
    from draft_archive_state import get_active_draft_archive
    from fantasy_league_context import ensure_fantasy_league_context_state

    store = ensure_fantasy_league_context_state(session)
    active_archive = get_active_draft_archive(session) or {}
    active_ctx_id = str(store.get("active_league_context_id") or "").strip()
    canonical_league_id = ""
    if active_ctx_id:
        try:
            from fantasy_league_context import get_league_context
            from fantasy_league_identity import resolve_canonical_league_id

            ctx = get_league_context(session, active_ctx_id)
            if isinstance(ctx, dict):
                canonical_league_id = str(resolve_canonical_league_id(ctx) or "").strip()
        except ImportError:
            pass

    live_override = bool(session.get(USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY))
    sim_override = bool(session.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))
    override_kind = "none"
    override_id = ""
    if live_override:
        override_kind = "live_draft_room"
        override_id = str(session.get("active_shared_draft_room_code") or "").strip()
    elif sim_override:
        override_kind = "simulator_board"
        override_id = "simulator"

    return {
        "schema_version": SCHEMA_VERSION,
        "user_id": str(session.get("_suite_auth_user_id") or session.get("_suite_account_user_id") or "").strip(),
        "workspace_id": _workspace_id(session),
        "active_draft_id": str(active_archive.get("draft_id") or session.get("active_draft_archive_id") or "").strip(),
        "active_league_context_id": active_ctx_id,
        "active_canonical_league_id": canonical_league_id,
        "fantasy_source_override_kind": override_kind,
        "fantasy_source_override_id": override_id,
        "research_mode_enabled": bool(session.get(FANTASY_RESEARCH_SYNC_KEY)),
        "use_draft_assistant_position_needs": bool(session.get(SYNC_POSITION_NEEDS_KEY)),
    }


def build_preference_document(
    session: dict[str, Any],
    *,
    revision: int,
    updated_by_device_id: str = "",
) -> dict[str, Any]:
    fields = _read_session_prefs_fields(session)
    fields["revision"] = int(revision)
    fields["updated_at"] = _utc_now_iso()
    fields["updated_by_device_id"] = str(updated_by_device_id or _device_id(session))
    return fields


def _load_cloud_prefs(session: dict[str, Any]) -> dict[str, Any]:
    if not _cloud_sync_available() or not _signed_in(session):
        return {}
    try:
        from suite_account import load_settings

        blob = load_settings(_prefs_settings_app(session))
        doc = blob.get(PREFS_DOC_KEY) if isinstance(blob, dict) else None
        return copy.deepcopy(doc) if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _save_cloud_prefs(session: dict[str, Any], doc: dict[str, Any]) -> bool:
    if not _cloud_sync_available() or not _signed_in(session):
        return False
    try:
        from suite_account import load_settings, save_settings

        app = _prefs_settings_app(session)
        envelope = load_settings(app)
        if not isinstance(envelope, dict):
            envelope = {}
        envelope[PREFS_DOC_KEY] = copy.deepcopy(doc)
        save_settings(app, envelope)
        return True
    except Exception:
        return False


def invalidate_preference_dependent_caches(session: dict[str, Any]) -> None:
    for key in (
        "_library_selection_fp",
        "_library_selection_cached",
        "_workflow_descriptor_fp",
        "_workflow_descriptor_cached",
        "_da_board_cache_fp",
        "_da_board_cache",
        "_lineup_page_context_cache",
        "_lineup_board_payload_cache",
        "_waiver_page_context_cache",
        "_standings_page_context_cache",
    ):
        session.pop(key, None)
    try:
        from fantasy_context_source import invalidate_fantasy_workflow_descriptor_cache

        invalidate_fantasy_workflow_descriptor_cache(session)
    except ImportError:
        session.pop("_fantasy_workflow_descriptor_cache", None)
        session.pop("_fantasy_workflow_descriptor_fp", None)
    try:
        from fantasy_lineup_perf import invalidate_lineup_page_caches

        invalidate_lineup_page_caches(session)
    except ImportError:
        pass
    try:
        from live_draft_ui_cache import invalidate_live_draft_ui_caches

        invalidate_live_draft_ui_caches(session)
    except ImportError:
        pass
    try:
        from draft_assistant_board import invalidate_draft_assistant_board_cache

        invalidate_draft_assistant_board_cache(session)
    except ImportError:
        pass


def _apply_prefs_to_session(session: dict[str, Any], doc: dict[str, Any], *, source: str) -> dict[str, Any]:
    trace: dict[str, Any] = {
        "source": source,
        "applied_revision": int(doc.get("revision") or 0),
        "changed": False,
        "active_draft_changed": False,
        "toggles_changed": False,
    }
    if not isinstance(doc, dict) or not doc:
        return trace

    applied = int(session.get(SESSION_APPLIED_REV_KEY) or 0)
    incoming = int(doc.get("revision") or 0)
    if incoming <= applied and source != "local_write":
        trace["skipped"] = "revision_not_newer"
        return trace

    prev_draft = str(session.get("active_draft_archive_id") or "").strip()
    prev_ctx = ""
    try:
        from fantasy_league_context import ensure_fantasy_league_context_state

        prev_ctx = str(ensure_fantasy_league_context_state(session).get("active_league_context_id") or "").strip()
    except ImportError:
        pass

    session[FANTASY_RESEARCH_SYNC_KEY] = bool(doc.get("research_mode_enabled"))
    session[SYNC_POSITION_NEEDS_KEY] = bool(doc.get("use_draft_assistant_position_needs"))

    override_kind = str(doc.get("fantasy_source_override_kind") or "none").strip().lower()
    session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = override_kind == "live_draft_room"
    session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = override_kind == "simulator_board"

    target_draft = str(doc.get("active_draft_id") or "").strip()
    target_ctx = str(doc.get("active_league_context_id") or "").strip()
    if target_draft and (target_draft != prev_draft or target_ctx != prev_ctx):
        try:
            from fantasy_league_context import activate_archive_league_context

            activate_archive_league_context(session, target_draft, defer_activation=False)
            trace["active_draft_changed"] = True
        except ImportError:
            session["active_draft_archive_id"] = target_draft
            if target_ctx:
                try:
                    from fantasy_league_context import activate_league_context

                    activate_league_context(session, target_ctx)
                except ImportError:
                    pass

    session[SESSION_APPLIED_REV_KEY] = incoming
    session[SESSION_LOCAL_REV_KEY] = incoming
    trace["changed"] = True
    trace["toggles_changed"] = True
    invalidate_preference_dependent_caches(session)
    return trace


def write_account_fantasy_preferences(
    session: dict[str, Any],
    *,
    reason: str = "",
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Persist current session prefs to cloud with revision increment."""
    trace: dict[str, Any] = {"reason": reason, "written": False, "cloud_saved": False}
    if not _signed_in(session):
        trace["skipped"] = "unsigned"
        return trace

    cloud = _load_cloud_prefs(session)
    cloud_rev = int(cloud.get("revision") or 0)
    local_rev = int(session.get(SESSION_LOCAL_REV_KEY) or session.get(SESSION_APPLIED_REV_KEY) or 0)
    base_rev = max(cloud_rev, local_rev)
    if expected_revision is not None and int(expected_revision) < cloud_rev:
        trace["conflict"] = "cloud_newer"
        trace["cloud_revision"] = cloud_rev
        _apply_prefs_to_session(session, cloud, source="conflict_resolve")
        return trace

    new_rev = base_rev + 1
    doc = build_preference_document(session, revision=new_rev)
    trace["revision"] = new_rev
    trace["cloud_saved"] = _save_cloud_prefs(session, doc)
    session[SESSION_APPLIED_REV_KEY] = new_rev
    session[SESSION_LOCAL_REV_KEY] = new_rev
    trace["written"] = True
    session[LAST_SYNC_TRACE_KEY] = trace
    return trace


def sync_account_fantasy_preferences(
    session: dict[str, Any],
    *,
    force: bool = False,
    poll: bool = False,
) -> dict[str, Any]:
    """Fetch cloud prefs; apply when remote revision is newer."""
    trace: dict[str, Any] = {"poll": poll, "applied": False}
    if not _signed_in(session):
        trace["skipped"] = "unsigned"
        return trace
    if not _cloud_sync_available():
        trace["skipped"] = "cloud_disabled"
        return trace

    now = time.monotonic()
    last = float(session.get(LAST_POLL_TS_KEY) or 0.0)
    if poll and not force and (now - last) < POLL_INTERVAL_SEC:
        trace["skipped"] = "poll_throttled"
        return trace
    session[LAST_POLL_TS_KEY] = now

    cloud = _load_cloud_prefs(session)
    if not cloud:
        trace["skipped"] = "empty_cloud"
        return trace
    trace["cloud_revision"] = int(cloud.get("revision") or 0)
    applied = _apply_prefs_to_session(session, cloud, source="cloud_sync")
    trace.update(applied)
    trace["applied"] = bool(applied.get("changed"))
    session[LAST_SYNC_TRACE_KEY] = trace
    return trace


def preference_revision_fingerprint(session: dict[str, Any]) -> str:
    rev = int(session.get(SESSION_APPLIED_REV_KEY) or session.get(SESSION_LOCAL_REV_KEY) or 0)
    return str(rev)
