"""Account-scoped fantasy preferences — lightweight cross-device sync."""

from __future__ import annotations

import copy
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Callable

from fantasy_context_source import (
    USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY,
    USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY,
)
from fantasy_context_ui import FANTASY_RESEARCH_SYNC_KEY
from fantasy_position_sync import SYNC_POSITION_NEEDS_KEY

SCHEMA_VERSION = 1
PREFS_DOC_KEY = "fantasy_account_prefs"
PREFS_REVISION_DOC_KEY = "fantasy_account_prefs_revision"

SESSION_APPLIED_REV_KEY = "_account_fantasy_prefs_applied_revision"
SESSION_LOCAL_REV_KEY = "_account_fantasy_prefs_local_revision"
SESSION_APPLIED_FP_KEY = "_account_fantasy_prefs_applied_fingerprint"
LAST_POLL_TS_KEY = "_account_fantasy_prefs_last_poll_ts"
LAST_SYNC_TRACE_KEY = "_account_fantasy_prefs_last_sync_trace"
LAST_SYNC_ERROR_KEY = "_account_fantasy_prefs_last_error"
LAST_WRITE_TRACE_KEY = "_account_fantasy_prefs_last_write_trace"
SYNC_STATUS_FLASH_KEY = "_account_fantasy_prefs_sync_status_flash"
WRITE_FAIL_FLASH_KEY = "_account_fantasy_prefs_write_fail_flash"
REMOTE_APPLY_IN_PROGRESS_KEY = "_account_preferences_remote_apply_in_progress"
SYNC_FAIL_USER_MSG = (
    "Your selection changed on this device, but account sync did not complete. Try again."
)

POLL_INTERVAL_SEC = 8.0

# Owned exclusively by the account preference document — never restored from full_session.
ACCOUNT_OWNED_SESSION_KEYS: tuple[str, ...] = (
    "use_active_league_context_waiver_filter",
    "use_live_draft_as_fantasy_context",
    "use_simulator_board_as_fantasy_context",
    "sync_draft_assistant_position_needs",
    SESSION_APPLIED_REV_KEY,
    SESSION_LOCAL_REV_KEY,
    SESSION_APPLIED_FP_KEY,
)

_COMPARE_FIELDS: tuple[str, ...] = (
    "active_draft_id",
    "active_league_context_id",
    "active_canonical_league_id",
    "research_mode_enabled",
    "fantasy_source_override_kind",
    "fantasy_source_override_id",
    "use_draft_assistant_position_needs",
)

# Injected by tests: maps settings_app -> envelope dict.
_TEST_CLOUD_STORE: dict[str, dict[str, Any]] | None = None
_TEST_CLOUD_AVAILABLE: bool | None = None
_TEST_SIGNED_IN: bool | None = None


def install_test_cloud_store(store: dict[str, dict[str, Any]] | None) -> None:
    """Install or clear an in-memory cloud preference store for tests."""
    global _TEST_CLOUD_STORE, _TEST_CLOUD_AVAILABLE, _TEST_SIGNED_IN
    _TEST_CLOUD_STORE = store
    if store is None:
        _TEST_CLOUD_AVAILABLE = None
        _TEST_SIGNED_IN = None
    else:
        _TEST_CLOUD_AVAILABLE = True
        _TEST_SIGNED_IN = True


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _record_error(session: dict[str, Any], *, where: str, exc: BaseException) -> None:
    session[LAST_SYNC_ERROR_KEY] = {
        "where": where,
        "error_type": type(exc).__name__,
        "error_summary": str(exc)[:240],
        "at": _utc_now_iso(),
    }


def _cloud_sync_available() -> bool:
    if _TEST_CLOUD_AVAILABLE is not None:
        return bool(_TEST_CLOUD_AVAILABLE)
    try:
        from suite_storage_config import cloud_storage_enabled

        return bool(cloud_storage_enabled())
    except ImportError:
        return False


def _signed_in(session: dict[str, Any]) -> bool:
    if _TEST_SIGNED_IN is not None:
        return bool(_TEST_SIGNED_IN)
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


def _scoped_baseball_base(session: dict[str, Any]) -> str:
    try:
        from suite_workspace import scoped_cloud_app_id

        return scoped_cloud_app_id("baseball", _workspace_id(session))
    except ImportError:
        return "baseball"


def prefs_settings_app(session: dict[str, Any]) -> str:
    """Public: settings app key used for the preference document."""
    return f"{_scoped_baseball_base(session)}_account_prefs"


def prefs_revision_settings_app(session: dict[str, Any]) -> str:
    """Compact revision-header document (fetched by the 8s fragment)."""
    return f"{_scoped_baseball_base(session)}_account_prefs_rev"


def _prefs_settings_app(session: dict[str, Any]) -> str:
    return prefs_settings_app(session)


def preference_document_fingerprint(doc: dict[str, Any] | None) -> str:
    if not isinstance(doc, dict):
        return ""
    parts = [str(int(doc.get("revision") or 0))]
    for key in _COMPARE_FIELDS:
        val = doc.get(key)
        if isinstance(val, bool):
            parts.append("1" if val else "0")
        else:
            parts.append(str(val or "").strip())
    return "|".join(parts)


def account_preference_fields_match_session(
    session: dict[str, Any],
    cloud_doc: dict[str, Any] | None,
) -> tuple[bool, list[str]]:
    """Return (match, mismatched_field_names) for account-owned preference fields."""
    if not isinstance(cloud_doc, dict) or not cloud_doc:
        return True, []
    local = _read_session_prefs_fields(session)
    mismatched: list[str] = []
    for key in _COMPARE_FIELDS:
        local_val = local.get(key)
        cloud_val = cloud_doc.get(key)
        if key in ("research_mode_enabled", "use_draft_assistant_position_needs"):
            if bool(local_val) != bool(cloud_val):
                mismatched.append(key)
            continue
        if str(local_val or "").strip() != str(cloud_val or "").strip():
            mismatched.append(key)
    return (not mismatched), mismatched


