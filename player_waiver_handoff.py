"""Player Action → Waiver Wire / Add-Drop handoff (active real league only)."""

from __future__ import annotations

from typing import Any

from fantasy_waiver_wire import WAIVER_PLANNER_ADD_KEY, WAIVER_PLANNER_DROP_KEY, WAIVER_WIRE_PAGE, set_waiver_tx_flash
from player_trade_constants import WAIVER_ACTION_PLAN_ADD, WAIVER_ACTION_PLAN_DROP
from player_trade_handoff import (
    VALIDATION_OK,
    VALIDATION_STALE,
    VALIDATION_TRANSIENT,
    _resolve_active_league_ids,
    _validate_league_identity,
    resolve_active_league_player_trade_eligibility,
)

WAIVER_WIRE_HANDOFF_KEY = "_waiver_wire_handoff"
HANDOFF_DIAG_SUFFIX = "waiver_handoff_diag"


def handoff_diag_key(scope_key: str = "waiver_wire") -> str:
    return f"{scope_key}|{HANDOFF_DIAG_SUFFIX}"


def _display_base(name: str) -> str:
    return str(name or "").split(" (")[0].strip()


def build_waiver_wire_handoff_payload(
    *,
    action: str,
    player_name: str,
    league_context_id: str,
    canonical_league_id: str,
    my_team: str,
    league_label: str,
) -> dict[str, Any]:
    display = _display_base(player_name)
    action_norm = str(action or "").strip().lower()
    flash_message = ""
    if action_norm == WAIVER_ACTION_PLAN_ADD:
        flash_message = f"{display} loaded as a planned add in {league_label}."
    elif action_norm == WAIVER_ACTION_PLAN_DROP:
        flash_message = f"{display} loaded as a planned drop from {my_team}."

    return {
        "action": action_norm,
        "source": "player_action",
        "player_name": display,
        "league_context_id": str(league_context_id or "").strip(),
        "canonical_league_id": str(canonical_league_id or "").strip(),
        "my_team": str(my_team or "").strip(),
        "flash_message": flash_message,
    }


def queue_player_action_waiver_handoff(
    session: dict[str, Any],
    *,
    player_name: str,
    mode: str,
) -> tuple[bool, str]:
    """Validate active-league ownership and queue durable Waiver Wire handoff."""
    eligibility = resolve_active_league_player_trade_eligibility(session, player_name)
    display = str(eligibility.get("player_name") or "").strip()
    mode_norm = str(mode or "").strip().lower()

    if mode_norm == WAIVER_ACTION_PLAN_ADD:
        if not eligibility.get("plan_add_enabled"):
            return False, str(
                eligibility.get("plan_add_help")
                or eligibility.get("block_message")
                or "Plan Add unavailable."
            )
    elif mode_norm == WAIVER_ACTION_PLAN_DROP:
        if not eligibility.get("plan_drop_enabled"):
            return False, str(
                eligibility.get("plan_drop_help")
                or eligibility.get("block_message")
                or "Plan Drop unavailable."
            )
    else:
        return False, "Unknown waiver action."

    league_context_id = str(eligibility.get("league_context_id") or "").strip()
    if league_context_id:
        try:
            from fantasy_league_context import schedule_league_context_activation

            schedule_league_context_activation(session, league_context_id)
        except ImportError:
            pass

    _, canonical_league_id = _resolve_active_league_ids(session)
    league_label = str(eligibility.get("league_label") or "active league")
    handoff = build_waiver_wire_handoff_payload(
        action=mode_norm,
        player_name=display,
        league_context_id=league_context_id,
        canonical_league_id=canonical_league_id,
        my_team=str(eligibility.get("my_team") or ""),
        league_label=league_label,
    )
    session[WAIVER_WIRE_HANDOFF_KEY] = handoff
    session["_navigate_to_page"] = WAIVER_WIRE_PAGE
    session["_skip_page_restore_for"] = WAIVER_WIRE_PAGE

    action_label = "Plan Add" if mode_norm == WAIVER_ACTION_PLAN_ADD else "Plan Drop"
    return True, f"{action_label} for {display} in {league_label}. Opening Waiver Wire / Add-Drop Center."


