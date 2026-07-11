"""League lineup format configuration for simulator and uploaded drafts."""

from __future__ import annotations

import copy
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fantasy_league_context import (
    CONTEXT_TYPE_LIVE_DRAFT_RESULT,
    CONTEXT_TYPE_MOCK_DRAFT_SIMULATION,
    CONTEXT_TYPE_REAL_LEAGUE,
    context_has_roster_slots,
    get_active_league_context,
    upsert_league_context,
)

CONFIG_SOURCE_LIVE = "live_draft_setup"
CONFIG_SOURCE_SIMULATOR = "simulator_lineup_setup"
CONFIG_SOURCE_UPLOADED = "uploaded_draft_lineup_setup"

LINEUP_FORMAT_KEY = "lineup_format"

PICKABLE_POSITIONS: tuple[tuple[str, str], ...] = (
    ("C", "Catcher"),
    ("1B", "First Base"),
    ("2B", "Second Base"),
    ("3B", "Third Base"),
    ("SS", "Shortstop"),
    ("OF", "Outfield"),
    ("UTIL", "Utility"),
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def lineup_format_block(context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(context, dict):
        return None
    roster_settings = context.get("roster_settings")
    if not isinstance(roster_settings, dict):
        return None
    block = roster_settings.get(LINEUP_FORMAT_KEY)
    return copy.deepcopy(block) if isinstance(block, dict) else None


def configuration_source_for_context(context: dict[str, Any] | None) -> str:
    block = lineup_format_block(context)
    if block and str(block.get("configuration_source") or "").strip():
        return str(block["configuration_source"]).strip()
    ctx_type = str((context or {}).get("context_type") or "").strip()
    if ctx_type == CONTEXT_TYPE_LIVE_DRAFT_RESULT and context_has_roster_slots(context):
        return CONFIG_SOURCE_LIVE
    if ctx_type == CONTEXT_TYPE_MOCK_DRAFT_SIMULATION:
        return CONFIG_SOURCE_SIMULATOR
    if ctx_type == CONTEXT_TYPE_REAL_LEAGUE:
        return CONFIG_SOURCE_UPLOADED
    return ""


def needs_lineup_format_setup(context: dict[str, Any] | None) -> bool:
    """True when commissioner must choose starting positions before lineup board."""
    if not isinstance(context, dict):
        return False
    if lineup_format_block(context):
        return False
    ctx_type = str(context.get("context_type") or "").strip()
    if ctx_type == CONTEXT_TYPE_LIVE_DRAFT_RESULT and context_has_roster_slots(context):
        return False
    if ctx_type in (CONTEXT_TYPE_MOCK_DRAFT_SIMULATION, CONTEXT_TYPE_REAL_LEAGUE):
        return not context_has_roster_slots(context)
    return False


def hydrate_lineup_format_from_shared(
    session: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Merge canonical shared-league lineup format into the active context."""
    if not isinstance(context, dict) or lineup_format_block(context):
        return context
    try:
        from fantasy_league_identity import resolve_canonical_league_id
        from fantasy_shared_league_store import load_shared_league, merge_shared_into_context

        league_id = resolve_canonical_league_id(context)
        if not league_id:
            return context
        shared = load_shared_league(league_id)
        if not isinstance(shared, dict):
            return context
        shared_settings = shared.get("roster_settings") or {}
        if not isinstance(shared_settings, dict) or not shared_settings.get("lineup_format"):
            return context
        merged = merge_shared_into_context(context, shared)
        upsert_league_context(session, merged)
        return merged
    except ImportError:
        return context


def is_lineup_format_commissioner(session: dict[str, Any], context: dict[str, Any] | None) -> bool:
    if not isinstance(context, dict):
        return False
    ctx_type = str(context.get("context_type") or "").strip()
    if ctx_type == CONTEXT_TYPE_MOCK_DRAFT_SIMULATION:
        return True
    if ctx_type == CONTEXT_TYPE_REAL_LEAGUE:
        try:
            from fantasy_league_invites import is_league_commissioner

            return bool(is_league_commissioner(context))
        except ImportError:
            return True
    if ctx_type == CONTEXT_TYPE_LIVE_DRAFT_RESULT:
        return True
    return True


def detect_roster_size_hint(
    context: dict[str, Any] | None,
    team_roster: Any = None,
) -> tuple[int, dict[str, int]]:
    """Return (suggested_size, per_team_counts) from league rosters or active team."""
    counts: dict[str, int] = {}
    if isinstance(context, dict):
        league_rosters = context.get("league_rosters") or {}
        if isinstance(league_rosters, dict):
            for team, entry in league_rosters.items():
                if not isinstance(entry, dict):
                    continue
                players = entry.get("players") or []
                if isinstance(players, list):
                    counts[str(team)] = len([p for p in players if isinstance(p, dict)])
    if not counts and team_roster is not None:
        try:
            import pandas as pd

            if isinstance(team_roster, pd.DataFrame) and not team_roster.empty:
                if "Team" in team_roster.columns:
                    vc = team_roster["Team"].astype(str).value_counts()
                    counts = {str(k): int(v) for k, v in vc.items()}
                else:
                    counts = {"team": len(team_roster)}
        except ImportError:
            pass
    if not counts:
        return 9, {}
    size_values = list(counts.values())
    suggested = Counter(size_values).most_common(1)[0][0]
    return max(1, int(suggested)), counts


def expand_position_picks(picks: list[str], *, of_count: int = 0) -> list[str]:
    """Turn commissioner picks into ordered starter slot tokens."""
    slots: list[str] = []
    of_remaining = max(0, int(of_count))
    for pick in picks:
        token = str(pick or "").strip().upper()
        if token == "OF":
            n = of_remaining if of_remaining > 0 else 1
            slots.extend(["OF"] * n)
            of_remaining = 0
        elif token == "UTIL":
            slots.append("UTIL")
        elif token in ("C", "1B", "2B", "3B", "SS"):
            slots.append(token)
    return slots


def roster_capacity_from_format(context: dict[str, Any] | None) -> int | None:
    block = lineup_format_block(context)
    if block and block.get("roster_capacity") is not None:
        return max(1, int(block["roster_capacity"]))
    if context_has_roster_slots(context):
        try:
            from fantasy_league_context import resolve_context_lineup_slots

            slots = resolve_context_lineup_slots(context) or []
            if slots:
                return len(slots)
        except ImportError:
            pass
    return None


def apply_lineup_format_to_context(
    context: dict[str, Any],
    *,
    lineup_slots: list[str],
    roster_capacity: int,
    configured_by: str,
    configuration_source: str,
    league_id: str = "",
) -> dict[str, Any]:
    """Persist league lineup format into roster_settings for all teams."""
    slots = [str(s or "").strip().upper() for s in lineup_slots if str(s or "").strip()]
    counts: dict[str, int] = {}
    for token in slots:
        counts[token] = counts.get(token, 0) + 1

    try:
        from live_draft_roster_slots import freeze_slot_instances_on_config

        cfg = freeze_slot_instances_on_config({"slots": counts})
    except ImportError:
        cfg = {"slots": counts, "slot_instances": []}

    roster_settings = dict(context.get("roster_settings") or {})
    roster_settings["roster_slots"] = dict(cfg.get("slots") or counts)
    roster_settings["slot_instances"] = list(cfg.get("slot_instances") or [])
    roster_settings[LINEUP_FORMAT_KEY] = {
        "league_id": str(league_id or context.get("league_context_id") or "").strip(),
        "lineup_slots": slots,
        "roster_capacity": max(1, int(roster_capacity)),
        "configured_by": str(configured_by or "").strip(),
        "configured_at": _utc_now_iso(),
        "configuration_source": str(configuration_source or "").strip(),
    }
    context = copy.deepcopy(context)
    context["roster_settings"] = roster_settings
    return context


def save_league_lineup_format(
    session: dict[str, Any],
    *,
    lineup_slots: list[str],
    roster_capacity: int,
    configured_by: str = "",
    configuration_source: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "errors": []}
    context = get_active_league_context(session)
    if not context:
        result["errors"].append("No active league context.")
        return result
    if not is_lineup_format_commissioner(session, context):
        result["errors"].append("Only the league commissioner can set the lineup format.")
        return result
    if not lineup_slots:
        result["errors"].append("Choose at least one starting position.")
        return result

    source = configuration_source or configuration_source_for_context(context)
    if not source:
        ctx_type = str(context.get("context_type") or "")
        source = CONFIG_SOURCE_SIMULATOR if ctx_type == CONTEXT_TYPE_MOCK_DRAFT_SIMULATION else CONFIG_SOURCE_UPLOADED

    league_id = str(context.get("league_context_id") or "").strip()
    updated = apply_lineup_format_to_context(
        context,
        lineup_slots=lineup_slots,
        roster_capacity=roster_capacity,
        configured_by=configured_by,
        configuration_source=source,
        league_id=league_id,
    )
    upsert_league_context(session, updated)
    try:
        from fantasy_shared_league_store import push_league_context_to_shared

        push_league_context_to_shared(session, updated)
    except ImportError:
        pass
    try:
        import streamlit as st
        from baseball_persistent_state import force_save_baseball_state

        force_save_baseball_state(st, reason="league_lineup_format_save")
    except Exception:
        pass
    result["ok"] = True
    result["lineup_slots"] = lineup_slots
    return result


def clear_saved_lineup_assignments_for_format_change(session: dict[str, Any]) -> None:
    """Reset weekly lineup drafts and unlocked saves when format changes."""
    context = get_active_league_context(session)
    if not context:
        return
    workflow = context.setdefault("workflow", {})
    if isinstance(workflow, dict):
        workflow.pop("weekly_lineup_drafts", None)
        store = workflow.get("weekly_lineups")
        if isinstance(store, dict):
            for key in list(store.keys()):
                payload = store.get(key)
                if isinstance(payload, dict) and str(payload.get("status") or "") != "locked":
                    store.pop(key, None)
    upsert_league_context(session, context)
