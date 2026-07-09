"""Saved Draft Library visibility — hide shared real_league entries until membership."""

from __future__ import annotations

import copy
from typing import Any

LIBRARY_SANITIZE_VERSION = 2

_WORKFLOW_DISK_KEYS = (
    "draft_archive_teams",
    "active_draft_archive_id",
    "fantasy_league_context_state",
    "_deleted_draft_archive_ids",
)


def _resolve_session_user_id(session: dict[str, Any]) -> str:
    try:
        from fantasy_league_team_ownership import _resolve_user_id

        uid = str(_resolve_user_id() or "").strip()
        if uid:
            return uid
    except ImportError:
        pass
    cloud = str(session.get("_suite_cloud_user_id") or "").strip()
    if cloud:
        return cloud
    return str(session.get("_suite_auth_user_id") or "").strip()


def _auth_session_scope_active(session: dict[str, Any]) -> bool:
    try:
        from suite_auth import is_auth_enabled, is_authenticated

        if is_auth_enabled():
            return bool(is_authenticated(session))
    except ImportError:
        pass
    return bool(
        session.get("_suite_cloud_user_id")
        or session.get("_suite_auth_user_id")
        or session.get("_suite_auth_session")
    )


def _team_roster_count(entry: dict[str, Any], context: dict[str, Any] | None) -> int:
    rosters = entry.get("league_rosters") or {}
    if not isinstance(rosters, dict) or not rosters:
        if isinstance(context, dict):
            rosters = context.get("league_rosters") or {}
    if not isinstance(rosters, dict):
        return 0
    return len([name for name in rosters.keys() if str(name).strip()])


def _requires_membership_visibility(
    entry: dict[str, Any],
    context: dict[str, Any] | None,
) -> bool:
    """Uploaded/shared leagues require commissioner or claimed-team membership."""
    try:
        from draft_archive_state import DRAFT_TYPE_IMPORTED, DRAFT_TYPE_SIMULATOR
        from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE, SOURCE_IMPORTED_DRAFT
    except ImportError:
        return False

    draft_type = str(entry.get("draft_type") or "").strip()
    if draft_type == DRAFT_TYPE_IMPORTED:
        return True
    if draft_type == DRAFT_TYPE_SIMULATOR:
        return False
    if isinstance(context, dict):
        if str(context.get("context_type") or "") == CONTEXT_TYPE_REAL_LEAGUE:
            return True
        if str(context.get("source") or "") == SOURCE_IMPORTED_DRAFT:
            return True
    # Legacy polluted blobs may omit draft_type/context but still carry multi-team rosters.
    if _team_roster_count(entry, context) >= 2 and draft_type != DRAFT_TYPE_SIMULATOR:
        return True
    return False


def _has_shared_league_membership(
    session: dict[str, Any],
    entry: dict[str, Any],
    *,
    context: dict[str, Any] | None,
    user_id: str,
) -> bool:
    if not user_id:
        return False
    if not isinstance(context, dict):
        return False
    try:
        from fantasy_league_invites import is_league_commissioner
        from fantasy_league_team_ownership import owned_team_for_user
    except ImportError:
        return False
    if is_league_commissioner(context, user_id):
        return True
    try:
        from fantasy_league_invites import _joined_via_invite
    except ImportError:
        _joined_via_invite = lambda _ctx: False  # type: ignore[assignment,misc]
    if _joined_via_invite(context) and owned_team_for_user(context, user_id):
        return True
    return False


