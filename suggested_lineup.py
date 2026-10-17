"""Use Suggested Lineup: copy the Lineup Assistant's recommended starters onto the lineup board.

The suggestion is the Recommended Starters list (``fantasy_lineup_scoring``: start/sit scores +
``build_position_aware_lineup``, which uses the same slot rule as Save Lineup). Applying it only
fills the editable board and stores it as an in-progress draft — exactly what dragging every
player would do. It never saves, locks or finalizes a lineup: the user reviews the board and
presses Save Lineup.
"""

from __future__ import annotations

import re
from typing import Any, Callable

import pandas as pd

BUILDER_SLOTS = ("C", "1B", "2B", "3B", "SS", "OF", "UTIL")


def _builder_slot(base_slot: str) -> str:
    base = str(base_slot or "").strip().upper()
    return "UTIL" if base in ("DH", "UTIL", "DH/UTIL") else base


def suggested_assignments(slot_labels: list[Any], team_roster: pd.DataFrame, *,
                          scoring_format: str = "5x5 Roto") -> tuple[dict[str, str], list[str]]:
    """(slot key → player, slots left empty). Slots the hitter builder can't fill (pitchers,
    bench) are left empty and reported."""
    from fantasy_lineup_scoring import build_lineup_assistant_scores, build_position_aware_lineup
    from fantasy_slot_eligibility import enrich_lineup_roster_positions

    keys = [(str(label.key), _builder_slot(label.base_slot)) for label in slot_labels]
    assignments = {key: "" for key, _ in keys}
    if team_roster is None or team_roster.empty:
        return assignments, [base for _, base in keys]
    scored = enrich_lineup_roster_positions(build_lineup_assistant_scores(team_roster, scoring_format))
    builder_slots = [base for _, base in keys if base in BUILDER_SLOTS]
    package = build_position_aware_lineup(scored, slots=builder_slots)
    queues: dict[str, list[str]] = {}
    lineup_df = package.get("lineup_df")
    if isinstance(lineup_df, pd.DataFrame) and not lineup_df.empty:
        for _, row in lineup_df.iterrows():
            base = re.sub(r"\d+$", "", str(row.get("Fantasy slot") or ""))
            name = str(row.get("Player") or row.get("fullName") or "").strip()
            if name:
                queues.setdefault(base, []).append(name)
    unfilled: list[str] = []
    for key, base in keys:
        queue = queues.get(base) or []
        if queue:
            assignments[key] = queue.pop(0)
        else:
            unfilled.append(base)
    return assignments, unfilled


def apply_suggested_lineup(
    session: Any,
    *,
    week: int,
    slots: list[str],
    slot_labels: list[Any],
    team_roster: pd.DataFrame,
    team: str,
    scoring_format: str = "5x5 Roto",
    write_check: Callable[[], tuple[bool, str]] | None = None,
) -> dict[str, Any]:
    """Fill the board with the suggestion and keep it as a draft (never a saved lineup).

    Returns {ok, assignments, unfilled, message, errors}. The caller puts ``assignments`` on
    the board; validation (``validate_weekly_lineup``) runs on it like any board edit.
    """
    from fantasy_weekly_lineup import persist_weekly_lineup_draft

    if write_check is not None:
        ok, err = write_check()
        if not ok:
            return {"ok": False, "assignments": None, "unfilled": [], "message": "", "errors": [err]}
    assignments, unfilled = suggested_assignments(slot_labels, team_roster, scoring_format=scoring_format)
    result = persist_weekly_lineup_draft(session, week=int(week), slots=list(slots), assignments=assignments,
                                         my_team=team, roster_df=team_roster)
    if not result.get("ok"):
        return {"ok": False, "assignments": None, "unfilled": unfilled, "message": "",
                "errors": list(result.get("errors") or ["Could not fill the lineup."])}
    message = "Suggested lineup filled in. Review it, then press Save Lineup — nothing is saved until you do."
    return {"ok": True, "assignments": assignments, "unfilled": unfilled, "message": message, "errors": []}
