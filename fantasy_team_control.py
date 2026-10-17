"""Who may manage a fantasy team right now — owner, commissioner proxy, or nobody.

* A team with a firm claim is managed only by its owner. The commissioner never
  silently overrides a claimed manager.
* An unclaimed team (no claim, or only a Live Draft reservation not yet accepted) may be
  managed by the commissioner as an explicit proxy: "Commissioner acting for Team X".
  Proxy control ends the moment a real user claims the team.
* Identity: a signed-in account when sign-in is enabled. With sign-in deliberately
  disabled (local install), the existing local account id (``local:<user>``) — the same
  identity league claims already use — so local lineup saves work without an account.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MODE_OWNER = "owner"
MODE_COMMISSIONER_PROXY = "commissioner_proxy"
MODE_NONE = "none"


def auth_required() -> bool:
    """True when this deployment uses real sign-in (hosted)."""
    try:
        from suite_auth import is_auth_enabled

        return bool(is_auth_enabled())
    except Exception:
        return False


def current_user_id(session: dict[str, Any] | None) -> str:
    """Signed-in account id; on a no-auth local install, the local account id."""
    uid = ""
    # Any mapping: in the running app this is Streamlit's SessionStateProxy, which is not a dict.
    if isinstance(session, Mapping):
        uid = str(session.get("_suite_auth_user_id") or session.get("_suite_cloud_user_id") or "").strip()
    if uid:
        return uid
    if auth_required():
        return ""  # hosted: sign in first
    try:
        from suite_user import get_account_user_id

        return str(get_account_user_id() or "").strip()
    except Exception:
        return ""


def _is_commissioner(session: dict[str, Any] | None, context: dict[str, Any], uid: str) -> bool:
    ctx_type = str(context.get("context_type") or "").strip()
    if ctx_type and ctx_type != "real_league":
        return True  # mock / simulator leagues are single-manager
    if not uid:
        return False
    try:
        from fantasy_league_invites import is_league_commissioner

        return bool(is_league_commissioner(context, uid))
    except ImportError:
        return False


@dataclass(frozen=True)
class TeamControl:
    team: str
    mode: str
    user_id: str
    is_commissioner: bool
    owner_display: str = ""
    reason: str = ""

    @property
    def can_manage(self) -> bool:
        return self.mode in (MODE_OWNER, MODE_COMMISSIONER_PROXY)

    @property
    def is_proxy(self) -> bool:
        return self.mode == MODE_COMMISSIONER_PROXY

    def banner(self) -> str:
        return f"Commissioner acting for {self.team}" if self.is_proxy else ""

    def actor_record(self) -> dict[str, Any]:
        return {"user_id": self.user_id, "acting_as": self.mode, "team": self.team}


def resolve_team_control(session: dict[str, Any] | None, context: dict[str, Any] | None, team: str) -> TeamControl:
    team = str(team or "").strip()
    if not isinstance(context, dict) or not team:
        return TeamControl(team, MODE_NONE, "", False, reason="No league or team.")
    uid = current_user_id(session)
    is_comm = _is_commissioner(session, context, uid)
    try:
        from fantasy_league_team_ownership import (
            account_user_ids_match,
            get_team_ownership,
            owner_display_for_team,
            ownership_is_firm_claim,
            ownership_is_provisional,
        )
    except ImportError:
        return TeamControl(team, MODE_OWNER, uid, is_comm)
    ownership = get_team_ownership(context)
    record = ownership.get(team) or {}
    if ownership_is_provisional(record):
        # Reserved for a known invitee (e.g. their Live Draft seat): theirs, not the commissioner's.
        invitee = str(record.get("reserved_for_email") or record.get("display_name") or "an invited manager")
        return TeamControl(team, MODE_NONE, uid, is_comm, reason=f"{team} is reserved for {invitee} until they accept.")
    if ownership_is_firm_claim(record):
        if uid and account_user_ids_match(str(record.get("user_id") or ""), uid):
            return TeamControl(team, MODE_OWNER, uid, is_comm)
        return TeamControl(
            team, MODE_NONE, uid, is_comm,
            owner_display=owner_display_for_team(context, team),
            reason=f"{team} is managed by {owner_display_for_team(context, team)}.",
        )
    # Unclaimed. Leagues that never used ownership (mock/simulator) keep "my team" as owner.
    if not any(ownership_is_firm_claim(r) for r in ownership.values()) and team == str(context.get("my_team_name") or "").strip():
        if not auth_required() or uid:
            return TeamControl(team, MODE_OWNER, uid, is_comm)
    if is_comm:
        return TeamControl(team, MODE_COMMISSIONER_PROXY, uid, True)
    return TeamControl(team, MODE_NONE, uid, False, reason=f"{team} is unclaimed; only the commissioner can manage it.")


def manageable_teams(session: dict[str, Any] | None, context: dict[str, Any] | None) -> list[TeamControl]:
    """Every team this user may manage: their own first, then commissioner-proxy teams."""
    if not isinstance(context, dict):
        return []
    teams = sorted(str(t) for t in (context.get("league_rosters") or {}) if str(t).strip())
    controls = [resolve_team_control(session, context, t) for t in teams]
    owned = [c for c in controls if c.mode == MODE_OWNER]
    proxy = [c for c in controls if c.mode == MODE_COMMISSIONER_PROXY]
    return owned + proxy


def record_league_action(context: dict[str, Any], *, control: TeamControl, action: str, detail: dict[str, Any] | None = None) -> None:
    """Append an in-league activity entry naming who acted and whether as commissioner proxy."""
    from datetime import datetime, timezone

    workflow = context.setdefault("workflow", {})
    if not isinstance(workflow, dict):
        return
    log = list(workflow.get("league_activity") or [])
    entry = {
        "team_name": control.team,
        "action": action,
        "actor_user_id": control.user_id,
        "acting_as": control.mode,
        "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    if control.is_proxy:
        entry["note"] = f"Commissioner acting for {control.team}"
    entry.update(detail or {})
    log.append(entry)
    workflow["league_activity"] = log[-200:]
