"""Team ownership mapping and trade eligibility for shared saved leagues."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from fantasy_league_context import (
    CONTEXT_TYPE_REAL_LEAGUE,
    MIGRATION_STATUS_SINGLE_TEAM_LEGACY,
    get_active_league_context,
    get_league_context,
    upsert_league_context,
)
from fantasy_league_identity import ensure_league_identity, resolve_canonical_league_id

TRADES_MOCK_SIM_DISABLED_MESSAGE = (
    "Trades are unavailable for solo mock drafts and draft simulations."
)
TRADES_AWAITING_CLAIMS_MESSAGE = (
    "Trades unlock after at least two teams are claimed by different accounts."
)
TRADES_DISABLED_MESSAGE = TRADES_AWAITING_CLAIMS_MESSAGE
TEAM_ASSIGNMENT_PROMPT = "Which team is yours?"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _resolve_user_id() -> str:
    try:
        from suite_user import get_account_user_id

        return str(get_account_user_id() or "").strip()
    except ImportError:
        return ""


def account_user_ids_match(stored_id: str, current_id: str = "") -> bool:
    """True when two persisted account ids refer to the same signed-in user."""
    stored = str(stored_id or "").strip()
    current = str(current_id or _resolve_user_id()).strip()
    if not stored or not current:
        return False
    if stored == current:
        return True
    try:
        from suite_user import get_account_user_id, get_external_user_id

        ext = str(get_external_user_id() or "").strip().lower()
        if not ext:
            return False
        canonical = str(get_account_user_id() or "").strip()
        local_keys = {f"local:{ext}", f"local:{ext.lower()}"}
        if stored in local_keys and current == canonical:
            return True
        if current in local_keys and stored == canonical:
            return True
        if stored in local_keys and current in local_keys:
            return True
    except ImportError:
        pass
    return False


def repair_upload_team_ownership_identity(
    context: dict[str, Any],
    session: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Normalize upload-owner team_ownership user_id to the canonical cloud account id."""
    if not isinstance(context, dict):
        return context, False
    uid = _resolve_user_id()
    if not uid:
        return context, False
    my_team = str(context.get("my_team_name") or "").strip()
    if not my_team:
        return context, False
    ownership = get_team_ownership(context)
    record = ownership.get(my_team) or {}
    stored = str(record.get("user_id") or "").strip()
    if not stored or stored == uid or not account_user_ids_match(stored, uid):
        return context, False
    ownership[my_team] = {**record, "user_id": uid}
    _set_team_ownership(context, ownership)
    if isinstance(session, dict):
        context = upsert_league_context(session, context)
        try:
            from workflow_persist_guard import mark_workflow_persist_authoritative

            mark_workflow_persist_authoritative(session)
        except ImportError:
            pass
    return context, True


def _resolve_user_email() -> str:
    try:
        from suite_user import get_user_email

        return str(get_user_email() or "").strip()
    except ImportError:
        return ""


def _resolve_display_name() -> str:
    try:
        from suite_user import get_display_name

        name = str(get_display_name() or "").strip()
        if name:
            return name
    except ImportError:
        pass
    email = _resolve_user_email()
    if email and "@" in email:
        return email.split("@", 1)[0]
    return ""