def _device_id(session: dict[str, Any]) -> str:
    try:
        from baseball_persistent_state import _get_device_id  # noqa: SLF001

        import streamlit as st

        return str(_get_device_id(st) or "")
    except Exception:
        return str(session.get("_suite_device_id") or "unknown")


def _clear_pending_activation_keys(session: dict[str, Any]) -> None:
    try:
        from fantasy_league_context import (
            PENDING_ARCHIVE_ACTIVATION_KEY,
            PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY,
        )

        session.pop(PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY, None)
        session.pop(PENDING_ARCHIVE_ACTIVATION_KEY, None)
    except ImportError:
        session.pop("_pending_active_league_context_id", None)
        session.pop("_pending_active_archive_id", None)


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
    field_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields = _read_session_prefs_fields(session)
    if field_overrides:
        fields.update({k: v for k, v in field_overrides.items() if v is not None})
    fields["revision"] = int(revision)
    fields["updated_at"] = _utc_now_iso()
    fields["updated_by_device_id"] = str(updated_by_device_id or _device_id(session))
    return fields


def _load_cloud_envelope(session: dict[str, Any]) -> dict[str, Any]:
    app = _prefs_settings_app(session)
    if _TEST_CLOUD_STORE is not None:
        return copy.deepcopy(_TEST_CLOUD_STORE.get(app) or {})
    try:
        from suite_account import load_settings

        blob = load_settings(app)
        return copy.deepcopy(blob) if isinstance(blob, dict) else {}
    except Exception as exc:
        _record_error(session, where="load_settings", exc=exc)
        raise


def _load_cloud_prefs(session: dict[str, Any]) -> dict[str, Any]:
    if not _cloud_sync_available() or not _signed_in(session):
        return {}
    try:
        envelope = _load_cloud_envelope(session)
        doc = envelope.get(PREFS_DOC_KEY) if isinstance(envelope, dict) else None
        return copy.deepcopy(doc) if isinstance(doc, dict) else {}
    except Exception as exc:
        _record_error(session, where="load_cloud_prefs", exc=exc)
        return {}


def _revision_header_from_doc(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "revision": int(doc.get("revision") or 0),
        "preference_fingerprint": preference_document_fingerprint(doc),
        "updated_at": str(doc.get("updated_at") or ""),
        "updated_by_device_id": str(doc.get("updated_by_device_id") or ""),
    }


def load_preference_revision_meta(session: dict[str, Any]) -> dict[str, Any]:
    """Compact revision-header fetch — does not load the full preference document."""
    empty = {
        "revision": 0,
        "preference_fingerprint": "",
        "updated_at": "",
        "updated_by_device_id": "",
    }
    if not _cloud_sync_available() or not _signed_in(session):
        return empty
    rev_app = prefs_revision_settings_app(session)
    try:
        if _TEST_CLOUD_STORE is not None:
            envelope = _TEST_CLOUD_STORE.get(rev_app) or {}
            header = envelope.get(PREFS_REVISION_DOC_KEY)
            if isinstance(header, dict) and header:
                return {
                    "revision": int(header.get("revision") or 0),
                    "preference_fingerprint": str(header.get("preference_fingerprint") or ""),
                    "updated_at": str(header.get("updated_at") or ""),
                    "updated_by_device_id": str(header.get("updated_by_device_id") or ""),
                    "settings_app": rev_app,
                    "source": "revision_header",
                }
            # Fallback for older writes that only stored the full prefs doc.
            doc = _load_cloud_prefs(session)
            if not doc:
                return empty
            header = _revision_header_from_doc(doc)
            return {**header, "settings_app": rev_app, "source": "prefs_fallback"}

        from suite_account import load_settings

        envelope = load_settings(rev_app)
        header = envelope.get(PREFS_REVISION_DOC_KEY) if isinstance(envelope, dict) else None
        if isinstance(header, dict) and header:
            return {
                "revision": int(header.get("revision") or 0),
                "preference_fingerprint": str(header.get("preference_fingerprint") or ""),
                "updated_at": str(header.get("updated_at") or ""),
                "updated_by_device_id": str(header.get("updated_by_device_id") or ""),
                "settings_app": rev_app,
                "source": "revision_header",
            }
        doc = _load_cloud_prefs(session)
        if not doc:
            return empty
        header = _revision_header_from_doc(doc)
        return {**header, "settings_app": rev_app, "source": "prefs_fallback"}
    except Exception as exc:
        _record_error(session, where="load_preference_revision_meta", exc=exc)
        return {**empty, "error": type(exc).__name__}


def _save_revision_header(session: dict[str, Any], doc: dict[str, Any]) -> bool:
    header = _revision_header_from_doc(doc)
    rev_app = prefs_revision_settings_app(session)
    try:
        if _TEST_CLOUD_STORE is not None:
            envelope = copy.deepcopy(_TEST_CLOUD_STORE.get(rev_app) or {})
            envelope[PREFS_REVISION_DOC_KEY] = copy.deepcopy(header)
            _TEST_CLOUD_STORE[rev_app] = envelope
            return True
        from suite_account import save_settings

        save_settings(rev_app, {PREFS_REVISION_DOC_KEY: header})
        return True
    except Exception as exc:
        _record_error(session, where="save_revision_header", exc=exc)
        return False