def _record_handoff_diag(
    session: dict[str, Any],
    *,
    handoff: dict[str, Any] | None,
    active_context_id: str,
    active_canonical_league_id: str,
    validation_result: str,
    rejection_reason: str = "",
    applied: bool = False,
    planned_add: list[str] | None = None,
    planned_drop: list[str] | None = None,
) -> None:
    session[handoff_diag_key()] = {
        "handoff_present": isinstance(handoff, dict),
        "handoff_context_id": str((handoff or {}).get("league_context_id") or ""),
        "handoff_canonical_league_id": str((handoff or {}).get("canonical_league_id") or ""),
        "active_context_id": str(active_context_id or ""),
        "active_canonical_league_id": str(active_canonical_league_id or ""),
        "validation_result": str(validation_result or ""),
        "rejection_reason": str(rejection_reason or ""),
        "applied": bool(applied),
        "planned_add": list(planned_add or []),
        "planned_drop": list(planned_drop or []),
    }


def _player_owner_team(active: dict[str, Any], player_name: str) -> str:
    try:
        from fantasy_league_context import normalize_player_key
    except ImportError:
        return ""
    ownership = active.get("ownership_map") or {}
    if not isinstance(ownership, dict):
        return ""
    key = normalize_player_key(_display_base(player_name))
    rec = ownership.get(key) if key else None
    if not isinstance(rec, dict):
        return ""
    return str(rec.get("owner_team") or "").strip()


def _preserve_valid_planner_side(
    session: dict[str, Any],
    active: dict[str, Any],
    *,
    my_team: str,
    incoming_action: str,
) -> tuple[str, str]:
    """Keep the opposite planner pick when it remains valid for this league/team."""
    current_add = str(session.get(WAIVER_PLANNER_ADD_KEY) or "").strip()
    current_drop = str(session.get(WAIVER_PLANNER_DROP_KEY) or "").strip()
    if incoming_action == WAIVER_ACTION_PLAN_ADD:
        drop_owner = _player_owner_team(active, current_drop) if current_drop else ""
        if current_drop and drop_owner == my_team:
            return current_add, current_drop
        return current_add, ""
    if incoming_action == WAIVER_ACTION_PLAN_DROP:
        add_owner = _player_owner_team(active, current_add) if current_add else ""
        if current_add and not add_owner:
            return current_add, current_drop
        return "", current_drop
    return current_add, current_drop


def validate_waiver_wire_handoff(
    handoff: dict[str, Any],
    session: dict[str, Any],
    *,
    active_context_id: str = "",
    active_canonical_league_id: str = "",
) -> tuple[dict[str, Any] | None, str, str]:
    try:
        from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE, get_active_league_context
        from fantasy_league_team_ownership import owned_team_for_user, trades_enabled
    except ImportError:
        return None, "Waiver Wire handoff validation unavailable.", VALIDATION_STALE

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
    if str(active.get("context_type") or "").strip() != CONTEXT_TYPE_REAL_LEAGUE:
        return None, "Waiver actions require an active real shared league.", VALIDATION_STALE

    ok_trade, trade_msg = trades_enabled(active, session)
    if not ok_trade:
        return None, trade_msg or "Waiver actions require an active shared league.", VALIDATION_STALE

    owned_team = owned_team_for_user(active) or str(active.get("my_team_name") or "").strip()
    handoff_team = str(handoff.get("my_team") or "").strip()
    if handoff_team and owned_team and handoff_team != owned_team:
        return None, "Waiver target could not be loaded because your owned team changed.", VALIDATION_STALE
    if not owned_team:
        return None, "Claim your team in this league before using Waiver Wire.", VALIDATION_STALE

    player_name = _display_base(str(handoff.get("player_name") or ""))
    action = str(handoff.get("action") or "").strip().lower()
    owner_team = _player_owner_team(active, player_name)

    if action == WAIVER_ACTION_PLAN_ADD:
        if owner_team:
            return (
                None,
                f"{player_name} is rostered by {owner_team}. Use Acquire in Trade Center instead.",
                VALIDATION_STALE,
            )
    elif action == WAIVER_ACTION_PLAN_DROP:
        if owner_team != owned_team:
            if owner_team:
                return (
                    None,
                    f"{player_name} is rostered by {owner_team}. You can only plan drops from {owned_team}.",
                    VALIDATION_STALE,
                )
            return None, f"{player_name} is not on {owned_team}. Plan Drop is unavailable.", VALIDATION_STALE
    else:
        return None, "Unknown waiver handoff action.", VALIDATION_STALE

    payload = dict(handoff)
    payload["player_name"] = player_name
    payload["my_team"] = owned_team
    if action == WAIVER_ACTION_PLAN_ADD:
        payload["planned_add"] = [player_name]
        payload["planned_drop"] = []
    else:
        payload["planned_add"] = []
        payload["planned_drop"] = [player_name]
    return payload, "", VALIDATION_OK


