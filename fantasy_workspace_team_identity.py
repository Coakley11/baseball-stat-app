"""Canonical per-workspace team identity for shared leagues."""

from __future__ import annotations

import copy
from typing import Any

from fantasy_league_identity import resolve_canonical_league_id
from fantasy_league_team_ownership import account_user_ids_match

TEAM_IDENTITY_TRACE_KEY = "_suite_team_identity_resolution_trace"


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def session_account_identity(session: dict[str, Any]) -> tuple[str, str, str, str, str]:
    uid = str(session.get("_suite_auth_user_id") or session.get("_suite_cloud_user_id") or "").strip()
    external = str(session.get("_suite_auth_external_id") or "").strip().lower()
    workspace = str(
        session.get("_suite_owned_workspace_id") or session.get("_suite_active_workspace_id") or ""
    ).strip()
    email = str(session.get("_suite_auth_user_email") or "").strip().lower()
    email_local = email.split("@", 1)[0] if email else ""
    return uid, external, workspace, email, email_local


def build_account_aliases(
    session: dict[str, Any] | None = None,
    *,
    owner_user_id: str = "",
    owner_external_id: str = "",
    workspace_id: str = "",
) -> set[str]:
    if session:
        uid, external, workspace, email, email_local = session_account_identity(session)
    else:
        uid = str(owner_user_id or "").strip()
        external = str(owner_external_id or "").strip().lower()
        workspace = str(workspace_id or "").strip()
        email = ""
        email_local = ""
    aliases: set[str] = set()
    for value in (
        uid,
        external,
        workspace,
        workspace.lower() if workspace else "",
        email,
        email_local,
        f"user:{external}" if external else "",
        f"local:{external}" if external else "",
    ):
        token = str(value or "").strip()
        if token:
            aliases.add(token)
            aliases.add(token.lower())
    return aliases


def _ownership_record_matches_aliases(record: dict[str, Any], aliases: set[str]) -> bool:
    if not isinstance(record, dict) or not aliases:
        return False
    candidates = {
        str(record.get("user_id") or "").strip(),
        str(record.get("external_id") or "").strip().lower(),
        str(record.get("display_name") or "").strip().lower(),
        str(record.get("email") or "").strip().lower(),
        str(record.get("email") or "").strip().lower().split("@", 1)[0],
        str(record.get("invitee_external_id") or "").strip().lower(),
        str(record.get("invitee_workspace_id") or "").strip(),
        str(record.get("accepted_by_external_id") or "").strip().lower(),
        str(record.get("accepted_by_workspace_id") or "").strip(),
    }
    for candidate in candidates:
        if candidate and candidate in aliases:
            return True
    return False


def owned_team_from_ownership(
    ownership: dict[str, Any] | None,
    *,
    owner_user_id: str = "",
    aliases: set[str] | None = None,
) -> str:
    """Resolve one owned team from canonical team_ownership."""
    if not isinstance(ownership, dict) or not ownership:
        return ""
    uid = str(owner_user_id or "").strip()
    alias_set = set(aliases or set())
    exact_uid_matches: list[str] = []
    alias_claimed_matches: list[str] = []
    alias_unclaimed_matches: list[str] = []

    for team, record in ownership.items():
        team_name = str(team or "").strip()
        if not team_name or not isinstance(record, dict):
            continue
        stored_uid = str(record.get("user_id") or "").strip()
        if stored_uid and uid and account_user_ids_match(stored_uid, uid):
            exact_uid_matches.append(team_name)
            continue
        if not _ownership_record_matches_aliases(record, alias_set):
            continue
        if stored_uid:
            alias_claimed_matches.append(team_name)
        else:
            alias_unclaimed_matches.append(team_name)

    if exact_uid_matches:
        return sorted(exact_uid_matches)[0]
    if len(alias_claimed_matches) == 1:
        return alias_claimed_matches[0]
    if alias_claimed_matches:
        return sorted(alias_claimed_matches)[0]
    if len(alias_unclaimed_matches) == 1:
        return alias_unclaimed_matches[0]
    return ""