def _save_cloud_prefs(session: dict[str, Any], doc: dict[str, Any]) -> bool:
    if not _cloud_sync_available() or not _signed_in(session):
        return False
    app = _prefs_settings_app(session)
    try:
        if _TEST_CLOUD_STORE is not None:
            envelope = copy.deepcopy(_TEST_CLOUD_STORE.get(app) or {})
            envelope[PREFS_DOC_KEY] = copy.deepcopy(doc)
            _TEST_CLOUD_STORE[app] = envelope
            _save_revision_header(session, doc)
            return True
        from suite_account import load_settings, save_settings

        envelope = load_settings(app)
        if not isinstance(envelope, dict):
            envelope = {}
        envelope[PREFS_DOC_KEY] = copy.deepcopy(doc)
        save_settings(app, envelope)
        _save_revision_header(session, doc)
        return True
    except Exception as exc:
        _record_error(session, where="save_cloud_prefs", exc=exc)
        return False


def _docs_match_for_verification(expected: dict[str, Any], actual: dict[str, Any]) -> tuple[bool, str]:
    checks = (
        ("revision", int(expected.get("revision") or 0), int(actual.get("revision") or 0)),
        (
            "active_draft_id",
            str(expected.get("active_draft_id") or "").strip(),
            str(actual.get("active_draft_id") or "").strip(),
        ),
        (
            "active_league_context_id",
            str(expected.get("active_league_context_id") or "").strip(),
            str(actual.get("active_league_context_id") or "").strip(),
        ),
        (
            "research_mode_enabled",
            bool(expected.get("research_mode_enabled")),
            bool(actual.get("research_mode_enabled")),
        ),
        (
            "fantasy_source_override_kind",
            str(expected.get("fantasy_source_override_kind") or "none"),
            str(actual.get("fantasy_source_override_kind") or "none"),
        ),
    )
    for name, want, got in checks:
        if want != got:
            return False, f"{name}_mismatch want={want!r} got={got!r}"
    return True, ""


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
        from fantasy_context_ui import reseed_fantasy_context_toggle_widgets

        reseed_fantasy_context_toggle_widgets(session)
    except ImportError:
        try:
            from fantasy_context_ui import clear_fantasy_context_toggle_widgets

            clear_fantasy_context_toggle_widgets(session)
        except ImportError:
            pass
    try:
        from fantasy_context_source import invalidate_fantasy_workflow_descriptor_cache

        invalidate_fantasy_workflow_descriptor_cache(session)
    except ImportError:
        session.pop("_workflow_descriptor_cache", None)
        session.pop("_workflow_descriptor_fp", None)
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
        "widgets_reseeded": False,
    }
    if not isinstance(doc, dict) or not doc:
        return trace

    applied = int(session.get(SESSION_APPLIED_REV_KEY) or 0)
    incoming = int(doc.get("revision") or 0)
    fields_match, mismatched = account_preference_fields_match_session(session, doc)
    if incoming < applied and source not in ("local_write", "atomic_activate", "conflict_resolve"):
        trace["skipped"] = "remote_revision_lower"
        return trace
    if (
        incoming == applied
        and fields_match
        and source not in ("local_write", "atomic_activate", "post_hydration_reassert")
    ):
        trace["skipped"] = "revision_equal_fields_match"
        return trace
    if incoming == applied and not fields_match and source.startswith("cloud"):
        source = "cloud_reassert_same_revision"
        trace["source"] = source
        trace["mismatched_fields"] = mismatched
    elif incoming < applied:
        # Still allow explicit reassert paths after stale hydration when forced via post_hydration.
        if source != "post_hydration_reassert":
            trace["skipped"] = "remote_revision_lower"
            return trace

    session[REMOTE_APPLY_IN_PROGRESS_KEY] = True
    try:
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
                _clear_pending_activation_keys(session)
                trace["active_draft_changed"] = True
            except ImportError:
                session["active_draft_archive_id"] = target_draft
                if target_ctx:
                    try:
                        from fantasy_league_context import activate_league_context, ensure_fantasy_league_context_state

                        activate_league_context(session, target_ctx)
                        ensure_fantasy_league_context_state(session)["active_league_context_id"] = target_ctx
                    except ImportError:
                        pass

        session[SESSION_APPLIED_REV_KEY] = incoming
        session[SESSION_LOCAL_REV_KEY] = incoming
        session[SESSION_APPLIED_FP_KEY] = preference_document_fingerprint(doc)
        trace["changed"] = True
        trace["toggles_changed"] = True
        invalidate_preference_dependent_caches(session)
        trace["widgets_reseeded"] = True
        return trace
    finally:
        session.pop(REMOTE_APPLY_IN_PROGRESS_KEY, None)


def reassert_account_preferences_after_hydration(session: dict[str, Any]) -> dict[str, Any]:
    """Final authority: reapply cloud preference fields after legacy full-session restore."""
    trace: dict[str, Any] = {"applied": False, "source": "post_hydration_reassert"}
    if not _signed_in(session) or not _cloud_sync_available():
        trace["skipped"] = "unavailable"
        return trace
    cloud = _load_cloud_prefs(session)
    if not cloud:
        trace["skipped"] = "empty_cloud"
        return trace
    match, mismatched = account_preference_fields_match_session(session, cloud)
    remote_rev = int(cloud.get("revision") or 0)
    if match:
        session[SESSION_APPLIED_REV_KEY] = max(int(session.get(SESSION_APPLIED_REV_KEY) or 0), remote_rev)
        session[SESSION_LOCAL_REV_KEY] = session[SESSION_APPLIED_REV_KEY]
        session[SESSION_APPLIED_FP_KEY] = preference_document_fingerprint(cloud)
        trace["skipped"] = "already_aligned"
        return trace

    # Same-revision (or any cloud doc) with local drift: reassert without bumping revision.
    session[REMOTE_APPLY_IN_PROGRESS_KEY] = True
    try:
        session[FANTASY_RESEARCH_SYNC_KEY] = bool(cloud.get("research_mode_enabled"))
        session[SYNC_POSITION_NEEDS_KEY] = bool(cloud.get("use_draft_assistant_position_needs"))
        override_kind = str(cloud.get("fantasy_source_override_kind") or "none").strip().lower()
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = override_kind == "live_draft_room"
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = override_kind == "simulator_board"
        target_draft = str(cloud.get("active_draft_id") or "").strip()
        if target_draft and str(session.get("active_draft_archive_id") or "").strip() != target_draft:
            try:
                from fantasy_league_context import activate_archive_league_context

                activate_archive_league_context(session, target_draft, defer_activation=False)
                _clear_pending_activation_keys(session)
            except ImportError:
                session["active_draft_archive_id"] = target_draft
        session[SESSION_APPLIED_REV_KEY] = remote_rev
        session[SESSION_LOCAL_REV_KEY] = remote_rev
        session[SESSION_APPLIED_FP_KEY] = preference_document_fingerprint(cloud)
        invalidate_preference_dependent_caches(session)
        trace.update(
            {
                "source": "cloud_reassert_same_revision",
                "changed": True,
                "toggles_changed": True,
                "widgets_reseeded": True,
                "mismatched_fields": mismatched,
                "applied_revision": remote_rev,
                "applied": True,
            }
        )
        session[LAST_SYNC_TRACE_KEY] = dict(trace)
        return trace
    finally:
        session.pop(REMOTE_APPLY_IN_PROGRESS_KEY, None)


