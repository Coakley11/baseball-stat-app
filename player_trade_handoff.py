"""Player Action → Trade Center handoff (active shared league only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from fantasy_trade_builder_state import ANY_TRADE_PARTNER, queue_pending_builder_update
from player_trade_constants import TRADE_ACTION_ACQUIRE, TRADE_ACTION_TRADE_AWAY

TRADE_CENTER_HANDOFF_KEY = "_trade_center_handoff"


def _display_base(name: str) -> str:
    return str(name or "").split(" (")[0].strip()


def _canonical_roster_player_name(roster_stats: pd.DataFrame | None, player_name: str) -> str | None:
    try:
        from fantasy_league_context import normalize_player_key
    except ImportError:
        normalize_player_key = lambda n: str(n or "").strip().lower()  # type: ignore[misc, assignment]

    target_key = normalize_player_key(_display_base(player_name))
    if not target_key or roster_stats is None or roster_stats.empty or "Player" not in roster_stats.columns:
        return None
    for _, row in roster_stats.iterrows():
        pname = str(row.get("Player") or "").strip()
        if pname and normalize_player_key(pname) == target_key:
            return pname
    return None


def resolve_active_league_player_trade_eligibility(
    session: dict[str, Any],
    player_name: str,
) -> dict[str, Any]:
    """Ownership-relative Trade Away / Acquire eligibility for the active shared league only."""
    display = _display_base(player_name)
    out: dict[str, Any] = {
        "player_name": display,
        "eligible_league": False,
        "trade_away_enabled": False,
        "acquire_enabled": False,
        "waiver_enabled": False,
        "is_unrostered": False,
        "is_my_player": False,
        "is_opponent_player": False,
        "my_team": "",
        "owner_team": "",
        "league_label": "",
        "league_context_id": "",
        "trade_away_help": "",
        "acquire_help": "",
        "block_message": "",
        "waiver_message": "",
    }
    if not display:
        out["block_message"] = "Pick a player first."
        return out

    try:
        from fantasy_league_context import get_active_league_context, normalize_player_key
        from fantasy_league_team_ownership import owned_team_for_user, trades_enabled
    except ImportError:
        out["block_message"] = "Trade actions require an active shared league."
        return out

    active = get_active_league_context(session)
    if not active:
        out["block_message"] = "Set an active shared league before trading."
        return out

    league_label = str(active.get("display_name") or active.get("league_name") or "active league").strip()
    league_context_id = str(active.get("league_context_id") or "").strip()
    out["league_label"] = league_label
    out["league_context_id"] = league_context_id

    ok, msg = trades_enabled(active, session)
    if not ok:
        out["block_message"] = msg or "Trade actions require an active shared league with multiple claimed owners."
        return out

    out["eligible_league"] = True
    my_team = owned_team_for_user(active) or str(active.get("my_team_name") or "").strip()
    out["my_team"] = my_team
    if not my_team:
        out["block_message"] = "Claim your team in this league before trading."
        return out

    target_key = normalize_player_key(display)
    ownership = active.get("ownership_map") or {}
    owner_rec = ownership.get(target_key) if isinstance(ownership, dict) else None
    if not isinstance(owner_rec, dict):
        out["is_unrostered"] = True
        out["waiver_enabled"] = True
        out["block_message"] = (
            f"{display} is not rostered in the active shared league. Use Waiver Wire/Add-Drop instead."
        )
        out["waiver_message"] = f"This player is not currently rostered in {league_label}."
        out["trade_away_help"] = out["block_message"]
        out["acquire_help"] = out["block_message"]
        return out

    owner_team = str(owner_rec.get("owner_team") or "").strip()
    out["owner_team"] = owner_team
    if owner_team == my_team:
        out["is_my_player"] = True
        out["trade_away_enabled"] = True
        out["trade_away_help"] = f"This player is on {my_team}, your team in {league_label}."
        out["acquire_help"] = f"{display} is on your roster. Use Trade Away instead."
        return out

    out["is_opponent_player"] = True
    out["acquire_enabled"] = True
    out["acquire_help"] = f"This player is on {owner_team} in {league_label}."
    out["trade_away_help"] = f"{display} belongs to {owner_team}. Use Acquire instead."
    return out


def build_trade_center_handoff_payload(
    *,
    mode: str,
    player_name: str,
    league_context_id: str,
    my_team: str,
    owner_team: str,
) -> dict[str, Any]:
    display = _display_base(player_name)
    mode_norm = str(mode or "").strip().lower()
    give_players: list[str] = []
    receive_players: list[str] = []
    other_team = ""
    trade_partner = ANY_TRADE_PARTNER
    source = "player_action_trade"
    flash_message = ""

    if mode_norm in (TRADE_ACTION_TRADE_AWAY, "trade_away"):
        give_players = [display]
        trade_partner = ANY_TRADE_PARTNER
        source = "player_action_trade_away"
        flash_message = f"{display} loaded as a trade-away candidate from {my_team}."
    elif mode_norm in (TRADE_ACTION_ACQUIRE, "acquire"):
        receive_players = [display]
        other_team = str(owner_team or "").strip()
        trade_partner = other_team or ANY_TRADE_PARTNER
        source = "player_action_acquire"
        if other_team:
            flash_message = f"{display} loaded as an acquire target from {other_team}."
        else:
            flash_message = f"{display} loaded as an acquire target."

    return {
        "action": "use",
        "source": source,
        "league_context_id": str(league_context_id or "").strip(),
        "give_players": give_players,
        "receive_players": receive_players,
        "other_team": other_team,
        "trade_partner": trade_partner,
        "auto_analyze": False,
        "flash_message": flash_message,
    }


def queue_player_action_trade_handoff(
    session: dict[str, Any],
    *,
    player_name: str,
    mode: str,
) -> tuple[bool, str]:
    """Validate active-league ownership and queue durable Trade Center handoff."""
    eligibility = resolve_active_league_player_trade_eligibility(session, player_name)
    display = str(eligibility.get("player_name") or "").strip()
    mode_norm = str(mode or "").strip().lower()

    if mode_norm in (TRADE_ACTION_TRADE_AWAY, "trade_away"):
        if not eligibility.get("trade_away_enabled"):
            return False, str(eligibility.get("trade_away_help") or eligibility.get("block_message") or "Trade Away unavailable.")
    elif mode_norm in (TRADE_ACTION_ACQUIRE, "acquire"):
        if not eligibility.get("acquire_enabled"):
            return False, str(eligibility.get("acquire_help") or eligibility.get("block_message") or "Acquire unavailable.")
    else:
        return False, "Unknown trade action."

    league_context_id = str(eligibility.get("league_context_id") or "").strip()
    if league_context_id:
        try:
            from fantasy_league_context import schedule_league_context_activation

            schedule_league_context_activation(session, league_context_id)
        except ImportError:
            pass

    handoff = build_trade_center_handoff_payload(
        mode=mode_norm,
        player_name=display,
        league_context_id=league_context_id,
        my_team=str(eligibility.get("my_team") or ""),
        owner_team=str(eligibility.get("owner_team") or ""),
    )
    session[TRADE_CENTER_HANDOFF_KEY] = handoff
    session["_lineup_focus_trade_center"] = True
    try:
        from fantasy_league_context import LINEUP_ASSISTANT_PAGE

        session["_navigate_to_page"] = LINEUP_ASSISTANT_PAGE
        session["_skip_page_restore_for"] = LINEUP_ASSISTANT_PAGE
    except ImportError:
        session["_navigate_to_page"] = "Fantasy Lineup Assistant"
        session["_skip_page_restore_for"] = "Fantasy Lineup Assistant"

    try:
        from fantasy_trade_ideas import TRADE_CENTER_INTERNAL_TAB_KEY, TRADE_CENTER_INTERNAL_WIDGET_KEY

        session[TRADE_CENTER_INTERNAL_TAB_KEY] = "Build & Analyze"
        session[TRADE_CENTER_INTERNAL_WIDGET_KEY] = "Build & Analyze"
    except ImportError:
        pass

    label = str(eligibility.get("league_label") or "active league")
    action_label = "Trade Away" if mode_norm in (TRADE_ACTION_TRADE_AWAY, "trade_away") else "Acquire"
    return True, f"{action_label} for {display} in {label}. Opening Fantasy Lineup Assistant → Trade Center."


def validate_trade_center_handoff(
    handoff: dict[str, Any],
    session: dict[str, Any],
    *,
    roster_stats: pd.DataFrame | None,
    my_team: str,
    other_teams: list[str],
) -> tuple[dict[str, Any] | None, str]:
    """Reject stale or cross-league handoffs before builder population."""
    try:
        from fantasy_league_context import get_active_league_context, normalize_player_key
        from fantasy_league_team_ownership import owned_team_for_user
    except ImportError:
        return None, "Trade Center handoff validation unavailable."

    active = get_active_league_context(session) or {}
    active_id = str(active.get("league_context_id") or "").strip()
    handoff_id = str(handoff.get("league_context_id") or "").strip()
    if handoff_id and active_id and handoff_id != active_id:
        return None, "Trade target league no longer matches the active shared league."

    owned_team = owned_team_for_user(active) or str(active.get("my_team_name") or "").strip()
    if my_team and owned_team and my_team != owned_team:
        return None, "Trade target could not be loaded because your owned team changed."

    give = [str(p).strip() for p in handoff.get("give_players") or [] if str(p).strip()]
    receive = [str(p).strip() for p in handoff.get("receive_players") or [] if str(p).strip()]
    ownership = active.get("ownership_map") or {}

    validated_give: list[str] = []
    for name in give:
        canonical = _canonical_roster_player_name(roster_stats, name) or name
        key = normalize_player_key(canonical)
        owner = (ownership.get(key) or {}).get("owner_team") if isinstance(ownership, dict) else None
        owner_team = str(owner or "").strip()
        if owner_team != owned_team:
            return None, f"{name} is no longer on {owned_team} in the active league. The trade candidate was not loaded."
        validated_give.append(canonical)

    validated_receive: list[str] = []
    partner = str(handoff.get("trade_partner") or handoff.get("other_team") or "").strip()
    for name in receive:
        canonical = _canonical_roster_player_name(roster_stats, name) or name
        key = normalize_player_key(canonical)
        owner = (ownership.get(key) or {}).get("owner_team") if isinstance(ownership, dict) else None
        owner_team = str(owner or "").strip()
        if not owner_team or owner_team == owned_team:
            return None, f"{name} is no longer rostered by another team in the active league. The trade target was not loaded."
        if partner and partner != ANY_TRADE_PARTNER and owner_team != partner:
            return None, (
                f"{name} is no longer rostered by {partner} in the active league. The trade target was not loaded."
            )
        if owner_team not in other_teams and owner_team != ANY_TRADE_PARTNER:
            return None, f"{name} is no longer rostered by an opponent in the active league."
        validated_receive.append(canonical)
        if not partner or partner == ANY_TRADE_PARTNER:
            partner = owner_team

    payload = dict(handoff)
    payload["give_players"] = validated_give
    payload["receive_players"] = validated_receive
    payload["get_players"] = validated_receive
    payload["other_team"] = partner if partner != ANY_TRADE_PARTNER else ""
    payload["trade_partner"] = partner or ANY_TRADE_PARTNER
    return payload, ""


def consume_trade_center_handoff_into_pending(
    session: dict[str, Any],
    scope_key: str,
    *,
    roster_stats: pd.DataFrame | None,
    my_team: str,
    other_teams: list[str],
    league_context_id: str = "",
) -> bool:
    """Consume `_trade_center_handoff` exactly once after scope/schema are ready."""
    handoff = session.pop(TRADE_CENTER_HANDOFF_KEY, None)
    if not isinstance(handoff, dict):
        return False

    validated, err = validate_trade_center_handoff(
        handoff,
        session,
        roster_stats=roster_stats,
        my_team=my_team,
        other_teams=other_teams,
    )
    if validated is None:
        session[f"{scope_key}|builder_flash"] = err or "Trade target could not be loaded."
        session[f"{scope_key}|builder_handoff_meta"] = {"present": True, "consumed": False, "rejected": True}
        return False

    if league_context_id:
        handoff_id = str(validated.get("league_context_id") or "").strip()
        if handoff_id and handoff_id != league_context_id:
            session[f"{scope_key}|builder_flash"] = (
                "Trade target league no longer matches the active shared league."
            )
            session[f"{scope_key}|builder_handoff_meta"] = {"present": True, "consumed": False, "rejected": True}
            return False

    queue_pending_builder_update(session, scope_key, validated)
    session[f"{scope_key}|builder_handoff_meta"] = {"present": True, "consumed": True}
    try:
        from fantasy_trade_ideas import TRADE_CENTER_INTERNAL_TAB_KEY, TRADE_CENTER_INTERNAL_WIDGET_KEY

        session[TRADE_CENTER_INTERNAL_TAB_KEY] = "Build & Analyze"
        session[TRADE_CENTER_INTERNAL_WIDGET_KEY] = "Build & Analyze"
    except ImportError:
        pass
    return True