def get_team_ownership(context: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(context, dict):
        return {}
    raw = context.get("team_ownership")
    if not isinstance(raw, dict):
        meta = context.get("metadata") or {}
        raw = meta.get("team_ownership")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for team_name, record in raw.items():
        team = str(team_name or "").strip()
        if not team or not isinstance(record, dict):
            continue
        out[team] = dict(record)
    return out


def _set_team_ownership(context: dict[str, Any], ownership: dict[str, dict[str, Any]]) -> None:
    context["team_ownership"] = copy.deepcopy(ownership)  # type: ignore[name-defined]
    meta = dict(context.get("metadata") or {})
    meta["team_ownership"] = copy.deepcopy(ownership)  # type: ignore[name-defined]
    context["metadata"] = meta


def assign_team_owner_to_context(
    context: dict[str, Any],
    team_name: str,
    *,
    user_id: str = "",
    email: str = "",
    display_name: str = "",
) -> dict[str, Any]:
    team = str(team_name or "").strip()
    if not team:
        return context
    context = ensure_league_identity(context)
    league_id = resolve_canonical_league_id(context)
    ownership = get_team_ownership(context)
    uid = str(user_id or _resolve_user_id()).strip()
    ownership[team] = {
        "team_name": team,
        "team_id": team,
        "user_id": uid,
        "email": str(email or _resolve_user_email()).strip(),
        "display_name": str(display_name or _resolve_display_name()).strip(),
        "league_id": league_id,
        "assigned_at": _utc_now_iso(),
    }
    _set_team_ownership(context, ownership)
    return context


def assign_my_team(
    session: dict[str, Any],
    team_name: str,
    *,
    user_id: str = "",
    email: str = "",
    display_name: str = "",
) -> tuple[dict[str, Any] | None, str]:
    context = get_active_league_context(session)
    if not context:
        return None, "Set an active league context before assigning your team."
    league_context_id = str(context.get("league_context_id") or "").strip()
    context = get_league_context(session, league_context_id)
    if not context:
        return None, "Active league context could not be loaded."
    team = str(team_name or "").strip()
    teams = set((context.get("league_rosters") or {}).keys())
    if team not in teams:
        return None, f"Team '{team}' is not in this league."
    ownership = get_team_ownership(context)
    uid = str(user_id or _resolve_user_id()).strip()
    for owned_team, record in ownership.items():
        other_uid = str(record.get("user_id") or "").strip()
        if account_user_ids_match(other_uid, uid) and owned_team != team:
            return None, f"Your account is already assigned to {owned_team}."
        if owned_team == team:
            if other_uid and not account_user_ids_match(other_uid, uid):
                return None, f"{team} is already owned by another account."
    context = assign_team_owner_to_context(
        context,
        team,
        user_id=uid,
        email=email,
        display_name=display_name,
    )
    context["my_team_name"] = team
    saved = upsert_league_context(session, context)
    try:
        from fantasy_shared_league_store import push_league_context_to_shared

        push_league_context_to_shared(session, saved)
    except ImportError:
        pass
    return saved, ""


def claim_team_in_league_context(
    session: dict[str, Any],
    league_context_id: str,
    team_name: str,
    *,
    user_id: str = "",
    email: str = "",
    display_name: str = "",
) -> tuple[dict[str, Any] | None, str]:
    """Claim a team on a specific league context (invite accept / library claim)."""
    league_context_id = str(league_context_id or "").strip()
    context = get_league_context(session, league_context_id)
    if not context:
        return None, "League context could not be loaded."
    team = str(team_name or "").strip()
    teams = set((context.get("league_rosters") or {}).keys())
    if team not in teams:
        return None, f"Team '{team}' is not in this league."
    ownership = get_team_ownership(context)
    uid = str(user_id or _resolve_user_id()).strip()
    for owned_team, record in ownership.items():
        other_uid = str(record.get("user_id") or "").strip()
        if account_user_ids_match(other_uid, uid) and owned_team != team:
            return None, f"Your account is already assigned to {owned_team}."
        if owned_team == team:
            if other_uid and not account_user_ids_match(other_uid, uid):
                return None, f"{team} is already owned by another account."
    context = assign_team_owner_to_context(
        context,
        team,
        user_id=uid,
        email=email,
        display_name=display_name,
    )
    context["my_team_name"] = team
    saved = upsert_league_context(session, context)
    try:
        from fantasy_shared_league_store import push_league_context_to_shared

        push_league_context_to_shared(session, saved)
    except ImportError:
        pass
    return saved, ""


def owned_team_for_user(context: dict[str, Any] | None, user_id: str = "") -> str:
    uid = str(user_id or _resolve_user_id()).strip()
    if not uid:
        return ""
    for team, record in get_team_ownership(context).items():
        if account_user_ids_match(str(record.get("user_id") or "").strip(), uid):
            return team
    return ""


def owner_user_id_for_team(context: dict[str, Any] | None, team_name: str) -> str:
    team = str(team_name or "").strip()
    if not team:
        return ""
    record = get_team_ownership(context).get(team) or {}
    return str(record.get("user_id") or "").strip()


def owner_display_for_team(context: dict[str, Any] | None, team_name: str) -> str:
    team = str(team_name or "").strip()
    if not team:
        return ""
    record = get_team_ownership(context).get(team) or {}
    display = str(record.get("display_name") or "").strip()
    if display:
        return display
    email = str(record.get("email") or "").strip()
    if email and "@" in email:
        return email.split("@", 1)[0]
    return team


def distinct_account_owner_count(context: dict[str, Any] | None) -> int:
    user_ids = {
        str(record.get("user_id") or "").strip()
        for record in get_team_ownership(context).values()
        if str(record.get("user_id") or "").strip()
    }
    return len(user_ids)


def claimed_team_count(context: dict[str, Any] | None) -> int:
    return sum(
        1
        for record in get_team_ownership(context).values()
        if str(record.get("user_id") or "").strip()
    )


def needs_team_assignment(context: dict[str, Any] | None, user_id: str = "") -> bool:
    if not isinstance(context, dict):
        return False
    uid = str(user_id or _resolve_user_id()).strip()
    if not uid:
        return False
    if owned_team_for_user(context, uid):
        return False
    teams = list((context.get("league_rosters") or {}).keys())
    return len(teams) >= 1


def trades_enabled(context: dict[str, Any] | None, session: dict[str, Any] | None = None) -> tuple[bool, str]:
    del session
    if not isinstance(context, dict):
        return False, TRADES_MOCK_SIM_DISABLED_MESSAGE

    context_type = str(context.get("context_type") or "").strip()
    if context_type != CONTEXT_TYPE_REAL_LEAGUE:
        return False, TRADES_MOCK_SIM_DISABLED_MESSAGE

    context = ensure_league_identity(context)
    league_id = resolve_canonical_league_id(context)
    if not league_id:
        return False, TRADES_MOCK_SIM_DISABLED_MESSAGE

    meta = context.get("metadata") or {}
    source_draft_id = str(meta.get("source_draft_id") or meta.get("draft_id") or "").strip()
    if not source_draft_id:
        return False, TRADES_MOCK_SIM_DISABLED_MESSAGE

    if str(meta.get("migration_status") or "") == MIGRATION_STATUS_SINGLE_TEAM_LEGACY:
        return False, TRADES_MOCK_SIM_DISABLED_MESSAGE

    rosters = context.get("league_rosters") or {}
    if not isinstance(rosters, dict) or len(rosters) < 2:
        return False, TRADES_MOCK_SIM_DISABLED_MESSAGE

    if claimed_team_count(context) < 2 or distinct_account_owner_count(context) < 2:
        return False, TRADES_AWAITING_CLAIMS_MESSAGE

    uid = _resolve_user_id()
    my_team = owned_team_for_user(context, uid)
    if not my_team:
        return False, TEAM_ASSIGNMENT_PROMPT

    return True, ""


def resolve_trade_team_for_session(context: dict[str, Any] | None, session: dict[str, Any] | None = None) -> str:
    """Prefer owned team over context my_team_name for trade UI/actions."""
    del session
    owned = owned_team_for_user(context)
    if owned:
        return owned
    if isinstance(context, dict):
        return str(context.get("my_team_name") or "").strip()
    return ""