def sync_account_fantasy_preferences(
    session: dict[str, Any],
    *,
    force: bool = False,
    poll: bool = False,
) -> dict[str, Any]:
    """Fetch cloud prefs; apply when remote revision is newer or same-rev fields drifted."""
    trace: dict[str, Any] = {"poll": poll, "applied": False, "needs_rerun": False}
    if not _signed_in(session):
        trace["skipped"] = "unsigned"
        return trace
    if not _cloud_sync_available():
        trace["skipped"] = "cloud_disabled"
        return trace

    now = time.monotonic()
    last = float(session.get(LAST_POLL_TS_KEY) or 0.0)
    if poll and not force and (now - last) < POLL_INTERVAL_SEC:
        # Still allow same-revision drift checks against local fingerprint without
        # a full throttle skip when force is False — use header only when warm.
        pass
    if poll and not force and (now - last) < POLL_INTERVAL_SEC:
        # Cheap local drift check without network when recently polled.
        cloud_fp = str(session.get(SESSION_APPLIED_FP_KEY) or "")
        if cloud_fp:
            local_fields = _read_session_prefs_fields(session)
            synth = {**local_fields, "revision": int(session.get(SESSION_APPLIED_REV_KEY) or 0)}
            if preference_document_fingerprint(synth) == cloud_fp:
                trace["skipped"] = "poll_throttled"
                return trace
        # Fall through to reassert when local fingerprint drifted mid-session.
        force = True
        trace["force_due_to_local_drift"] = True
    session[LAST_POLL_TS_KEY] = now

    try:
        meta = load_preference_revision_meta(session)
        remote_rev = int(meta.get("revision") or 0)
        remote_fp = str(meta.get("preference_fingerprint") or "")
        local_rev = int(session.get(SESSION_APPLIED_REV_KEY) or 0)
        local_fp = str(session.get(SESSION_APPLIED_FP_KEY) or "")
        trace["remote_revision"] = remote_rev
        trace["local_revision"] = local_rev
        need_full = bool(force) or remote_rev > local_rev or (remote_fp and remote_fp != local_fp)
        if not need_full and remote_rev == local_rev:
            # Check local field drift against applied fingerprint without fetching full doc
            # when header matches; still reassert if local fingerprint differs from fields.
            local_fields = _read_session_prefs_fields(session)
            synth = {**local_fields, "revision": local_rev}
            if preference_document_fingerprint(synth) == local_fp and local_fp:
                trace["skipped"] = "revision_equal_fields_match"
                session[LAST_SYNC_TRACE_KEY] = trace
                return trace
            need_full = True

        if not need_full:
            trace["skipped"] = "revision_not_newer"
            session[LAST_SYNC_TRACE_KEY] = trace
            return trace

        cloud = _load_cloud_prefs(session)
        if not cloud:
            trace["skipped"] = "empty_cloud"
            session[LAST_SYNC_TRACE_KEY] = trace
            return trace
        match, mismatched = account_preference_fields_match_session(session, cloud)
        cloud_rev = int(cloud.get("revision") or 0)
        if cloud_rev > local_rev:
            applied = _apply_prefs_to_session(session, cloud, source="cloud_sync")
        elif cloud_rev == local_rev and not match:
            applied = _apply_prefs_to_session(session, cloud, source="cloud_reassert_same_revision")
            if applied.get("skipped"):
                applied = reassert_account_preferences_after_hydration(session)
        elif force and not match:
            applied = reassert_account_preferences_after_hydration(session)
        else:
            applied = _apply_prefs_to_session(session, cloud, source="cloud_sync")
        trace.update(applied)
        trace["applied"] = bool(applied.get("changed"))
        trace["needs_rerun"] = bool(applied.get("changed"))
        trace["mismatched_fields"] = mismatched
        session.pop(LAST_SYNC_ERROR_KEY, None)
        session[LAST_SYNC_TRACE_KEY] = trace
        return trace
    except Exception as exc:
        _record_error(session, where="sync_account_fantasy_preferences", exc=exc)
        trace["error"] = type(exc).__name__
        session[LAST_SYNC_TRACE_KEY] = trace
        return trace


