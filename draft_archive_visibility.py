"""Saved Draft Library visibility — hide shared real_league entries until membership."""

from __future__ import annotations

import copy
from typing import Any


def _resolve_session_user_id(session: dict[str, Any]) -> str:
    try:
        from fantasy_league_team_ownership import _resolve_user_id

        return str(_resolve_user_id() or "").strip()
    except ImportError:
        pass
    return str(
        session.get("_suite_cloud_user_id")
        or session.get("_suite_auth_user_id")
        or ""
    ).strip()


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
        from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE, get_league_context_for_archive
        from fantasy_league_invites import is_league_commissioner
        from fantasy_league_team_ownership import owned_team_for_user
    except ImportError:
        return True

    ctx = context if context is not None else get_league_context_for_archive(session, entry)
    if not isinstance(ctx, dict):
        return True
    if str(ctx.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
        return True
    if not _auth_session_scope_active(session):
        return True

    uid = _resolve_session_user_id(session)
    if not uid:
        return False
    if is_league_commissioner(ctx, uid):
        return True
    if owned_team_for_user(ctx, uid):
        return True
    return False


def list_visible_draft_archives(session: dict[str, Any]) -> list[dict[str, Any]]:
    from draft_archive_state import list_draft_archives

    return [
        copy.deepcopy(entry)
        for entry in list_draft_archives(session)
        if is_saved_draft_visible_to_session(session, entry)
    ]


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
            CONTEXT_TYPE_REAL_LEAGUE,
            FANTASY_LEAGUE_CONTEXT_STATE_KEY,
            ensure_fantasy_league_context_state,
            get_league_context_for_archive,
        )
        from fantasy_league_invites import is_league_commissioner
        from fantasy_league_team_ownership import owned_team_for_user
        from workflow_persist_guard import mark_workflow_persist_authoritative
    except ImportError:
        return {"archives_removed": 0, "contexts_removed": 0}

    archives_removed = 0
    contexts_removed = 0
    kept_archives: list[dict[str, Any]] = []
    for entry in list_draft_archives(session):
        ctx = get_league_context_for_archive(session, entry)
        if is_saved_draft_visible_to_session(session, entry, context=ctx):
            kept_archives.append(entry)
        else:
            archives_removed += 1

    if archives_removed:
        session[DRAFT_ARCHIVE_KEY] = kept_archives
        active_id = str(session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "").strip()
        if active_id and not get_draft_archive(session, active_id):
            session.pop(ACTIVE_DRAFT_ARCHIVE_KEY, None)

    store = ensure_fantasy_league_context_state(session)
    contexts = store.get("contexts") or {}
    if isinstance(contexts, dict):
        uid = _resolve_session_user_id(session)
        auth_scope = _auth_session_scope_active(session)
        kept_ctx: dict[str, Any] = {}
        for context_id, ctx in contexts.items():
            if not isinstance(ctx, dict):
                continue
            if str(ctx.get("context_type") or "") != CONTEXT_TYPE_REAL_LEAGUE:
                kept_ctx[context_id] = ctx
                continue
            if not auth_scope:
                kept_ctx[context_id] = ctx
                continue
            if not uid:
                contexts_removed += 1
                continue
            if is_league_commissioner(ctx, uid) or owned_team_for_user(ctx, uid):
                kept_ctx[context_id] = ctx
            else:
                contexts_removed += 1
        if contexts_removed:
            store["contexts"] = kept_ctx
            session[FANTASY_LEAGUE_CONTEXT_STATE_KEY] = store

    if archives_removed or contexts_removed:
        try:
            mark_workflow_persist_authoritative(session)
        except Exception:
            pass
    return {"archives_removed": archives_removed, "contexts_removed": contexts_removed}
