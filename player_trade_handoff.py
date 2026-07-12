"""Player Action → Trade Center handoff (active shared league only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from fantasy_trade_builder_state import ANY_TRADE_PARTNER, queue_pending_builder_update
from player_trade_constants import TRADE_ACTION_ACQUIRE, TRADE_ACTION_TRADE_AWAY

TRADE_CENTER_HANDOFF_KEY = "_trade_center_HANDOFF_KEY".replace("_HANDOFF_KEY", "_handoff")  # keep stable key below
TRADE_CENTER_HANDOFF_KEY = "_trade_center_handoff"
HANDOFF_DIAG_SUFFIX = "builder_handoff_diag"

VALIDATION_OK = "ok"
VALIDATION_STALE = "stale"
VALIDATION_TRANSIENT = "transient"


def handoff_diag_key(scope_key: str) -> str:
    return f"{scope_key}|{HANDOFF_DIAG_SUFFIX}"


def _resolve_active_league_ids(session: dict[str, Any]) -> tuple[str, str]:
    """Return (league_context_id, canonical_league_id) for the active shared league."""
    try:
        from fantasy_league_context import get_active_league_context
        from fantasy_league_identity import resolve_canonical_league_id
    except ImportError:
        return "", ""

    active = get_active_league_context(session) or {}
    context_id = str(active.get("league_context_id") or "").strip()
    canonical_id = str(resolve_canonical_league_id(active) or "").strip()
    return context_id, canonical_id

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
        "plan_add_enabled": False,
        "plan_drop_enabled": False,
        "is_unrostered": False,
        "is_my_player": False,
        "is_opponent_player": False,
        "my_team": "",
        "owner_team": "",
        "league_label": "",
        "league_context_id": "",
        "trade_away_help": "",
        "acquire_help": "",
        "plan_add_help": "",
        "plan_drop_help": "",
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
        out["plan_add_enabled"] = True
        out["block_message"] = (
            f"{display} is not rostered in the active shared league. Use Waiver Wire/Add-Drop instead."
        )
        out["waiver_message"] = f"This player is not currently rostered in {league_label}."
        out["plan_add_help"] = f"Plan Add for {display} in {league_label}."
        out["trade_away_help"] = out["block_message"]
        out["acquire_help"] = f"{display} is not rostered in {league_label}. Use Plan Add in Waiver Wire."
        out["plan_drop_help"] = f"{display} is not on your roster. Plan Drop is unavailable."
        return out

    owner_team = str(owner_rec.get("owner_team") or "").strip()
    out["owner_team"] = owner_team
    if owner_team == my_team:
        out["is_my_player"] = True
        out["trade_away_enabled"] = True
        out["plan_drop_enabled"] = True
        out["trade_away_help"] = f"This player is on {my_team}, your team in {league_label}."
        out["acquire_help"] = f"{display} is on your roster. Use Trade Away instead."
        out["plan_add_help"] = f"{display} is already on {my_team}. Plan Add is unavailable."
        out["plan_drop_help"] = f"Plan Drop for {display} from {my_team} in {league_label}."
        return out

    out["is_opponent_player"] = True
    out["acquire_enabled"] = True
    out["acquire_help"] = f"This player is on {owner_team} in {league_label}."
    out["trade_away_help"] = f"{display} belongs to {owner_team}. Use Acquire instead."
    out["plan_add_help"] = f"{display} is rostered by {owner_team}. Use Acquire in Trade Center instead."
    out["plan_drop_help"] = f"{display} is rostered by {owner_team}. Plan Drop is unavailable."
    return out


def build_trade_center_handoff_payload(
    *,
    mode: str,
    player_name: str,
    league_context_id: str,
    canonical_league_id: str = "",
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
        "canonical_league_id": str(canonical_league_id or "").strip(),
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

    _, canonical_league_id = _resolve_active_league_ids(session)

    handoff = build_trade_center_handoff_payload(
        mode=mode_norm,
        player_name=display,
        league_context_id=league_context_id,
        canonical_league_id=canonical_league_id,
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


def _validate_league_identity(
    handoff: dict[str, Any],
    session: dict[str, Any],
    *,
    active_context_id: str,
    active_canonical_league_id: str,
) -> tuple[bool, str, str]:
    """Compare context IDs to context IDs and canonical IDs to canonical IDs only."""
    handoff_context_id = str(handoff.get("league_context_id") or "").strip()
    handoff_canonical_id = str(handoff.get("canonical_league_id") or "").strip()
    pending_context_id = ""
    try:
        from fantasy_league_context import PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY

        pending_context_id = str(session.get(PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY) or "").strip()
    except ImportError:
        pending_context_id = ""

    if handoff_context_id and not active_context_id:
        if pending_context_id == handoff_context_id:
            return False, "Active league context activation is pending.", VALIDATION_TRANSIENT
        return False, "Active league context is not ready yet.", VALIDATION_TRANSIENT

    if handoff_context_id and active_context_id and handoff_context_id != active_context_id:
        if pending_context_id == handoff_context_id:
            return False, "Active league context activation is pending.", VALIDATION_TRANSIENT
        return False, "Trade target league no longer matches the active shared league.", VALIDATION_STALE

    if (
        handoff_canonical_id
        and active_canonical_league_id
        and handoff_canonical_id != active_canonical_league_id
    ):
        return False, "Trade target canonical league no longer matches the active shared league.", VALIDATION_STALE

    return True, "", VALIDATION_OK


def validate_trade_center_handoff(
    handoff: dict[str, Any],
    session: dict[str, Any],
    *,
    roster_stats: pd.DataFrame | None,
    my_team: str,
    other_teams: list[str],
    active_context_id: str = "",
    active_canonical_league_id: str = "",
) -> tuple[dict[str, Any] | None, str, str]:
    """Reject stale or cross-league handoffs before builder population."""
    try:
        from fantasy_league_context import get_active_league_context, normalize_player_key
        from fantasy_league_team_ownership import owned_team_for_user
    except ImportError:
        return None, "Trade Center handoff validation unavailable.", VALIDATION_STALE

    if not active_context_id or not active_canonical_league_id:
        resolved_context_id, resolved_canonical_id = _resolve_active_league_ids(session)
        active_context_id = active_context_id or resolved_context_id
        active_canonical_league_id = active_canonical_league_id or resolved_canonical_id

    ok, err, status = _validate_league_identity(
        handoff,
        session,
        active_context_id=active_context_id,
        active_canonical_league_id=active_canonical_league_id,
    )
    if not ok:
        return None, err, status

    active = get_active_league_context(session) or {}
    owned_team = owned_team_for_user(active) or str(active.get("my_team_name") or "").strip()
    if my_team and owned_team and my_team != owned_team:
        return None, "Trade target could not be loaded because your owned team changed.", VALIDATION_STALE

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
            return (
                None,
                f"{name} is no longer on {owned_team} in the active league. The trade candidate was not loaded.",
                VALIDATION_STALE,
            )
        validated_give.append(canonical)

    validated_receive: list[str] = []
    partner = str(handoff.get("trade_partner") or handoff.get("other_team") or "").strip()
    for name in receive:
        canonical = _canonical_roster_player_name(roster_stats, name) or name
        key = normalize_player_key(canonical)
        owner = (ownership.get(key) or {}).get("owner_team") if isinstance(ownership, dict) else None
        owner_team = str(owner or "").strip()
        if not owner_team or owner_team == owned_team:
            return (
                None,
                f"{name} is no longer rostered by another team in the active league. The trade target was not loaded.",
                VALIDATION_STALE,
            )
        if partner and partner != ANY_TRADE_PARTNER and owner_team != partner:
            return (
                None,
                f"{name} is no longer rostered by {partner} in the active league. The trade target was not loaded.",
                VALIDATION_STALE,
            )
        if owner_team not in other_teams and owner_team != ANY_TRADE_PARTNER:
            return None, f"{name} is no longer rostered by an opponent in the active league.", VALIDATION_STALE
        validated_receive.append(canonical)
        if not partner or partner == ANY_TRADE_PARTNER:
            partner = owner_team

    payload = dict(handoff)
    payload["give_players"] = validated_give
    payload["receive_players"] = validated_receive
    payload["get_players"] = validated_receive
    payload["other_team"] = partner if partner != ANY_TRADE_PARTNER else ""
    payload["trade_partner"] = partner or ANY_TRADE_PARTNER
    return payload, "", VALIDATION_OK


def _record_handoff_diag(
    session: dict[str, Any],
    scope_key: str,
    *,
    handoff: dict[str, Any] | None,
    active_context_id: str,
    active_canonical_league_id: str,
    validation_result: str,
    rejection_reason: str = "",
    pending_update_queued: bool = False,
    pending_get_players: list[str] | None = None,
    pending_give_players: list[str] | None = None,
    receive_widget_after: list[str] | None = None,
    partner_widget_after: str = "",
    give_widget_after: list[str] | None = None,
) -> None:
    session[handoff_diag_key(scope_key)] = {
        "handoff_present": isinstance(handoff, dict),
        "handoff_context_id": str((handoff or {}).get("league_context_id") or ""),
        "handoff_canonical_league_id": str((handoff or {}).get("canonical_league_id") or ""),
        "active_context_id": str(active_context_id or ""),
        "active_canonical_league_id": str(active_canonical_league_id or ""),
        "validation_result": str(validation_result or ""),
        "rejection_reason": str(rejection_reason or ""),
        "pending_update_queued": bool(pending_update_queued),
        "pending_get_players": list(pending_get_players or []),
        "pending_give_players": list(pending_give_players or []),
        "receive_widget_after": list(receive_widget_after or []),
        "partner_widget_after": str(partner_widget_after or ""),
        "give_widget_after": list(give_widget_after or []),
    }


def consume_trade_center_handoff_into_pending(
    session: dict[str, Any],
    scope_key: str,
    *,
    roster_stats: pd.DataFrame | None,
    my_team: str,
    other_teams: list[str],
    active_context_id: str = "",
    active_canonical_league_id: str = "",
) -> bool:
    """Consume `_trade_center_handoff` exactly once after scope/schema are ready."""
    handoff = session.get(TRADE_CENTER_HANDOFF_KEY)
    if not isinstance(handoff, dict):
        _record_handoff_diag(
            session,
            scope_key,
            handoff=None,
            active_context_id=active_context_id,
            active_canonical_league_id=active_canonical_league_id,
            validation_result="absent",
        )
        return False

    if not active_context_id or not active_canonical_league_id:
        resolved_context_id, resolved_canonical_id = _resolve_active_league_ids(session)
        active_context_id = active_context_id or resolved_context_id
        active_canonical_league_id = active_canonical_league_id or resolved_canonical_id

    validated, err, status = validate_trade_center_handoff(
        handoff,
        session,
        roster_stats=roster_stats,
        my_team=my_team,
        other_teams=other_teams,
        active_context_id=active_context_id,
        active_canonical_league_id=active_canonical_league_id,
    )
    if validated is None:
        _record_handoff_diag(
            session,
            scope_key,
            handoff=handoff,
            active_context_id=active_context_id,
            active_canonical_league_id=active_canonical_league_id,
            validation_result=status,
            rejection_reason=err or "Trade target could not be loaded.",
        )
        session[f"{scope_key}|builder_flash"] = err or "Trade target could not be loaded."
        session[f"{scope_key}|builder_handoff_meta"] = {
            "present": True,
            "consumed": False,
            "rejected": status == VALIDATION_STALE,
            "transient": status == VALIDATION_TRANSIENT,
        }
        if status == VALIDATION_STALE:
            session.pop(TRADE_CENTER_HANDOFF_KEY, None)
        return False

    queue_pending_builder_update(session, scope_key, validated)
    session.pop(TRADE_CENTER_HANDOFF_KEY, None)
    session[f"{scope_key}|builder_handoff_meta"] = {"present": True, "consumed": True}
    _record_handoff_diag(
        session,
        scope_key,
        handoff=validated,
        active_context_id=active_context_id,
        active_canonical_league_id=active_canonical_league_id,
        validation_result=VALIDATION_OK,
        pending_update_queued=True,
        pending_get_players=list(validated.get("get_players") or validated.get("receive_players") or []),
        pending_give_players=list(validated.get("give_players") or []),
    )
    flash_message = str(validated.get("flash_message") or "").strip()
    if flash_message:
        session[f"{scope_key}|builder_flash"] = flash_message
    return True
