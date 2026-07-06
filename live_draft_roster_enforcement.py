"""End-of-draft required-position enforcement for Live Draft Room."""

from __future__ import annotations

from typing import Any

import pandas as pd

from draft_needs import filter_bench_gaps
from live_draft_roster_slots import (
    _eligible_for_draft_slot,
    _player_position_tokens,
    get_remaining_position_needs,
)


def count_team_picks_remaining(room: dict[str, Any] | None, team_name: str) -> int:
    """Unmade pick-order slots for one fantasy team from the current index onward."""
    if not isinstance(room, dict):
        return 0
    team = str(team_name or "").strip()
    if not team:
        return 0
    picks = room.get("pick_order") or []
    idx = int(room.get("current_pick_index") or 0)
    count = 0
    for slot in picks[idx:]:
        if isinstance(slot, dict) and str(slot.get("Team") or "").strip() == team:
            count += 1
    return count


def _display_position_code(code: str) -> str:
    pos = str(code or "").strip().upper()
    if pos == "DH":
        return "UTIL"
    return pos


def format_required_pick_message(required_positions: list[str]) -> str:
    """User-facing disable message for forced required-position picks."""
    labels = [_display_position_code(p) for p in dict.fromkeys(required_positions or []) if str(p).strip()]
    if not labels:
        return "Required pick: you must fill a required roster slot."
    if len(labels) == 1:
        return f"Required pick: you must select a {labels[0]}."
    if len(labels) == 2:
        return f"Required pick: you must select {labels[0]} or {labels[1]}."
    return f"Required pick: you must select {', '.join(labels[:-1])} or {labels[-1]}."


def compute_required_position_enforcement(
    roster_df: pd.DataFrame | None,
    config: dict[str, Any] | None,
    *,
    picks_remaining: int,
) -> tuple[bool, list[str]]:
    """
    Force required-position picks when remaining picks cannot skip open slots.

    Bench is excluded. Activates when picks_remaining <= open required slots.
    """
    if picks_remaining <= 0:
        return False, []
    gaps = filter_bench_gaps(get_remaining_position_needs(roster_df, config))
    if not gaps:
        return False, []
    if picks_remaining <= len(gaps):
        return True, list(dict.fromkeys(gaps))
    return False, []


def player_eligible_for_required_positions(
    row: Any,
    required_positions: list[str],
) -> bool:
    """True when multi-position eligibility matches any enforced open slot."""
    if not required_positions:
        return True
    if row is None:
        return False
    series = row if isinstance(row, pd.Series) else pd.Series(row)
    tokens = _player_position_tokens(series)
    return any(_eligible_for_draft_slot(tokens, str(pos)) for pos in required_positions)


def resolve_on_clock_enforcement(
    room: dict[str, Any] | None,
    *,
    on_clock_team: str,
) -> dict[str, Any]:
    """Enforcement snapshot for the team currently on the clock."""
    out: dict[str, Any] = {
        "active": False,
        "on_clock_team": str(on_clock_team or "").strip(),
        "required_positions": [],
        "picks_remaining": 0,
        "message": "",
    }
    if not isinstance(room, dict) or not out["on_clock_team"]:
        return out
    try:
        from live_draft_roster_tracker import roster_df_for_team

        roster_df = roster_df_for_team(room, out["on_clock_team"])
    except ImportError:
        roster_df = pd.DataFrame((room.get("rosters") or {}).get(out["on_clock_team"]) or [])
    cfg = dict(room.get("config") or {})
    out["picks_remaining"] = count_team_picks_remaining(room, out["on_clock_team"])
    active, required = compute_required_position_enforcement(
        roster_df,
        cfg,
        picks_remaining=out["picks_remaining"],
    )
    out["active"] = active
    out["required_positions"] = required
    if active:
        out["message"] = format_required_pick_message(required)
    return out


def check_required_position_gate(
    session: dict[str, Any],
    room: dict[str, Any] | None,
    *,
    on_clock_team: str,
    player_name: str = "",
) -> dict[str, Any]:
    """Gate helper for draft buttons — blocks ineligible players when enforcement is active."""
    enf = resolve_on_clock_enforcement(room, on_clock_team=on_clock_team)
    if not enf.get("active"):
        return {"allowed": True, **enf}
    if not str(player_name or "").strip():
        return {"allowed": True, **enf}
    try:
        from draft_actions import _find_live_player_row

        row = _find_live_player_row(session, player_name)
    except ImportError:
        row = None
    if player_eligible_for_required_positions(row, list(enf.get("required_positions") or [])):
        return {"allowed": True, **enf}
    return {"allowed": False, **enf}
