"""Authoritative Live Draft recommendation context — team on clock only."""

from __future__ import annotations

from typing import Any

import pandas as pd

RECOMMENDATION_CONTEXT_KEY = "_live_draft_recommendation_context_diag"


def _draft_fingerprint(room: dict[str, Any]) -> str:
    try:
        from fantasy_league_identity import compute_draft_fingerprint

        cfg = dict(room.get("config") or {})
        return str(compute_draft_fingerprint(cfg) or "").strip()
    except ImportError:
        return str(room.get("draft_fingerprint") or room.get("draft_id") or "").strip()


def _draft_id(room: dict[str, Any]) -> str:
    return str(
        room.get("draft_room_id")
        or room.get("draft_id")
        or (room.get("config") or {}).get("draft_id")
        or ""
    ).strip()


def _player_names(roster: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for row in roster:
        if not isinstance(row, dict):
            continue
        name = str(row.get("fullName") or row.get("Player") or "").strip()
        if name:
            names.append(name)
    return names


def _open_and_filled_slots(target_counts: dict[str, int], roster_df: pd.DataFrame) -> tuple[list[str], list[str]]:
    if roster_df is None or roster_df.empty or "Primary Position" not in roster_df.columns:
        open_slots = [pos for pos, count in target_counts.items() if int(count or 0) > 0]
        return open_slots, []
    counts = roster_df["Primary Position"].fillna("DH").astype(str).value_counts().to_dict()
    open_slots: list[str] = []
    filled_slots: list[str] = []
    for pos, target in target_counts.items():
        if int(target or 0) <= 0:
            continue
        have = int(counts.get(str(pos), 0))
        if have < int(target):
            open_slots.append(str(pos))
        elif have > 0:
            filled_slots.append(str(pos))
    return open_slots, filled_slots


def _research_mode_enabled(session: dict[str, Any] | None) -> bool:
    if not isinstance(session, dict):
        return False
    try:
        from fantasy_context_source import is_research_mode_sync_enabled

        return bool(is_research_mode_sync_enabled(session))
    except ImportError:
        return bool(session.get("use_active_league_context_waiver_filter"))


def resolve_team_on_clock(room: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Return (slot, team_on_clock) from the draft board / pick order only."""
    try:
        from live_draft_timer_logic import resolve_live_draft_on_clock_slot

        slot = resolve_live_draft_on_clock_slot(room)
    except ImportError:
        from live_draft_timer_logic import live_draft_current_slot

        slot = live_draft_current_slot(room)
    if not isinstance(slot, dict):
        return None, ""
    team = str(slot.get("Team") or "").strip()
    return slot, team


def build_live_draft_recommendation_context(
    room: dict[str, Any],
    session: dict[str, Any] | None = None,
    *,
    team_override: str | None = None,
) -> dict[str, Any]:
    """Build one authoritative recommendation context for the team currently on the clock."""
    slot, team_on_clock = resolve_team_on_clock(room)
    # Active rooms can briefly lose the on-clock slot; keep scoring usable via override.
    if (not team_on_clock or slot is None) and str(team_override or "").strip():
        team_on_clock = str(team_override).strip()
        pick_n = int(room.get("current_pick_index") or 0) + 1
        slot = dict(slot or {})
        slot.setdefault("Team", team_on_clock)
        slot.setdefault("Pick", pick_n)
        slot.setdefault("Round", max(1, (pick_n - 1) // max(1, len(room.get("teams") or []) or 12) + 1))
    empty: dict[str, Any] = {
        "draft_id": _draft_id(room),
        "draft_fingerprint": _draft_fingerprint(room),
        "pick_number": 0,
        "round_number": 0,
        "team_on_clock": "",
        "resolved_recommendation_team": "",
        "team_roster": [],
        "team_roster_players": [],
        "all_drafted_players": [],
        "open_roster_slots": [],
        "filled_roster_slots": [],
        "category_strengths": [],
        "category_weaknesses": [],
        "league_settings": dict(room.get("config") or {}),
        "roster_slots": {},
        "scoring_settings": {},
        "drafted_player_count": 0,
        "candidate_pool_count": 0,
        "research_mode": _research_mode_enabled(session),
    }
    if not team_on_clock or slot is None:
        return empty

    try:
        from live_draft_state import live_draft_get_available, reconcile_drafted_player_ids

        reconcile_drafted_player_ids(room)
        available = live_draft_get_available(room)
    except ImportError:
        from live_draft_state import live_draft_get_available

        available = live_draft_get_available(room)

    cfg = dict(room.get("config") or {})
    try:
        from live_draft_roster_slots import ensure_room_slot_config, normalize_draft_slot_config

        scratch = {"config": cfg}
        ensure_room_slot_config(scratch)
        cfg = dict(scratch.get("config") or cfg)
        cfg = normalize_draft_slot_config(cfg)
    except ImportError:
        pass

    roster_rows = list((room.get("rosters") or {}).get(team_on_clock) or [])
    roster_df = pd.DataFrame(roster_rows)
    target_counts: dict[str, int] = {}
    try:
        from live_draft_pick_scoring import _live_draft_target_counts

        target_counts = _live_draft_target_counts(cfg)
    except ImportError:
        slots = cfg.get("slots") or {}
        target_counts = {str(k): int(v or 0) for k, v in slots.items()}

    open_slots, filled_slots = _open_and_filled_slots(target_counts, roster_df)
    fantasy_format = str(cfg.get("fantasy_format") or "5x5 Roto")
    category_strengths: list[str] = []
    category_weaknesses: list[str] = []
    need_pos: list[str] = list(open_slots)
    cat_needs: list[str] = []
    try:
        from live_draft_safe_mode import is_draft_truly_complete

        draft_complete = bool(is_draft_truly_complete(room))
    except ImportError:
        draft_complete = str(room.get("status") or "").strip() == "complete"
    try:
        from draft_needs import infer_draft_team_needs

        need_pos, cat_needs = infer_draft_team_needs(
            roster_df,
            available,
            config=cfg,
            fantasy_format=fantasy_format,
            draft_complete=draft_complete,
        )
        category_weaknesses = list(cat_needs or [])
        if need_pos:
            open_slots = list(need_pos)
    except ImportError:
        pass

    drafted_names: list[str] = []
    for row in room.get("draft_board") or []:
        if isinstance(row, dict):
            name = str(row.get("fullName") or row.get("Player") or "").strip()
            if name:
                drafted_names.append(name)

    scoring_settings = {
        "fantasy_format": fantasy_format,
        "scoring_type": str(cfg.get("scoring_type") or ""),
        "use_ml_blend": bool(cfg.get("use_ml_blend", False)),
        "ml_blend_weight": float(cfg.get("ml_blend_weight") or 0),
    }

    context = {
        "draft_id": _draft_id(room),
        "draft_fingerprint": _draft_fingerprint(room),
        "pick_number": int(slot.get("Pick") or 1),
        "round_number": int(slot.get("Round") or 1),
        "team_on_clock": team_on_clock,
        "resolved_recommendation_team": team_on_clock,
        "team_roster": roster_rows,
        "team_roster_players": _player_names(roster_rows),
        "all_drafted_players": drafted_names,
        "open_roster_slots": list(open_slots),
        "filled_roster_slots": list(filled_slots),
        "category_strengths": list(category_strengths),
        "category_weaknesses": list(category_weaknesses),
        "league_settings": cfg,
        "roster_slots": dict(target_counts),
        "scoring_settings": scoring_settings,
        "drafted_player_count": len(drafted_names),
        "candidate_pool_count": int(len(available)) if isinstance(available, pd.DataFrame) else 0,
        "research_mode": _research_mode_enabled(session),
        "needed_positions": list(need_pos),
        "category_needs": list(cat_needs),
        "current_pick": int(slot.get("Pick") or 1),
        "next_user_pick": None,
        "target_counts": target_counts,
        "draft_complete": draft_complete,
        "fantasy_format": fantasy_format,
    }
    if isinstance(session, dict):
        session[RECOMMENDATION_CONTEXT_KEY] = {
            "active_live_draft_id": context["draft_id"],
            "draft_fingerprint": context["draft_fingerprint"],
            "pick_number": context["pick_number"],
            "round_number": context["round_number"],
            "team_on_clock": context["team_on_clock"],
            "resolved_recommendation_team": context["resolved_recommendation_team"],
            "team_roster_players": context["team_roster_players"],
            "open_slots": context["open_roster_slots"],
            "filled_slots": context["filled_roster_slots"],
            "category_strengths": context["category_strengths"],
            "category_weaknesses": context["category_weaknesses"],
            "drafted_player_count": context["drafted_player_count"],
            "candidate_pool_count": context["candidate_pool_count"],
            "research_mode": context["research_mode"],
        }
    return context
