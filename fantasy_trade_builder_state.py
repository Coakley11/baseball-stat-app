"""Scoped Trade Center builder state — logical selections vs Streamlit widget keys."""

from __future__ import annotations

from typing import Any

import pandas as pd

from fantasy_trade_ideas import (
    LINEUP_TRADE_IDEAS_DIAG_KEY,
    LINEUP_TRADE_IDEAS_RESULTS_KEY,
    resolve_player_owner_team,
)

ANY_TRADE_PARTNER = "Any team"
PENDING_BUILDER_SUFFIX = "pending_builder_update"


def pending_builder_key(scope_key: str) -> str:
    return f"{scope_key}|{PENDING_BUILDER_SUFFIX}"


def give_widget_key(scope_key: str) -> str:
    return f"{scope_key}|give_widget"


def receive_widget_key(scope_key: str) -> str:
    return f"{scope_key}|receive_widget"


def partner_widget_key(scope_key: str) -> str:
    return f"{scope_key}|partner_widget"


def builder_widget_keys(scope_key: str) -> dict[str, str]:
    return {
        "give": give_widget_key(scope_key),
        "receive": receive_widget_key(scope_key),
        "partner": partner_widget_key(scope_key),
    }


def _normalize_names(values: list[str] | None) -> list[str]:
    return [str(v).strip() for v in (values or []) if str(v).strip()]


def _filter_valid(names: list[str], options: list[str]) -> list[str]:
    allowed = set(options)
    return [name for name in names if name in allowed]


def queue_pending_builder_update(session: dict[str, Any], scope_key: str, update: dict[str, Any]) -> None:
    """Queue a logical builder mutation to consume before widgets render on the next run."""
    session[pending_builder_key(scope_key)] = dict(update)


def consume_pending_builder_update(session: dict[str, Any], scope_key: str) -> dict[str, Any] | None:
    pending = session.pop(pending_builder_key(scope_key), None)
    return dict(pending) if isinstance(pending, dict) else None


def apply_pending_to_logical_state(
    session: dict[str, Any],
    scope_key: str,
    logical_state: dict[str, Any],
    *,
    my_players: list[str],
    receive_options: list[str],
    other_teams: list[str],
) -> dict[str, Any]:
    """Merge pending builder update into scoped logical state; validate selections."""
    state = dict(logical_state or {})
    pending = consume_pending_builder_update(session, scope_key)
    if not pending:
        return state

    if pending.get("clear"):
        session.pop(LINEUP_TRADE_IDEAS_RESULTS_KEY, None)
        session.pop(LINEUP_TRADE_IDEAS_DIAG_KEY, None)
        clear_builder_widgets(session, scope_key)
        return {}

    give = _filter_valid(_normalize_names(pending.get("give_players")), my_players)
    receive = _filter_valid(_normalize_names(pending.get("get_players")), receive_options)
    other = str(pending.get("other_team") or "").strip()
    if other and other not in other_teams and other != ANY_TRADE_PARTNER:
        other = ""

    state.update(
        {
            "give_players": give,
            "get_players": receive,
            "other_team": other,
        }
    )
    for field in ("source_idea_id", "source_offer_id", "auto_analyze"):
        if field in pending:
            state[field] = pending[field]
    return state


def sync_builder_widgets_from_logical(
    session: dict[str, Any],
    scope_key: str,
    logical_state: dict[str, Any],
    *,
    my_players: list[str],
    receive_options: list[str],
    partner_options: list[str],
) -> dict[str, list[str] | str]:
    """Initialize scoped widget keys from logical state before widget creation."""
    keys = builder_widget_keys(scope_key)
    give = _filter_valid(_normalize_names(logical_state.get("give_players")), my_players)
    receive = _filter_valid(_normalize_names(logical_state.get("get_players")), receive_options)
    partner = str(logical_state.get("other_team") or ANY_TRADE_PARTNER).strip()
    if partner not in partner_options:
        partner = ANY_TRADE_PARTNER if ANY_TRADE_PARTNER in partner_options else (partner_options[0] if partner_options else "")

    session[keys["give"]] = give
    session[keys["receive"]] = receive
    session[keys["partner"]] = partner
    return {"give_players": give, "get_players": receive, "other_team": partner}


def clear_builder_widgets(session: dict[str, Any], scope_key: str) -> None:
    keys = builder_widget_keys(scope_key)
    for key in keys.values():
        session.pop(key, None)


def migrate_legacy_builder_keys(
    session: dict[str, Any],
    scope_key: str,
    logical_state: dict[str, Any],
) -> dict[str, Any]:
    """One-time migration from global lineup_trade_* keys into scoped logical state."""
    state = dict(logical_state or {})
    legacy_give = session.pop("lineup_trade_give_players", None)
    legacy_get = session.pop("lineup_trade_get_players", None)
    legacy_other = session.pop("lineup_trade_other_team", None)
    if legacy_give is not None and not state.get("give_players"):
        state["give_players"] = list(legacy_give or [])
    if legacy_get is not None and not state.get("get_players"):
        state["get_players"] = list(legacy_get or [])
    if legacy_other and not state.get("other_team"):
        state["other_team"] = str(legacy_other)
    if legacy_give is not None or legacy_get is not None or legacy_other:
        session.pop(pending_builder_key(scope_key), None)
    return state


def receive_options_for_partner(
    roster_stats: pd.DataFrame,
    *,
    my_team: str,
    partner: str,
    all_other_players: list[str],
) -> list[str]:
    if partner and partner != ANY_TRADE_PARTNER:
        if roster_stats is None or roster_stats.empty:
            return []
        return sorted(
            roster_stats[roster_stats["Team"].astype(str) == str(partner)]["Player"]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )
    return list(all_other_players)


def resolve_effective_partner(
    partner: str,
    receive_players: list[str],
    roster_stats: pd.DataFrame,
    *,
    my_team: str,
) -> str:
    if partner and partner != ANY_TRADE_PARTNER:
        return partner
    owners = sorted(
        {
            owner
            for player in receive_players
            if (owner := resolve_player_owner_team(player, roster_stats, my_team=my_team))
        }
    )
    if len(owners) == 1:
        return owners[0]
    return ANY_TRADE_PARTNER


def build_search_summary(
    *,
    my_team: str,
    partner: str,
    give_players: list[str],
    receive_players: list[str],
) -> str:
    give = _normalize_names(give_players)
    receive = _normalize_names(receive_players)
    partner_label = partner if partner and partner != ANY_TRADE_PARTNER else ""
    if not give and not receive and not partner_label:
        return "Searching all opposing teams for fair trades that improve your roster."
    if partner_label and not give and not receive:
        return f"Searching {partner_label}'s roster for fair trade opportunities."
    if give and not receive and not partner_label:
        return f"Searching all opposing teams for trades where you give {', '.join(give)}."
    if give and partner_label and not receive:
        return f"Searching {partner_label} for trades where you give {', '.join(give)}."
    if receive and not give:
        owner = partner_label or "the player's team"
        return f"Searching {owner} for ways to acquire {', '.join(receive)}."
    if give and receive:
        return (
            f"Evaluating {', '.join(give)} for {', '.join(receive)}"
            + (f" with {partner_label}" if partner_label else "")
            + " and finding similar alternatives."
        )
    return "Searching all opposing teams for fair trades that improve your roster."