def update_account_fantasy_preference_fields(
    session: dict[str, Any],
    *,
    changed_fields: dict[str, Any],
    reason: str = "",
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Atomically patch preference fields without rebuilding from ambient session state."""
    trace: dict[str, Any] = {
        "reason": reason,
        "written": False,
        "cloud_saved": False,
        "write_verified": False,
        "changed_fields": dict(changed_fields or {}),
    }
    session[LAST_WRITE_TRACE_KEY] = trace
    if not changed_fields:
        trace["skipped"] = "empty_changed_fields"
        return trace
    if not _signed_in(session):
        # Still update local persisted keys for unsigned sessions.
        _apply_changed_fields_locally(session, changed_fields)
        trace["skipped"] = "unsigned"
        return trace
    if not _cloud_sync_available():
        _apply_changed_fields_locally(session, changed_fields)
        trace["skipped"] = "cloud_disabled"
        return trace

    try:
        cloud = _load_cloud_prefs(session)
    except Exception as exc:
        _record_error(session, where="update_fields_load", exc=exc)
        trace["error"] = type(exc).__name__
        session[WRITE_FAIL_FLASH_KEY] = SYNC_FAIL_USER_MSG
        session[SYNC_STATUS_FLASH_KEY] = "Changed on this device, but account sync failed"
        return trace

    cloud_rev = int(cloud.get("revision") or 0)
    local_rev = int(session.get(SESSION_LOCAL_REV_KEY) or session.get(SESSION_APPLIED_REV_KEY) or 0)
    base_rev = max(cloud_rev, local_rev)
    if expected_revision is not None and int(expected_revision) < cloud_rev:
        trace["conflict"] = "cloud_newer"
        _apply_prefs_to_session(session, cloud, source="conflict_resolve")
        session[LAST_WRITE_TRACE_KEY] = trace
        return trace

    new_rev = base_rev + 1
    # Start from cloud doc (authoritative), fall back to session build when empty.
    if cloud:
        doc = copy.deepcopy(cloud)
    else:
        doc = build_preference_document(session, revision=new_rev)
    for key, value in changed_fields.items():
        doc[key] = value
    doc["revision"] = new_rev
    doc["updated_at"] = _utc_now_iso()
    doc["updated_by_device_id"] = _device_id(session)
    doc["schema_version"] = SCHEMA_VERSION
    # Keep user/workspace metadata aligned
    fields = _read_session_prefs_fields(session)
    doc["user_id"] = fields.get("user_id") or doc.get("user_id") or ""
    doc["workspace_id"] = fields.get("workspace_id") or doc.get("workspace_id") or ""
    # Preserve active league from existing doc unless explicitly changed
    if "active_draft_id" not in changed_fields and not doc.get("active_draft_id"):
        doc["active_draft_id"] = fields.get("active_draft_id") or ""
    if "active_league_context_id" not in changed_fields and not doc.get("active_league_context_id"):
        doc["active_league_context_id"] = fields.get("active_league_context_id") or ""

    trace["revision"] = new_rev
    trace["write_document"] = {
        k: doc.get(k)
        for k in (
            "revision",
            "active_draft_id",
            "active_league_context_id",
            "research_mode_enabled",
            "fantasy_source_override_kind",
            "fantasy_source_override_id",
        )
    }
    saved = _save_cloud_prefs(session, doc)
    trace["cloud_saved"] = saved
    if not saved:
        _apply_changed_fields_locally(session, changed_fields)
        session[WRITE_FAIL_FLASH_KEY] = SYNC_FAIL_USER_MSG
        session[SYNC_STATUS_FLASH_KEY] = "Changed on this device, but account sync failed"
        session[LAST_WRITE_TRACE_KEY] = trace
        return trace

    readback = _load_cloud_prefs(session)
    trace["readback_document"] = {
        k: readback.get(k)
        for k in (
            "revision",
            "active_draft_id",
            "active_league_context_id",
            "research_mode_enabled",
            "fantasy_source_override_kind",
            "fantasy_source_override_id",
        )
    }
    mismatches: list[str] = []
    for key, value in changed_fields.items():
        got = readback.get(key)
        if isinstance(value, bool):
            if bool(got) != bool(value):
                mismatches.append(key)
        elif str(got or "").strip() != str(value or "").strip():
            mismatches.append(key)
    if int(readback.get("revision") or 0) != new_rev:
        mismatches.append("revision")
    trace["write_verified"] = not mismatches
    if mismatches:
        trace["verification_error"] = f"changed_field_mismatch:{mismatches}"
        session[WRITE_FAIL_FLASH_KEY] = SYNC_FAIL_USER_MSG
        session[SYNC_STATUS_FLASH_KEY] = "Changed on this device, but account sync failed"
        session[LAST_WRITE_TRACE_KEY] = trace
        return trace

    # Local authoritative state from verified readback
    session[REMOTE_APPLY_IN_PROGRESS_KEY] = True
    try:
        _apply_changed_fields_locally(session, {k: readback.get(k) for k in changed_fields})
        # Also sync any remaining known preference fields from readback
        session[FANTASY_RESEARCH_SYNC_KEY] = bool(readback.get("research_mode_enabled"))
        session[SYNC_POSITION_NEEDS_KEY] = bool(readback.get("use_draft_assistant_position_needs"))
        override_kind = str(readback.get("fantasy_source_override_kind") or "none").strip().lower()
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = override_kind == "live_draft_room"
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = override_kind == "simulator_board"
        session[SESSION_APPLIED_REV_KEY] = new_rev
        session[SESSION_LOCAL_REV_KEY] = new_rev
        session[SESSION_APPLIED_FP_KEY] = preference_document_fingerprint(readback)
        reseed_ok = False
        try:
            from fantasy_context_ui import (
                _LIVE_CONTEXT_TOGGLE_WIDGET_KEY,
                _RESEARCH_SYNC_TOGGLE_WIDGET_KEY,
                _SIM_CONTEXT_TOGGLE_WIDGET_KEY,
            )

            # Only reseed keys touched by this write — avoid stomping concurrent toggle changes.
            if "research_mode_enabled" in changed_fields:
                session.pop(_RESEARCH_SYNC_TOGGLE_WIDGET_KEY, None)
                session[_RESEARCH_SYNC_TOGGLE_WIDGET_KEY] = bool(readback.get("research_mode_enabled"))
            if "fantasy_source_override_kind" in changed_fields:
                kind = str(readback.get("fantasy_source_override_kind") or "none").strip().lower()
                session.pop(_LIVE_CONTEXT_TOGGLE_WIDGET_KEY, None)
                session.pop(_SIM_CONTEXT_TOGGLE_WIDGET_KEY, None)
                session[_LIVE_CONTEXT_TOGGLE_WIDGET_KEY] = kind == "live_draft_room"
                session[_SIM_CONTEXT_TOGGLE_WIDGET_KEY] = kind == "simulator_board"
            reseed_ok = True
        except ImportError:
            pass
        trace["widget_reseed_result"] = reseed_ok
    finally:
        session.pop(REMOTE_APPLY_IN_PROGRESS_KEY, None)

    session.pop(LAST_SYNC_ERROR_KEY, None)
    session[SYNC_STATUS_FLASH_KEY] = "Synced to your account"
    trace["written"] = True
    session[LAST_WRITE_TRACE_KEY] = trace
    session[LAST_SYNC_TRACE_KEY] = {"source": "local_write", **trace}
    return trace


def _apply_changed_fields_locally(session: dict[str, Any], changed_fields: dict[str, Any]) -> None:
    if "research_mode_enabled" in changed_fields:
        session[FANTASY_RESEARCH_SYNC_KEY] = bool(changed_fields.get("research_mode_enabled"))
    if "use_draft_assistant_position_needs" in changed_fields:
        session[SYNC_POSITION_NEEDS_KEY] = bool(changed_fields.get("use_draft_assistant_position_needs"))
    if "fantasy_source_override_kind" in changed_fields:
        kind = str(changed_fields.get("fantasy_source_override_kind") or "none").strip().lower()
        session[USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY] = kind == "live_draft_room"
        session[USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY] = kind == "simulator_board"
    if "active_draft_id" in changed_fields:
        draft_id = str(changed_fields.get("active_draft_id") or "").strip()
        if draft_id:
            session["active_draft_archive_id"] = draft_id
    if "active_league_context_id" in changed_fields:
        ctx_id = str(changed_fields.get("active_league_context_id") or "").strip()
        if ctx_id:
            try:
                from fantasy_league_context import ensure_fantasy_league_context_state

                ensure_fantasy_league_context_state(session)["active_league_context_id"] = ctx_id
            except ImportError:
                pass


def ensure_account_preferences_applied_before_controls(session: dict[str, Any]) -> dict[str, Any]:
    """Authoritative prefs must win before Research/Live/Simulator checkboxes render."""
    trace: dict[str, Any] = {"applied": False, "source": "before_controls"}
    if not _signed_in(session) or not _cloud_sync_available():
        # Still reseed widgets from whatever persisted keys exist.
        try:
            from fantasy_context_ui import reseed_fantasy_context_toggle_widgets

            reseed_fantasy_context_toggle_widgets(session)
            trace["widget_reseed_result"] = True
        except ImportError:
            trace["widget_reseed_result"] = False
        return trace

    meta = load_preference_revision_meta(session)
    remote_rev = int(meta.get("revision") or 0)
    remote_fp = str(meta.get("preference_fingerprint") or "")
    local_rev = int(session.get(SESSION_APPLIED_REV_KEY) or 0)
    local_fp = str(session.get(SESSION_APPLIED_FP_KEY) or "")
    local_fields = _read_session_prefs_fields(session)
    synth = {**local_fields, "revision": local_rev}
    local_drift = bool(local_fp) and preference_document_fingerprint(synth) != local_fp
    need_full = remote_rev > local_rev or (remote_fp and remote_fp != local_fp) or local_drift or not local_fp
    if not need_full:
        try:
            from fantasy_context_ui import reseed_fantasy_context_toggle_widgets

            # Clear then reseed so widgets cannot retain stale values across hydration.
            reseed_fantasy_context_toggle_widgets(session)
            trace["widget_reseed_result"] = True
            trace["skipped"] = "header_unchanged"
        except ImportError:
            pass
        return trace

    cloud = _load_cloud_prefs(session)
    if not cloud:
        try:
            from fantasy_context_ui import reseed_fantasy_context_toggle_widgets

            reseed_fantasy_context_toggle_widgets(session)
        except ImportError:
            pass
        trace["skipped"] = "empty_cloud"
        return trace

    applied = reassert_account_preferences_after_hydration(session)
    # Force widget delete + reseed even if reassert thought values already matched.
    try:
        from fantasy_context_ui import clear_fantasy_context_toggle_widgets, reseed_fantasy_context_toggle_widgets

        clear_fantasy_context_toggle_widgets(session)
        reseed_fantasy_context_toggle_widgets(session)
        applied["widget_reseed_result"] = True
    except ImportError:
        applied["widget_reseed_result"] = False
    applied["source"] = applied.get("source") or "before_controls"
    session[LAST_SYNC_TRACE_KEY] = dict(applied)
    return applied


def pop_preference_sync_status(session: dict[str, Any]) -> str:
    return str(session.pop(SYNC_STATUS_FLASH_KEY, "") or "").strip()


def write_account_fantasy_preferences(
    session: dict[str, Any],
    *,
    reason: str = "",
    expected_revision: int | None = None,
    field_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist session prefs to cloud with revision increment and readback verification."""
    trace: dict[str, Any] = {
        "reason": reason,
        "written": False,
        "cloud_saved": False,
        "write_verified": False,
    }
    if not _signed_in(session):
        trace["skipped"] = "unsigned"
        return trace

    try:
        cloud = _load_cloud_prefs(session)
    except Exception as exc:
        _record_error(session, where="write_load_cloud", exc=exc)
        trace["error"] = type(exc).__name__
        session[WRITE_FAIL_FLASH_KEY] = SYNC_FAIL_USER_MSG
        session[LAST_SYNC_TRACE_KEY] = trace
        return trace

    cloud_rev = int(cloud.get("revision") or 0)
    local_rev = int(session.get(SESSION_LOCAL_REV_KEY) or session.get(SESSION_APPLIED_REV_KEY) or 0)
    base_rev = max(cloud_rev, local_rev)
    if expected_revision is not None and int(expected_revision) < cloud_rev:
        trace["conflict"] = "cloud_newer"
        trace["cloud_revision"] = cloud_rev
        _apply_prefs_to_session(session, cloud, source="conflict_resolve")
        session[LAST_SYNC_TRACE_KEY] = trace
        return trace

    new_rev = base_rev + 1
    doc = build_preference_document(session, revision=new_rev, field_overrides=field_overrides)
    trace["revision"] = new_rev
    trace["doc_active_draft_id"] = doc.get("active_draft_id")
    trace["doc_active_league_context_id"] = doc.get("active_league_context_id")
    saved = _save_cloud_prefs(session, doc)
    trace["cloud_saved"] = saved
    if not saved:
        session[WRITE_FAIL_FLASH_KEY] = SYNC_FAIL_USER_MSG
        session[LAST_SYNC_TRACE_KEY] = trace
        return trace

    readback = _load_cloud_prefs(session)
    ok, mismatch = _docs_match_for_verification(doc, readback)
    trace["write_verified"] = ok
    if not ok:
        trace["verification_error"] = mismatch or "readback_mismatch"
        session[WRITE_FAIL_FLASH_KEY] = SYNC_FAIL_USER_MSG
        session[LAST_SYNC_TRACE_KEY] = trace
        return trace

    session[SESSION_APPLIED_REV_KEY] = new_rev
    session[SESSION_LOCAL_REV_KEY] = new_rev
    session[SESSION_APPLIED_FP_KEY] = preference_document_fingerprint(doc)
    session.pop(LAST_SYNC_ERROR_KEY, None)
    trace["written"] = True
    session[LAST_SYNC_TRACE_KEY] = trace
    return trace


def activate_library_selection_and_sync_preferences(
    session: dict[str, Any],
    *,
    draft_id: str,
    reason: str = "activate_archive",
) -> dict[str, Any]:
    """Atomically activate archive/context, then write the cloud preference document."""
    from draft_archive_state import get_draft_archive
    from fantasy_league_context import (
        activate_archive_league_context,
        context_id_for_archive,
        get_league_context,
    )
    from saved_draft_library_selection import active_pair_is_coherent

    draft_id = str(draft_id or "").strip()
    result: dict[str, Any] = {
        "ok": False,
        "draft_id": draft_id,
        "reason": reason,
        "prefs_write": {},
    }
    if not draft_id:
        result["error"] = "missing_draft_id"
        return result

    entry = get_draft_archive(session, draft_id)
    if not isinstance(entry, dict):
        result["error"] = "archive_not_found"
        return result

    ctx_id = str(entry.get("league_context_id") or context_id_for_archive(draft_id)).strip()
    context = get_league_context(session, ctx_id)
    coherent, coherent_reason = active_pair_is_coherent(entry, context if isinstance(context, dict) else None)
    result["coherent"] = coherent
    result["coherent_reason"] = coherent_reason

    # Immediate activation — never defer when syncing account preferences.
    loaded_entry, loaded_context = activate_archive_league_context(
        session,
        draft_id,
        defer_activation=False,
    )
    _clear_pending_activation_keys(session)
    if not loaded_entry:
        result["error"] = "activation_failed"
        return result

    # Ensure session IDs match the explicit target before building the doc.
    session["active_draft_archive_id"] = draft_id
    try:
        from fantasy_league_context import ensure_fantasy_league_context_state

        store = ensure_fantasy_league_context_state(session)
        store["active_league_context_id"] = ctx_id
    except ImportError:
        pass

    invalidate_preference_dependent_caches(session)

    canonical_league_id = ""
    if isinstance(loaded_context, dict):
        try:
            from fantasy_league_identity import resolve_canonical_league_id

            canonical_league_id = str(resolve_canonical_league_id(loaded_context) or "").strip()
        except ImportError:
            pass

    write_trace = write_account_fantasy_preferences(
        session,
        reason=reason,
        field_overrides={
            "active_draft_id": draft_id,
            "active_league_context_id": ctx_id,
            "active_canonical_league_id": canonical_league_id,
        },
    )
    result["prefs_write"] = write_trace
    result["ok"] = bool(write_trace.get("write_verified") or write_trace.get("skipped") == "unsigned")
    result["entry"] = loaded_entry
    result["context"] = loaded_context
    result["active_draft_id"] = draft_id
    result["active_league_context_id"] = ctx_id
    return result


def preference_revision_fingerprint(session: dict[str, Any]) -> str:
    rev = int(session.get(SESSION_APPLIED_REV_KEY) or session.get(SESSION_LOCAL_REV_KEY) or 0)
    fp = str(session.get(SESSION_APPLIED_FP_KEY) or "")
    return f"{rev}:{fp}" if fp else str(rev)


def collect_account_preference_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Developer Mode diagnostics for preference sync identity and revisions."""
    local_fields = _read_session_prefs_fields(session)
    remote: dict[str, Any] = {}
    remote_err = ""
    try:
        remote = _load_cloud_prefs(session) if (_cloud_sync_available() and _signed_in(session)) else {}
    except Exception as exc:
        remote_err = f"{type(exc).__name__}: {exc}"[:200]
    last_trace = session.get(LAST_SYNC_TRACE_KEY)
    last_write = session.get(LAST_WRITE_TRACE_KEY)
    last_error = session.get(LAST_SYNC_ERROR_KEY)
    header = {}
    try:
        header = load_preference_revision_meta(session)
    except Exception:
        header = {}
    widget_live = session.get("_fcs_live_context_toggle_widget")
    widget_sim = session.get("_fcs_sim_context_toggle_widget")
    widget_research = session.get("_fcs_research_sync_toggle_widget")
    persisted_research = bool(session.get(FANTASY_RESEARCH_SYNC_KEY))
    persisted_live = bool(session.get(USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY))
    persisted_sim = bool(session.get(USE_SIMULATOR_BOARD_AS_FANTASY_CONTEXT_KEY))
    return {
        "authenticated_user_id": local_fields.get("user_id"),
        "external_account_id": str(session.get("_suite_auth_external_id") or ""),
        "workspace_id": local_fields.get("workspace_id"),
        "preference_settings_app": _prefs_settings_app(session),
        "preference_revision_app": prefs_revision_settings_app(session),
        "preference_doc_key": PREFS_DOC_KEY,
        "full_preference_document_revision": int(remote.get("revision") or 0),
        "revision_header_revision": int(header.get("revision") or 0),
        "preference_fingerprint_local": str(session.get(SESSION_APPLIED_FP_KEY) or ""),
        "preference_fingerprint_remote": preference_document_fingerprint(remote) if remote else "",
        "preference_fingerprint_header": str(header.get("preference_fingerprint") or ""),
        "remote_research_mode_enabled": bool(remote.get("research_mode_enabled")) if remote else None,
        "remote_fantasy_source_override_kind": str(remote.get("fantasy_source_override_kind") or "") if remote else None,
        "remote_fantasy_source_override_id": str(remote.get("fantasy_source_override_id") or "") if remote else None,
        "local_persisted_research_mode": persisted_research,
        "local_persisted_live_override": persisted_live,
        "local_persisted_simulator_override": persisted_sim,
        "widget_research_mode": widget_research if widget_research is not None else None,
        "widget_live_override": widget_live if widget_live is not None else None,
        "widget_simulator_override": widget_sim if widget_sim is not None else None,
        "widget_matches_persisted": {
            "research": (widget_research is None) or (bool(widget_research) == persisted_research),
            "live": (widget_live is None) or (bool(widget_live) == persisted_live),
            "simulator": (widget_sim is None) or (bool(widget_sim) == persisted_sim),
        },
        "local_active_draft_id": local_fields.get("active_draft_id"),
        "local_active_context_id": local_fields.get("active_league_context_id"),
        "remote_active_draft_id": str(remote.get("active_draft_id") or ""),
        "remote_active_context_id": str(remote.get("active_league_context_id") or ""),
        "last_preference_write_reason": (last_write or {}).get("reason") if isinstance(last_write, dict) else None,
        "last_preference_write_document": (last_write or {}).get("write_document") if isinstance(last_write, dict) else {},
        "write_readback_document": (last_write or {}).get("readback_document") if isinstance(last_write, dict) else {},
        "write_verified": (last_write or {}).get("write_verified") if isinstance(last_write, dict) else None,
        "last_remote_apply_source": (last_trace or {}).get("source") if isinstance(last_trace, dict) else None,
        "mismatched_fields": (last_trace or {}).get("mismatched_fields") if isinstance(last_trace, dict) else [],
        "widget_reseed_result": (last_write or last_trace or {}).get("widget_reseed_result")
        if isinstance(last_write or last_trace, dict)
        else None,
        "last_sync_result": last_trace if isinstance(last_trace, dict) else {},
        "last_sync_error": last_error if isinstance(last_error, dict) else {},
        "cloud_read_error": remote_err,
        "cloud_sync_available": _cloud_sync_available(),
        "signed_in": _signed_in(session),
    }



def pop_preference_sync_warning(session: dict[str, Any]) -> str:
    return str(session.pop(WRITE_FAIL_FLASH_KEY, "") or "").strip()


def render_account_preference_sync_fragment(st: Any) -> None:
    """Periodic lightweight preference revision poll — run_every=8s on relevant pages."""
    session = st.session_state

    def _tick() -> None:
        msg = pop_preference_sync_warning(session)
        if msg:
            st.warning(msg)
        if not _signed_in(session) or not _cloud_sync_available():
            return
        meta = load_preference_revision_meta(session)
        remote_rev = int(meta.get("revision") or 0)
        remote_fp = str(meta.get("preference_fingerprint") or "")
        local_rev = int(session.get(SESSION_APPLIED_REV_KEY) or 0)
        local_fp = str(session.get(SESSION_APPLIED_FP_KEY) or "")
        # Local drift against applied fingerprint — even at equal revision.
        local_fields = _read_session_prefs_fields(session)
        synth = {**local_fields, "revision": local_rev}
        local_drift = bool(local_fp) and preference_document_fingerprint(synth) != local_fp
        if remote_rev < local_rev:
            return
        if remote_rev == local_rev and remote_fp == local_fp and not local_drift:
            return
        result = sync_account_fantasy_preferences(session, force=True)
        if result.get("needs_rerun") or result.get("applied"):
            rerun = getattr(st, "rerun", None)
            if callable(rerun):
                try:
                    rerun(scope="app")
                except TypeError:
                    rerun()

    fragment = getattr(st, "fragment", None)
    if callable(fragment):
        @fragment(run_every=POLL_INTERVAL_SEC)
        def _poll_fragment() -> None:
            _tick()

        _poll_fragment()
    else:
        # Fallback for environments without fragments (tests / older Streamlit).
        sync_account_fantasy_preferences(session, poll=True)


def maybe_render_account_preference_sync(st: Any, *, page: str = "") -> None:
    """Wire the sync fragment onto supported Baseball workflow pages."""
    supported = {
        "Saved Draft Library",
        "Fantasy Lineup Assistant",
        "Fantasy Standings Tracker",
        "Waiver Wire / Add-Drop Center",
        "Draft Assistant Simulator",
        "Live Draft Room",
    }
    if page and page not in supported:
        return
    try:
        render_account_preference_sync_fragment(st)
    except Exception as exc:
        _record_error(st.session_state, where="render_account_preference_sync_fragment", exc=exc)