def owned_team_from_shared_doc(
    shared_doc: dict[str, Any] | None,
    session: dict[str, Any] | None = None,
    *,
    owner_user_id: str = "",
    owner_external_id: str = "",
    workspace_id: str = "",
) -> str:
    if not isinstance(shared_doc, dict):
        return ""
    ownership = shared_doc.get("team_ownership") or {}
    uid, external, workspace, _, _ = (
        session_account_identity(session) if session else (owner_user_id, owner_external_id, workspace_id, "", "")
    )
    aliases = build_account_aliases(
        session,
        owner_user_id=uid or owner_user_id,
        owner_external_id=external or owner_external_id,
        workspace_id=workspace or workspace_id,
    )
    return owned_team_from_ownership(
        ownership if isinstance(ownership, dict) else {},
        owner_user_id=uid or owner_user_id,
        aliases=aliases,
    )


def _is_commissioner_for_context(
    session: dict[str, Any],
    context: dict[str, Any],
    shared_doc: dict[str, Any] | None = None,
) -> bool:
    from fantasy_league_invites import is_league_commissioner

    uid, _, _, _, _ = session_account_identity(session)
    if not uid:
        return False
    meta = context.get("metadata") or {}
    commissioner = str(
        meta.get("commissioner_user_id")
        or (shared_doc or {}).get("commissioner_user_id")
        or ""
    ).strip()
    return bool(is_league_commissioner(context, uid) or account_user_ids_match(uid, commissioner))


def _claimed_team_from_accepted_invite(
    session: dict[str, Any],
    shared_doc: dict[str, Any] | None,
) -> str:
    from fantasy_league_invites import INVITE_STATUS_ACCEPTED
    from fantasy_shared_league_startup_sync import _record_matches_account

    if not isinstance(shared_doc, dict):
        return ""
    uid, external, workspace, _, _ = session_account_identity(session)
    invites = shared_doc.get("league_invites") or []
    if not isinstance(invites, list):
        return ""
    for invite in invites:
        if not isinstance(invite, dict):
            continue
        if str(invite.get("status") or "").strip() != INVITE_STATUS_ACCEPTED:
            continue
        if not _record_matches_account(
            invite,
            user_id=uid,
            external_id=external,
            workspace_id=workspace,
        ):
            continue
        return str(invite.get("claimed_team") or "").strip()
    return ""


def _shared_league_context(context: dict[str, Any]) -> bool:
    if not isinstance(context, dict):
        return False
    league_id = str(resolve_canonical_league_id(context) or "").strip()
    if league_id:
        return True
    return str(context.get("context_type") or "").strip() == "real_league"


def overlay_workspace_team_on_context(
    session: dict[str, Any],
    context: dict[str, Any] | None,
    *,
    shared_doc: dict[str, Any] | None = None,
    trace_phase: str = "",
    record_trace: bool = True,
) -> dict[str, Any] | None:
    """Apply canonical ownership team; never let stale archive/context team bleed across accounts."""
    if not isinstance(context, dict):
        return context

    uid, external, workspace, _, _ = session_account_identity(session)
    pre_merge_team = str(context.get("my_team_name") or "").strip()
    out = copy.deepcopy(context)
    league_id = str(resolve_canonical_league_id(out) or "").strip()

    shared = shared_doc
    if shared is None and league_id:
        try:
            from fantasy_shared_league_store import load_shared_league

            loaded = load_shared_league(league_id)
            shared = loaded if isinstance(loaded, dict) else None
        except ImportError:
            shared = None

    ownership = {}
    if isinstance(shared, dict):
        raw = shared.get("team_ownership") or {}
        ownership = raw if isinstance(raw, dict) else {}
    if not ownership:
        try:
            from fantasy_shared_league_store import get_team_ownership_from_context

            ownership = get_team_ownership_from_context(out)
        except ImportError:
            ownership = {}

    aliases = build_account_aliases(session)
    ownership_team = owned_team_from_ownership(ownership, owner_user_id=uid, aliases=aliases)
    if not ownership_team and isinstance(shared, dict):
        ownership_team = owned_team_from_shared_doc(shared, session)

    invite_team = ""
    if not _is_commissioner_for_context(session, out, shared):
        invite_team = _claimed_team_from_accepted_invite(session, shared)

    resolved_team = ownership_team or invite_team
    if resolved_team:
        out["my_team_name"] = resolved_team
    elif _shared_league_context(out):
        out["my_team_name"] = ""

    post_merge_team = str(out.get("my_team_name") or "").strip()

    if record_trace and trace_phase:
        record_team_identity_trace(
            session,
            phase=trace_phase,
            authenticated_workspace=workspace,
            ownership_resolved_team=ownership_team or None,
            pre_merge_team=pre_merge_team or None,
            post_merge_team=post_merge_team or None,
        )
    return out


