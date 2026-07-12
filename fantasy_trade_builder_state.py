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
TRADE_BUILDER_STATE_SCHEMA_VERSION = 2
PENDING_BUILDER_SUFFIX = "pending_builder_update"
BUILDER_SCOPE_STAMP_SUFFIX = "builder_scope_stamp"
BUILDER_FLASH_SUFFIX = "builder_flash"
BUILDER_SCHEMA_SUFFIX = "builder_schema_version"
PROPOSAL_CONFIRM_SUFFIX = "proposal_confirm"
BUILDER_DIAG_SUFFIX = "builder_diag_last"

FORCE_REASONS = (
    "pending_update",
    "scope_change",
    "missing_widget",
    "invalid_widget",
    "none",
)


def pending_builder_key(scope_key: str) -> str:
    return f"{scope_key}|{PENDING_BUILDER_SUFFIX}"


def give_widget_key(scope_key: str) -> str:
    return f"{scope_key}|give_widget"


def receive_widget_key(scope_key: str) -> str:
    return f"{scope_key}|receive_widget"


def partner_widget_key(scope_key: str) -> str:
    return f"{scope_key}|partner_widget"


def builder_scope_stamp_key(scope_key: str) -> str:
    return f"{scope_key}|{BUILDER_SCOPE_STAMP_SUFFIX}"


def builder_schema_key(scope_key: str) -> str:
    return f"{scope_key}|{BUILDER_SCHEMA_SUFFIX}"


def proposal_confirm_key(scope_key: str) -> str:
    return f"{scope_key}|{PROPOSAL_CONFIRM_SUFFIX}"


def builder_diag_key(scope_key: str) -> str:
    return f"{scope_key}|{BUILDER_DIAG_SUFFIX}"


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


def _logical_partner(logical_state: dict[str, Any], partner_options: list[str]) -> str:
    partner = str(
        logical_state.get("trade_partner")
        or logical_state.get("other_team")
        or ANY_TRADE_PARTNER
    ).strip()
    if partner not in partner_options:
        partner = ANY_TRADE_PARTNER if ANY_TRADE_PARTNER in partner_options else (partner_options[0] if partner_options else "")
    return partner


def _widget_snapshot(session: dict[str, Any], scope_key: str) -> dict[str, Any]:
    keys = builder_widget_keys(scope_key)
    return {
        "partner": session.get(keys["partner"]),
        "give": list(session.get(keys["give"]) or []),
        "receive": list(session.get(keys["receive"]) or []),
    }


def queue_pending_builder_update(session: dict[str, Any], scope_key: str, update: dict[str, Any]) -> None:
    """Queue a logical builder mutation to consume before widgets render on the next run."""
    session[pending_builder_key(scope_key)] = dict(update)


def consume_pending_builder_update(session: dict[str, Any], scope_key: str) -> dict[str, Any] | None:
    pending = session.pop(pending_builder_key(scope_key), None)
    return dict(pending) if isinstance(pending, dict) else None


def clear_legacy_lineup_trade_keys(session: dict[str, Any]) -> None:
    for key in (
        "lineup_trade_give_players",
        "lineup_trade_get_players",
        "lineup_trade_other_team",
        "lineup_trade_analyzer_open",
    ):
        session.pop(key, None)