def is_saved_draft_visible_to_session(
    session: dict[str, Any],
    entry: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> bool:
    """True when the signed-in account may see this library card."""
    if not isinstance(entry, dict):
        return False
    try:
        from fantasy_league_context import get_league_context_for_archive
    except ImportError:
        return True

    ctx = context if context is not None else get_league_context_for_archive(session, entry)
    if not _requires_membership_visibility(entry, ctx):
        return True
    if not _auth_session_scope_active(session):
        return True

    uid = _resolve_session_user_id(session)
    return _has_shared_league_membership(session, entry, context=ctx, user_id=uid)


def list_visible_draft_archives(session: dict[str, Any]) -> list[dict[str, Any]]:
    from draft_archive_state import list_draft_archives

    return [
        copy.deepcopy(entry)
        for entry in list_draft_archives(session)
        if is_saved_draft_visible_to_session(session, entry)
    ]


def _record_removed_draft_tombstones(session: dict[str, Any], removed_entries: list[dict[str, Any]]) -> None:
    from draft_archive_state import DELETED_DRAFT_ARCHIVE_IDS_KEY

    if not removed_entries:
        return
    deleted = {
        str(item).strip()
        for item in (session.get(DELETED_DRAFT_ARCHIVE_IDS_KEY) or [])
        if str(item).strip()
    }
    for entry in removed_entries:
        draft_id = str(entry.get("draft_id") or "").strip()
        if draft_id:
            deleted.add(draft_id)
    session[DELETED_DRAFT_ARCHIVE_IDS_KEY] = sorted(deleted)


def _record_removed_context_tombstones(session: dict[str, Any], removed_context_ids: list[str]) -> None:
    if not removed_context_ids:
        return
    try:
        from fantasy_league_context import ensure_fantasy_league_context_state
    except ImportError:
        return
    store = ensure_fantasy_league_context_state(session)
    deleted = {
        str(item).strip()
        for item in (store.get("deleted_context_ids") or [])
        if str(item).strip()
    }
    deleted.update(str(item).strip() for item in removed_context_ids if str(item).strip())
    store["deleted_context_ids"] = sorted(deleted)


def _repair_league_context_identities(session: dict[str, Any]) -> None:
    """Backfill commissioner/ownership ids before visibility prune (local vs cloud uuid drift)."""
    try:
        from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE, list_league_contexts
        from fantasy_league_invites import repair_commissioner_identity
    except ImportError:
        return
    for ctx in list_league_contexts(session):
        if str(ctx.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
            continue
        repair_commissioner_identity(ctx, session)


def prune_invisible_shared_league_state(session: dict[str, Any]) -> dict[str, int]:
    """Remove shared real_league archives/contexts the account should not see."""
    from draft_archive_state import (
        ACTIVE_DRAFT_ARCHIVE_KEY,
        DRAFT_ARCHIVE_KEY,
        get_draft_archive,
        list_draft_archives,
    )

    try:
        from fantasy_league_context import (
            FANTASY_LEAGUE_CONTEXT_STATE_KEY,
            ensure_fantasy_league_context_state,
            get_league_context_for_archive,
        )
        from workflow_persist_guard import mark_workflow_persist_authoritative
    except ImportError:
        return {"archives_removed": 0, "contexts_removed": 0}

    _repair_league_context_identities(session)

    archives_removed = 0
    contexts_removed = 0
    removed_entries: list[dict[str, Any]] = []
    removed_context_ids: list[str] = []
    kept_archives: list[dict[str, Any]] = []
    for entry in list_draft_archives(session):
        ctx = get_league_context_for_archive(session, entry)
        if is_saved_draft_visible_to_session(session, entry, context=ctx):
            kept_archives.append(entry)
        else:
            archives_removed += 1
            removed_entries.append(entry)

    if archives_removed:
        session[DRAFT_ARCHIVE_KEY] = kept_archives
        _record_removed_draft_tombstones(session, removed_entries)
        active_id = str(session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "").strip()
        if active_id and not get_draft_archive(session, active_id):
            session.pop(ACTIVE_DRAFT_ARCHIVE_KEY, None)

    store = ensure_fantasy_league_context_state(session)
    contexts = store.get("contexts") or {}
    if isinstance(contexts, dict):
        auth_scope = _auth_session_scope_active(session)
        uid = _resolve_session_user_id(session)
        kept_ctx: dict[str, Any] = {}
        for context_id, ctx in contexts.items():
            if not isinstance(ctx, dict):
                continue
            stub = {"draft_id": str(ctx.get("source_draft_id") or ""), "league_context_id": context_id}
            if not _requires_membership_visibility(stub, ctx):
                kept_ctx[context_id] = ctx
                continue
            if not auth_scope:
                kept_ctx[context_id] = ctx
                continue
            if _has_shared_league_membership(session, stub, context=ctx, user_id=uid):
                kept_ctx[context_id] = ctx
            else:
                contexts_removed += 1
                removed_context_ids.append(context_id)
        if contexts_removed:
            store["contexts"] = kept_ctx
            active_ctx_id = str(store.get("active_league_context_id") or "").strip()
            if active_ctx_id and active_ctx_id not in kept_ctx:
                store.pop("active_league_context_id", None)
            _record_removed_context_tombstones(session, removed_context_ids)
            session[FANTASY_LEAGUE_CONTEXT_STATE_KEY] = store

    if archives_removed or contexts_removed:
        try:
            mark_workflow_persist_authoritative(session)
        except Exception:
            pass
    return {"archives_removed": archives_removed, "contexts_removed": contexts_removed}


def _workflow_patch_from_session(session: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for key in _WORKFLOW_DISK_KEYS:
        if key in session:
            patch[key] = copy.deepcopy(session[key])
    if "active_draft_archive_id" not in patch:
        patch.pop("active_draft_archive_id", None)
    if "draft_archive_teams" not in patch:
        patch["draft_archive_teams"] = []
    return patch


def sanitize_workflow_blob_for_account(session: dict[str, Any], blob: dict[str, Any]) -> dict[str, Any]:
    """Return a disk/cloud workflow blob with foreign shared leagues removed for this account."""
    if not isinstance(blob, dict) or not blob:
        return {}
    scratch = dict(session)
    for key in _WORKFLOW_DISK_KEYS:
        if key in blob:
            scratch[key] = copy.deepcopy(blob[key])
    prune_invisible_shared_league_state(scratch)
    out = copy.deepcopy(blob)
    patch = _workflow_patch_from_session(scratch)
    for key in _WORKFLOW_DISK_KEYS:
        if key in patch:
            out[key] = copy.deepcopy(patch[key])
        elif key == "active_draft_archive_id":
            out.pop(key, None)
        elif key == "draft_archive_teams":
            out[key] = []
    return out


def force_persist_sanitized_workflow_disk(
    session: dict[str, Any],
    *,
    app_id: str = "baseball",
) -> bool:
    """Rewrite the workspace disk file with sanitized draft library workflow keys."""
    try:
        from suite_user_persistence import _load_raw, save_user_state
        from workflow_persist_guard import WORKFLOW_PERSIST_ALLOW_CLEAR_KEY, mark_workflow_persist_authoritative
    except ImportError:
        return False

    prune_invisible_shared_league_state(session)
    mark_workflow_persist_authoritative(session)
    session[WORKFLOW_PERSIST_ALLOW_CLEAR_KEY] = True

    disk_state, _, _ = _load_raw(app_id)
    if not isinstance(disk_state, dict):
        disk_state = {}
    disk_state = sanitize_workflow_blob_for_account(session, disk_state)
    patch = _workflow_patch_from_session(session)
    for key, val in patch.items():
        disk_state[key] = copy.deepcopy(val)
    if not str(disk_state.get("active_draft_archive_id") or "").strip():
        disk_state.pop("active_draft_archive_id", None)
    return bool(save_user_state(app_id, disk_state))


def sanitize_workflow_library_for_account(
    session: dict[str, Any],
    *,
    st: Any | None = None,
    persist_cleanup: bool = False,
    app_id: str = "baseball",
) -> dict[str, Any]:
    """
    Drop foreign shared leagues from session and optionally rewrite cloud/disk rows.

    Tombstones removed draft ids so disk union-merge cannot reintroduce leaked leagues.
    """
    before_archives = 0
    try:
        from draft_archive_state import list_draft_archives

        before_archives = len(list_draft_archives(session))
    except ImportError:
        pass

    removed = prune_invisible_shared_league_state(session)
    total = int(removed.get("archives_removed") or 0) + int(removed.get("contexts_removed") or 0)
    out = dict(removed)
    out["total_removed"] = total
    out["disk_persisted"] = False
    out["persisted"] = False

    try:
        from draft_archive_state import list_draft_archives

        after_archives = len(list_draft_archives(session))
    except ImportError:
        after_archives = 0

    needs_disk_rewrite = bool(
        persist_cleanup and _auth_session_scope_active(session) and total > 0
    )
    if needs_disk_rewrite:
        out["disk_persisted"] = force_persist_sanitized_workflow_disk(session, app_id=app_id)

    if total > 0 or out.get("disk_persisted"):
        session["_suite_workflow_library_sanitized"] = dict(out)
        session["_suite_workflow_library_sanitize_version"] = LIBRARY_SANITIZE_VERSION

    if persist_cleanup and st is not None and (total > 0 or out.get("disk_persisted")):
        try:
            from workflow_persist_guard import WORKFLOW_PERSIST_ALLOW_CLEAR_KEY, mark_workflow_persist_authoritative

            mark_workflow_persist_authoritative(session)
            session[WORKFLOW_PERSIST_ALLOW_CLEAR_KEY] = True
            from baseball_persistent_state import force_save_baseball_state

            out["persisted"] = bool(force_save_baseball_state(st, reason="workflow_library_sanitized"))
        except Exception:
            out["persisted"] = False
    return out
