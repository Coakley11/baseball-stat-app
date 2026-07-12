"""Canonical lineup scope fingerprint — account, workspace, league, team, week."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from fantasy_league_identity import resolve_canonical_league_id
from fantasy_workspace_team_identity import overlay_workspace_team_on_context, session_account_identity

LINEUP_SCOPE_TRACKING_KEY = "_lineup_active_scope_fingerprint"
ROSTER_STATS_SCOPE_KEY = "_fantasy_roster_stats_scope_fingerprint"
LINEUP_IDENTITY_SYNC_ERROR = (
    "Your account and lineup team are temporarily out of sync. "
    "Refresh the correct team context before saving."
)

_LEGACY_CANON_RE = re.compile(r"^weekly_lineup_canon_\d+$")
_LEGACY_BOARD_NONCE_RE = re.compile(r"^weekly_lineup_board_nonce_\d+$")
_LEGACY_BOARD_COMPONENT_RE = re.compile(r"^weekly_lineup_circle_board_\d+")
_LEGACY_SCOPE_PREFIXES = (
    "weekly_lineup_canon_",
    "weekly_lineup_board_nonce_",
    "weekly_lineup_circle_board_",
)


@dataclass(frozen=True)
class LineupScope:
    fingerprint: str
    user_id: str
    owned_workspace_id: str
    active_workspace_id: str
    league_id: str
    owned_team: str
    page_lineup_team: str
    week: int

    @property
    def assignments_key(self) -> str:
        return f"{self.fingerprint}|assignments"

    @property
    def board_nonce_key(self) -> str:
        return f"{self.fingerprint}|board_nonce"

    @property
    def component_key_base(self) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_|]", "_", self.fingerprint)
        return f"weekly_lineup_board|{safe}"

    @property
    def persisted_record_key(self) -> str:
        return f"{self.owned_team}|week_{int(self.week)}"

    @property
    def stats_cache_scope(self) -> str:
        return f"roster_stats|{self.user_id}|{self.owned_workspace_id}|{self.league_id}|{self.owned_team}"


def build_lineup_scope_fingerprint(
    *,
    user_id: str,
    owned_workspace_id: str,
    league_id: str,
    team_key: str,
    week: int,
) -> str:
    uid = str(user_id or "").strip() or "anon"
    ws = str(owned_workspace_id or "").strip() or "default"
    league = str(league_id or "").strip() or "no_league"
    team = str(team_key or "").strip() or "no_team"
    return f"weekly_lineup|{uid}|{ws}|{league}|{team}|week_{int(week)}"


def resolve_lineup_scope(
    session: dict[str, Any],
    context: dict[str, Any] | None,
    *,
    week: int,
    page_lineup_team: str = "",
) -> LineupScope | None:
    if not isinstance(context, dict):
        return None

    merged = overlay_workspace_team_on_context(
        session,
        context,
        trace_phase="lineup_scope",
    )
    if not isinstance(merged, dict):
        return None

    uid, _external, owned_ws, email, _local = session_account_identity(session)
    active_ws = str(session.get("_suite_active_workspace_id") or owned_ws or "").strip()
    league_id = str(resolve_canonical_league_id(merged) or "").strip()
    owned_team = str(merged.get("my_team_name") or "").strip()
    page_team = str(page_lineup_team or "").strip()

    fingerprint = build_lineup_scope_fingerprint(
        user_id=uid,
        owned_workspace_id=owned_ws,
        league_id=league_id,
        team_key=owned_team,
        week=int(week),
    )
    return LineupScope(
        fingerprint=fingerprint,
        user_id=uid,
        owned_workspace_id=owned_ws,
        active_workspace_id=active_ws,
        league_id=league_id,
        owned_team=owned_team,
        page_lineup_team=page_team,
        week=int(week),
    )


def resolve_canonical_lineup_team(
    session: dict[str, Any],
    context: dict[str, Any] | None,
    *,
    page_lineup_team: str = "",
) -> str:
    """Owned team from team_ownership — never a stale page/archive team."""
    scope = resolve_lineup_scope(session, context, week=1, page_lineup_team=page_lineup_team)
    if scope and scope.owned_team:
        return scope.owned_team
    if isinstance(context, dict):
        return str(context.get("my_team_name") or "").strip()
    return str(page_lineup_team or "").strip()


def lineup_identity_in_sync(scope: LineupScope | None) -> bool:
    if scope is None or not scope.owned_team:
        return False
    if scope.page_lineup_team and scope.page_lineup_team != scope.owned_team:
        return False
    return True


def assert_lineup_write_identity(scope: LineupScope | None) -> tuple[bool, str]:
    if scope is None:
        return False, "No active league context."
    if not scope.user_id:
        return False, "Sign in to save lineup changes."
    if not scope.owned_team:
        return False, "Your account does not own a team in this league."
    if not lineup_identity_in_sync(scope):
        return False, LINEUP_IDENTITY_SYNC_ERROR
    return True, ""


def _pop_legacy_lineup_session_keys(session: dict[str, Any]) -> None:
    for key in list(session.keys()):
        sk = str(key)
        if _LEGACY_CANON_RE.match(sk) or _LEGACY_BOARD_NONCE_RE.match(sk):
            session.pop(key, None)
            continue
        if sk.startswith(_LEGACY_SCOPE_PREFIXES):
            session.pop(key, None)


def apply_lineup_scope_change(session: dict[str, Any], scope: LineupScope) -> bool:
    """Invalidate prior unscoped or cross-account session state when scope changes."""
    prev = str(session.get(LINEUP_SCOPE_TRACKING_KEY) or "").strip()
    changed = prev != scope.fingerprint
    if not changed:
        return False

    _pop_legacy_lineup_session_keys(session)
    for key in list(session.keys()):
        sk = str(key)
        if sk.startswith("weekly_lineup|") and not sk.startswith(scope.fingerprint):
            session.pop(key, None)

    session.pop("fantasy_current_roster_stats", None)
    session.pop("fantasy_current_standings", None)
    session.pop(ROSTER_STATS_SCOPE_KEY, None)
    try:
        from fantasy_lineup_perf import invalidate_lineup_page_caches

        invalidate_lineup_page_caches(session)
    except ImportError:
        pass
    try:
        from fantasy_trade_roster_sync import invalidate_fantasy_roster_view_caches

        invalidate_fantasy_roster_view_caches(session)
    except ImportError:
        pass

    session[LINEUP_SCOPE_TRACKING_KEY] = scope.fingerprint
    return True


def roster_stats_cache_valid(session: dict[str, Any], scope: LineupScope) -> bool:
    cached_scope = str(session.get(ROSTER_STATS_SCOPE_KEY) or "").strip()
    return bool(cached_scope) and cached_scope == scope.stats_cache_scope


def stamp_roster_stats_cache_scope(session: dict[str, Any], scope: LineupScope) -> None:
    session[ROSTER_STATS_SCOPE_KEY] = scope.stats_cache_scope


def render_lineup_identity_diagnostics_from_session(
    st: Any,
    session: dict[str, Any],
    scope: LineupScope | None,
) -> None:
    if scope is None:
        st.json({"error": "no_scope"})
        return
    _uid, _ext, _owned, email, _local = session_account_identity(session)
    st.json(
        {
            "auth_email": email,
            "auth_user_id": scope.user_id,
            "owned_workspace": scope.owned_workspace_id,
            "active_workspace": scope.active_workspace_id,
            "canonical_league_id": scope.league_id,
            "ownership_resolved_team": scope.owned_team,
            "page_lineup_team": scope.page_lineup_team,
            "final_active_lineup_team": scope.owned_team,
            "assignment_scope_key": scope.assignments_key,
            "stats_cache_scope": scope.stats_cache_scope,
            "persisted_record_key": scope.persisted_record_key,
            "scope_fingerprint": scope.fingerprint,
            "identity_in_sync": lineup_identity_in_sync(scope),
        }
    )