def maybe_migrate_builder_schema(
    session: dict[str, Any],
    scope_key: str,
    logical_state: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """One-time migration when stored schema version differs from current."""
    schema_key = builder_schema_key(scope_key)
    stored = int(session.get(schema_key) or 0)
    if stored >= TRADE_BUILDER_STATE_SCHEMA_VERSION:
        return logical_state, False

    clear_builder_widgets(session, scope_key)
    session.pop(pending_builder_key(scope_key), None)
    session.pop(f"{scope_key}|{BUILDER_FLASH_SUFFIX}", None)
    session.pop(proposal_confirm_key(scope_key), None)
    clear_legacy_lineup_trade_keys(session)

    state = dict(logical_state or {})
    for field in (
        "give_players",
        "get_players",
        "other_team",
        "trade_partner",
        "source_idea_id",
        "auto_analyze",
        "analysis",
        "verdict",
        "mode",
    ):
        state.pop(field, None)
    state["trade_partner"] = ANY_TRADE_PARTNER

    session[schema_key] = TRADE_BUILDER_STATE_SCHEMA_VERSION
    session[f"{scope_key}|{BUILDER_FLASH_SUFFIX}"] = (
        "Trade builder reset to a fresh editable state after a layout update."
    )
    return state, True


def reset_trade_builder(
    session: dict[str, Any],
    scope_key: str,
    *,
    logical_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Emergency reset — builder selections and stale analysis only."""
    clear_builder_widgets(session, scope_key)
    session.pop(pending_builder_key(scope_key), None)
    session.pop(proposal_confirm_key(scope_key), None)
    session.pop(LINEUP_TRADE_IDEAS_RESULTS_KEY, None)
    session.pop(LINEUP_TRADE_IDEAS_DIAG_KEY, None)
    clear_legacy_lineup_trade_keys(session)

    state = dict(logical_state or {})
    for field in (
        "give_players",
        "get_players",
        "other_team",
        "trade_partner",
        "source_idea_id",
        "auto_analyze",
        "analysis",
        "verdict",
        "mode",
    ):
        state.pop(field, None)
    state["trade_partner"] = ANY_TRADE_PARTNER
    session[f"{scope_key}|{BUILDER_FLASH_SUFFIX}"] = "Trade builder reset. Offers and history were preserved."
    return state


def apply_pending_to_logical_state(
    session: dict[str, Any],
    scope_key: str,
    logical_state: dict[str, Any],
    *,
    my_players: list[str],
    receive_options: list[str],
    other_teams: list[str],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Merge one-time pending builder update into scoped logical state."""
    state = dict(logical_state or {})
    pending = consume_pending_builder_update(session, scope_key)
    if not pending:
        return state, None

    action = str(pending.get("action") or "").strip().lower()
    if pending.get("clear") or action == "clear":
        session.pop(LINEUP_TRADE_IDEAS_RESULTS_KEY, None)
        session.pop(LINEUP_TRADE_IDEAS_DIAG_KEY, None)
        session.pop(proposal_confirm_key(scope_key), None)
        clear_builder_widgets(session, scope_key)
        session.pop(f"{scope_key}|{BUILDER_FLASH_SUFFIX}", None)
        clear_legacy_lineup_trade_keys(session)
        return {}, pending

    give = _filter_valid(_normalize_names(pending.get("give_players")), my_players)
    receive = _filter_valid(_normalize_names(pending.get("get_players")), receive_options)
    other = str(pending.get("other_team") or pending.get("trade_partner") or "").strip()
    if other and other not in other_teams and other != ANY_TRADE_PARTNER:
        other = ""

    state.update(
        {
            "give_players": give,
            "get_players": receive,
            "other_team": other,
            "trade_partner": other if other else ANY_TRADE_PARTNER,
        }
    )
    for field in ("source_idea_id", "source_offer_id", "analysis"):
        if field in pending:
            state[field] = pending[field]

    if action in ("analyze", "analyze_offer") or pending.get("auto_analyze"):
        state["auto_analyze"] = True
    elif "auto_analyze" in pending:
        state["auto_analyze"] = bool(pending.get("auto_analyze"))

    if action == "propose" or pending.get("await_proposal_confirm"):
        session[proposal_confirm_key(scope_key)] = {
            "give_players": give,
            "get_players": receive,
            "trade_partner": other if other else ANY_TRADE_PARTNER,
            "other_team": other,
            "source_idea_id": str(pending.get("source_idea_id") or ""),
            "source_offer_id": str(pending.get("source_offer_id") or ""),
        }

    flash = str(pending.get("flash_message") or "").strip()
    if flash:
        session[f"{scope_key}|{BUILDER_FLASH_SUFFIX}"] = flash
    elif action == "analyze" or action == "analyze_offer":
        session[f"{scope_key}|{BUILDER_FLASH_SUFFIX}"] = "Trade loaded for analysis."
    elif action == "propose":
        session[f"{scope_key}|{BUILDER_FLASH_SUFFIX}"] = "Trade loaded. Review and confirm the proposal below."
    elif action in ("use", ""):
        session[f"{scope_key}|{BUILDER_FLASH_SUFFIX}"] = (
            "Trade idea loaded. Review, edit, analyze, or propose it."
        )
    return state, pending


def scope_fingerprint_changed(session: dict[str, Any], scope_key: str, scope_fingerprint: str) -> tuple[bool, str | None]:
    stamp_key = builder_scope_stamp_key(scope_key)
    previous = session.get(stamp_key)
    session[stamp_key] = scope_fingerprint
    if previous is not None and previous != scope_fingerprint:
        return True, str(previous)
    return False, str(previous) if previous is not None else None


def prepare_builder_widget_state(
    session: dict[str, Any],
    scope_key: str,
    logical_state: dict[str, Any],
    *,
    my_players: list[str],
    receive_options: list[str],
    partner_options: list[str],
    force: bool = False,
    force_reason: str = "none",
) -> dict[str, Any]:
    """Initialize widget keys only when required; preserve valid user selections otherwise."""
    keys = builder_widget_keys(scope_key)
    before = _widget_snapshot(session, scope_key)
    resolved_reason = force_reason if force_reason in FORCE_REASONS else "none"

    logical_give = _filter_valid(_normalize_names(logical_state.get("give_players")), my_players)
    logical_receive = _filter_valid(_normalize_names(logical_state.get("get_players")), receive_options)
    logical_partner = _logical_partner(logical_state, partner_options)

    if force:
        session[keys["partner"]] = logical_partner
        session[keys["give"]] = logical_give
        session[keys["receive"]] = logical_receive
    else:
        resolved_reason = "none"
        if keys["partner"] not in session:
            session[keys["partner"]] = ANY_TRADE_PARTNER
            resolved_reason = "missing_widget"
        else:
            current_partner = str(session.get(keys["partner"]) or "").strip()
            if current_partner not in partner_options:
                session[keys["partner"]] = ANY_TRADE_PARTNER
                resolved_reason = "invalid_widget"

        if keys["give"] not in session:
            session[keys["give"]] = []
            if resolved_reason == "none":
                resolved_reason = "missing_widget"
        else:
            current_give = _normalize_names(session.get(keys["give"]))
            valid_give = _filter_valid(current_give, my_players)
            if len(valid_give) != len(current_give):
                session[keys["give"]] = valid_give
                if resolved_reason == "none":
                    resolved_reason = "invalid_widget"

        if keys["receive"] not in session:
            session[keys["receive"]] = []
            if resolved_reason == "none":
                resolved_reason = "missing_widget"
        else:
            current_receive = _normalize_names(session.get(keys["receive"]))
            valid_receive = _filter_valid(current_receive, receive_options)
            if len(valid_receive) != len(current_receive):
                session[keys["receive"]] = valid_receive
                if resolved_reason == "none":
                    resolved_reason = "invalid_widget"

    after = _widget_snapshot(session, scope_key)
    return {
        "force_widgets": force or resolved_reason in ("missing_widget", "invalid_widget"),
        "force_reason": force_reason if force else resolved_reason,
        "partner_widget_before": before["partner"],
        "partner_widget_after": after["partner"],
        "give_widget_before": before["give"],
        "give_widget_after": after["give"],
        "receive_widget_before": before["receive"],
        "receive_widget_after": after["receive"],
        "logical_partner": logical_partner,
        "logical_give": logical_give,
        "logical_receive": logical_receive,
    }


def prune_invalid_receive_for_partner(
    session: dict[str, Any],
    scope_key: str,
    *,
    receive_options: list[str],
    roster_stats: pd.DataFrame,
    my_team: str,
    partner: str,
) -> list[str]:
    """Remove receive selections invalid for the current partner scope (pre-render only)."""
    keys = builder_widget_keys(scope_key)
    current = _normalize_names(session.get(keys["receive"]))
    valid = _filter_valid(current, receive_options)
    removed = [name for name in current if name not in valid]
    if removed != current:
        session[keys["receive"]] = valid

    messages: list[str] = []
    for name in removed:
        owner = resolve_player_owner_team(name, roster_stats, my_team=my_team) or "another team"
        if partner and partner != ANY_TRADE_PARTNER:
            messages.append(f"{name} was removed because they are owned by {owner}, not {partner}.")
        else:
            messages.append(f"{name} was removed because they are not available for the current partner filter.")
    return messages


def save_logical_state_from_widgets(
    logical_state: dict[str, Any],
    *,
    give_players: list[str],
    receive_players: list[str],
    trade_partner: str,
    other_team: str,
) -> dict[str, Any]:
    """Persist widget return values into logical state without touching widget keys."""
    state = dict(logical_state or {})
    state["give_players"] = list(give_players or [])
    state["get_players"] = list(receive_players or [])
    state["trade_partner"] = trade_partner
    state["other_team"] = other_team if other_team and other_team != ANY_TRADE_PARTNER else ""
    state.pop("auto_analyze", None)
    return state


def build_builder_diagnostics(
    *,
    deployed_feature_sha: str,
    scope_key: str,
    scope_fingerprint: str,
    previous_scope_stamp: str | None,
    scope_changed: bool,
    pending_update: dict[str, Any] | None,
    prepare_diag: dict[str, Any],
    handoff_present: bool,
    handoff_consumed: bool,
    schema_migrated: bool,
) -> dict[str, Any]:
    pending = pending_update or {}
    return {
        "deployed_feature_sha": deployed_feature_sha,
        "scope_key": scope_key,
        "scope_fingerprint": scope_fingerprint,
        "previous_scope_stamp": previous_scope_stamp,
        "scope_changed": scope_changed,
        "schema_migrated": schema_migrated,
        "pending_update_found": bool(pending),
        "pending_action": str(pending.get("action") or ""),
        "pending_source": str(pending.get("source_idea_id") or pending.get("source_offer_id") or ""),
        "force_widgets": bool(prepare_diag.get("force_widgets")),
        "force_reason": str(prepare_diag.get("force_reason") or "none"),
        "partner_widget_before": prepare_diag.get("partner_widget_before"),
        "partner_widget_after": prepare_diag.get("partner_widget_after"),
        "give_widget_before": prepare_diag.get("give_widget_before"),
        "give_widget_after": prepare_diag.get("give_widget_after"),
        "receive_widget_before": prepare_diag.get("receive_widget_before"),
        "receive_widget_after": prepare_diag.get("receive_widget_after"),
        "logical_partner": prepare_diag.get("logical_partner"),
        "logical_give": prepare_diag.get("logical_give"),
        "logical_receive": prepare_diag.get("logical_receive"),
        "handoff_present": handoff_present,
        "handoff_consumed": handoff_consumed,
    }


def clear_builder_widgets(session: dict[str, Any], scope_key: str) -> None:
    keys = builder_widget_keys(scope_key)
    for key in keys.values():
        session.pop(key, None)


def migrate_legacy_builder_keys(
    session: dict[str, Any],
    scope_key: str,
    logical_state: dict[str, Any],
) -> dict[str, Any]:
    """Discard legacy global lineup_trade_* keys — Trade Center owns builder state now."""
    clear_legacy_lineup_trade_keys(session)
    return dict(logical_state or {})


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
