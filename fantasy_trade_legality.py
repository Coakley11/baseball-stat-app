"""Roster legality of a proposed trade, for both teams.

A trade is never blocked here — leagues allow empty spots — but each side is told when
the trade leaves its roster unable to fill a required lineup slot it could fill before,
or moves it over / under the roster size. Only gaps the trade creates are reported.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd


def _player_positions(player: dict[str, Any], lookup: dict[str, str]) -> list[str]:
    """Stored positions plus the feed's data-driven eligibility for this player."""
    from fantasy_position_eligibility import split_positions
    from fantasy_waiver_wire import _player_identity_keys

    positions = set(split_positions(player.get("positions") or []))
    for key in _player_identity_keys(player.get("player_name")):
        if key in lookup:
            positions.update(split_positions(lookup[key]))
            break
    return sorted(positions)


def _position_lookup(stats_pool: pd.DataFrame | None) -> dict[str, str]:
    """identity key -> eligible positions ("OF, DH") from the current stats feed."""
    if stats_pool is None or getattr(stats_pool, "empty", True):
        return {}
    from fantasy_position_eligibility import eligible_positions_from_row, format_positions
    from fantasy_waiver_wire import _player_identity_keys, _player_name_col

    name_col = _player_name_col(stats_pool)
    if name_col not in stats_pool.columns:
        return {}
    lookup: dict[str, str] = {}
    for _, row in stats_pool.iterrows():
        positions = eligible_positions_from_row(row)
        if not positions:
            continue
        for key in _player_identity_keys(row.get(name_col)):
            lookup.setdefault(key, format_positions(positions))
    return lookup


def _same_player(a: str, b: str) -> bool:
    from fantasy_waiver_wire import _player_identity_keys

    return bool(_player_identity_keys(a) & _player_identity_keys(b))


def _team_label(team: str, my_team: str) -> str:
    return "your team" if team and team == my_team else team


def _slot_gap_message(label: str, slot: str, missing: int, required: int) -> str:
    if required == 1:
        return f"This trade leaves {label} without an eligible {slot} for the required lineup."
    have = max(0, required - missing)
    return (
        f"This trade leaves {label} with {have} eligible {slot} for the {required} {slot} spots "
        "in the required lineup."
    )


def trade_roster_warnings(
    context: dict[str, Any] | None,
    *,
    proposer_team: str,
    recipient_team: str,
    proposer_gives: list[str],
    proposer_receives: list[str],
    stats_pool: pd.DataFrame | None = None,
) -> list[str]:
    """Legality warnings for both rosters after the trade (empty list = no new problems)."""
    return [
        issue["message"]
        for issue in trade_roster_issues(
            context,
            proposer_team=proposer_team,
            recipient_team=recipient_team,
            proposer_gives=proposer_gives,
            proposer_receives=proposer_receives,
            stats_pool=stats_pool,
        )
    ]


def trade_roster_issues(
    context: dict[str, Any] | None,
    *,
    proposer_team: str,
    recipient_team: str,
    proposer_gives: list[str],
    proposer_receives: list[str],
    stats_pool: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    """The same checks as ``trade_roster_warnings``, one record per warning:
    ``team``, ``kind`` ("slot": a required lineup slot it can no longer fill; "over": above
    the roster size, so a drop is needed; "under": open roster spots), ``slot`` and ``message``."""
    if not isinstance(context, dict):
        return []
    rosters = context.get("league_rosters") or {}
    proposer = str(proposer_team or "").strip()
    recipient = str(recipient_team or "").strip()
    if not isinstance(rosters, dict) or proposer not in rosters or recipient not in rosters:
        return []
    from fantasy_lineup_fill import unfilled_slots
    from fantasy_weekly_lineup import resolve_weekly_lineup_slots

    try:
        from fantasy_league_lineup_format import roster_capacity_from_format

        capacity = roster_capacity_from_format(context)
    except ImportError:
        capacity = None
    slots = list(resolve_weekly_lineup_slots(context) or [])
    lookup = _position_lookup(stats_pool)
    my_team = str(context.get("my_team_name") or "").strip()

    def players(team: str) -> list[dict[str, Any]]:
        return [p for p in ((rosters.get(team) or {}).get("players") or []) if isinstance(p, dict)]

    def moving(team: str, names: list[str]) -> list[dict[str, Any]]:
        return [p for p in players(team) if any(_same_player(str(p.get("player_name") or ""), n) for n in names)]

    warnings: list[dict[str, Any]] = []
    for team, out_names, other, in_names in (
        (proposer, proposer_gives, recipient, proposer_receives),
        (recipient, proposer_receives, proposer, proposer_gives),
    ):
        before = players(team)
        leaving = moving(team, out_names)
        arriving = moving(other, in_names)
        after = [p for p in before if p not in leaving] + arriving
        label = _team_label(team, my_team)
        if slots:
            open_before = Counter(unfilled_slots([_player_positions(p, lookup) for p in before], slots))
            open_after = Counter(unfilled_slots([_player_positions(p, lookup) for p in after], slots))
            required = Counter(slots)
            for slot in sorted(open_after, key=slots.index):
                new_gap = open_after[slot] - open_before.get(slot, 0)
                if new_gap > 0:
                    warnings.append({"team": team, "kind": "slot", "slot": slot,
                                     "message": _slot_gap_message(label, slot, open_after[slot], required[slot])})
        if capacity:
            size = len(after)
            if size > capacity and size > len(before):
                warnings.append({"team": team, "kind": "over", "slot": "", "message": (
                    f"{label[0].upper() + label[1:]} would carry {size} players — {size - capacity} over the "
                    f"{capacity}-player roster, so a drop will be needed."
                )})
            elif size < capacity and size < len(before):
                spots = capacity - size
                warnings.append({"team": team, "kind": "under", "slot": "", "message": (
                    f"{label[0].upper() + label[1:]} would carry {size} players, leaving "
                    f"{spots} open roster spot{'s' if spots != 1 else ''}."
                )})
    return warnings