def consume_waiver_wire_handoff_into_planner(
    session: dict[str, Any],
    *,
    active_context_id: str = "",
    active_canonical_league_id: str = "",
) -> bool:
    """Apply `_waiver_wire_handoff` to planner keys after scope/context are ready."""
    handoff = session.get(WAIVER_WIRE_HANDOFF_KEY)
    if not isinstance(handoff, dict):
        _record_handoff_diag(
            session,
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

    validated, err, status = validate_waiver_wire_handoff(
        handoff,
        session,
        active_context_id=active_context_id,
        active_canonical_league_id=active_canonical_league_id,
    )
    if validated is None:
        _record_handoff_diag(
            session,
            handoff=handoff,
            active_context_id=active_context_id,
            active_canonical_league_id=active_canonical_league_id,
            validation_result=status,
            rejection_reason=err or "Waiver target could not be loaded.",
        )
        if err:
            set_waiver_tx_flash(session, level="warning", message=err)
        if status == VALIDATION_STALE:
            session.pop(WAIVER_WIRE_HANDOFF_KEY, None)
        return False

    try:
        from fantasy_league_context import get_active_league_context

        active = get_active_league_context(session) or {}
    except ImportError:
        active = {}

    action = str(validated.get("action") or "").strip().lower()
    my_team = str(validated.get("my_team") or "").strip()
    player_name = str(validated.get("player_name") or "").strip()
    preserved_add, preserved_drop = _preserve_valid_planner_side(
        session,
        active,
        my_team=my_team,
        incoming_action=action,
    )

    if action == WAIVER_ACTION_PLAN_ADD:
        session[WAIVER_PLANNER_ADD_KEY] = player_name
        if preserved_drop:
            session[WAIVER_PLANNER_DROP_KEY] = preserved_drop
        else:
            session.pop(WAIVER_PLANNER_DROP_KEY, None)
        planned_add = [player_name]
        planned_drop = [preserved_drop] if preserved_drop else []
    else:
        session[WAIVER_PLANNER_DROP_KEY] = player_name
        if preserved_add:
            session[WAIVER_PLANNER_ADD_KEY] = preserved_add
        else:
            session.pop(WAIVER_PLANNER_ADD_KEY, None)
        planned_add = [preserved_add] if preserved_add else []
        planned_drop = [player_name]

    flash_message = str(validated.get("flash_message") or "").strip()
    if flash_message:
        set_waiver_tx_flash(session, level="info", message=flash_message)

    session.pop(WAIVER_WIRE_HANDOFF_KEY, None)
    _record_handoff_diag(
        session,
        handoff=validated,
        active_context_id=active_context_id,
        active_canonical_league_id=active_canonical_league_id,
        validation_result=VALIDATION_OK,
        applied=True,
        planned_add=planned_add,
        planned_drop=planned_drop,
    )
    return True