def record_team_identity_trace(session: dict[str, Any], *, phase: str, **fields: Any) -> None:
    trace = session.get(TEAM_IDENTITY_TRACE_KEY)
    if not isinstance(trace, dict):
        trace = {"updated_at": _utc_now_iso(), "steps": []}
    steps = trace.setdefault("steps", [])
    if not isinstance(steps, list):
        steps = []
        trace["steps"] = steps
    entry = {"phase": str(phase or "").strip(), "at": _utc_now_iso()}
    entry.update({k: v for k, v in fields.items() if v is not None and v != ""})
    steps.append(entry)
    trace["updated_at"] = _utc_now_iso()
    for key in (
        "authenticated_workspace",
        "ownership_resolved_team",
        "pre_merge_team",
        "post_merge_team",
        "active_archive_team",
        "final_library_team",
        "final_fantasy_lineup_team",
    ):
        if key in entry:
            trace[key] = entry[key]
    session[TEAM_IDENTITY_TRACE_KEY] = trace


def get_team_identity_trace(session: dict[str, Any]) -> dict[str, Any]:
    raw = session.get(TEAM_IDENTITY_TRACE_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def resolve_archive_display_team(
    session: dict[str, Any],
    archive_entry: dict[str, Any] | None,
    context: dict[str, Any] | None = None,
) -> str:
    """Team label for Saved Draft Library cards — canonical ownership, not stale archive.team_name."""
    if not isinstance(archive_entry, dict):
        return ""
    if context is None:
        try:
            from fantasy_league_context import get_league_context_for_archive

            context = get_league_context_for_archive(session, archive_entry)
        except ImportError:
            context = None
    if isinstance(context, dict):
        team = str(context.get("my_team_name") or "").strip()
        if team:
            return team
    league_id = ""
    if isinstance(context, dict):
        league_id = str(resolve_canonical_league_id(context) or "").strip()
    if league_id:
        return ""
    return str(archive_entry.get("team_name") or "").strip()


def resolve_final_fantasy_lineup_team(session: dict[str, Any]) -> str:
    try:
        from fantasy_league_context import get_active_league_context

        context = get_active_league_context(session, respect_source_priority=True)
    except ImportError:
        context = None
    if isinstance(context, dict):
        return str(context.get("my_team_name") or "").strip()
    return ""


def resolve_final_rendered_context_teams(
    session: dict[str, Any],
    *,
    draft_id: str = "",
) -> dict[str, Any]:
    """Final teams as library + lineup pages would render after full resolution."""
    from draft_archive_state import ACTIVE_DRAFT_ARCHIVE_KEY, get_draft_archive, list_draft_archives

    uid, external, workspace, _, _ = session_account_identity(session)
    active_id = str(draft_id or session.get(ACTIVE_DRAFT_ARCHIVE_KEY) or "").strip()
    entry = get_draft_archive(session, active_id) if active_id else None
    if not isinstance(entry, dict):
        archives = list_draft_archives(session)
        entry = archives[0] if archives else None

    context = None
    if isinstance(entry, dict):
        try:
            from fantasy_league_context import get_league_context_for_archive

            context = get_league_context_for_archive(session, entry)
        except ImportError:
            context = None

    ownership_team = ""
    if isinstance(context, dict):
        league_id = str(resolve_canonical_league_id(context) or "").strip()
        if league_id:
            try:
                from fantasy_shared_league_store import load_shared_league

                shared = load_shared_league(league_id)
            except ImportError:
                shared = None
            if isinstance(shared, dict):
                ownership_team = owned_team_from_shared_doc(shared, session)

    library_team = resolve_archive_display_team(session, entry if isinstance(entry, dict) else None, context)
    lineup_team = resolve_final_fantasy_lineup_team(session)
    active_archive_team = str((entry or {}).get("team_name") or "").strip() if isinstance(entry, dict) else ""

    result = {
        "authenticated_workspace": workspace,
        "ownership_resolved_team": ownership_team or None,
        "pre_merge_team": None,
        "post_merge_team": str((context or {}).get("my_team_name") or "").strip() or None,
        "active_archive_team": active_archive_team or None,
        "final_library_team": library_team or None,
        "final_fantasy_lineup_team": lineup_team or None,
        "auth_user_id": uid or None,
        "auth_external_id": external or None,
        "draft_id": active_id or None,
    }
    record_team_identity_trace(session, phase="final_rendered_context", **result)
    return result
