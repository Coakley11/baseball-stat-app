"""Session-only draft/league seed for local browser checks.

Activated only by ``?isolated_seed=c1b``. It does not read or write saved
drafts, live leagues, or Supabase. Pair it with ``SUITE_WORKSPACE_ID`` so any
accidental local autosave lands in a throwaway workspace.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

SEED_NAME = "c1b"
TEAM = "Seed Team"
OTHER = "Other Seed"
CATCHER_TO_DRAFT = "Cal Raleigh"
DRAFTED_BY_OTHER = ("Matt Olson", "Adley Rutschman", "Vladimir Guerrero Jr.")

MY_ROSTER = (
    "Ketel Marte",
    "Nolan Arenado",
    "Corey Seager",
    "Kyle Schwarber",
    "Yordan Alvarez",
    "Aaron Judge",
    "Shohei Ohtani",
)

SLOTS = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "BN": 2}


def _query_value(st: Any, key: str) -> str:
    try:
        raw = st.query_params.get(key)
    except Exception:
        return ""
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else ""
    return str(raw or "").strip()


def _board(extra: tuple[tuple[str, str], ...] = ()) -> pd.DataFrame:
    rows = []
    picks = [(TEAM, name) for name in MY_ROSTER] + [(OTHER, name) for name in DRAFTED_BY_OTHER]
    picks.extend(extra)
    for pick_no, (team, player) in enumerate(picks, start=1):
        rows.append({"Round": ((pick_no - 1) // 2) + 1, "Pick": pick_no, "Team": team, "Player": player})
    return pd.DataFrame(rows)


def _install_board(session: dict[str, Any], extra: tuple[tuple[str, str], ...] = ()) -> None:
    session["draft_room_table"] = _board(extra)
    session["room_your_team"] = TEAM
    session["room_team_count"] = 2
    session["room_team_names"] = f"{TEAM}\n{OTHER}"
    session["use_simulator_board_as_fantasy_context"] = True
    session["use_live_draft_as_fantasy_context"] = False
    session["live_draft_room"] = {
        "config": {"slots": dict(SLOTS), "fantasy_format": "5x5 Roto", "league_name": "Isolated Seed League"},
        "status": "seed",
    }
    session["draft_assistant_synced_team"] = TEAM
    session["draft_top_n"] = 8
    session["draft_assistant_rec_card_sort"] = session.get("draft_assistant_rec_card_sort") or "Roster Fit"


def _install_league(session: dict[str, Any]) -> None:
    from fantasy_league_context import (
        create_league_context_from_simulator_board,
        ensure_fantasy_league_context_state,
    )

    context = create_league_context_from_simulator_board(
        session,
        session["draft_room_table"],
        my_team_name=TEAM,
        config={"slots": dict(SLOTS), "fantasy_format": "5x5 Roto"},
        league_name="Isolated Seed League",
        display_name="Isolated Seed League",
        league_context_id="seed:c1b",
        persist=False,
    )
    store = ensure_fantasy_league_context_state(session)
    store.setdefault("contexts", {})[context["league_context_id"]] = context
    store["active_league_context_id"] = context["league_context_id"]


def _install_stats(session: dict[str, Any]) -> None:
    free_agents = [
        {"Player": "Mike Trout", "fullName": "Mike Trout", "Primary Position": "OF", "Eligible Positions": "OF", "MLB Team": "LAA", "HR": 18, "RBI": 48, "R": 42, "SB": 2, "BA": 0.265},
        {"Player": "Mookie Betts", "fullName": "Mookie Betts", "Primary Position": "OF", "Eligible Positions": "OF,2B", "MLB Team": "LAD", "HR": 12, "RBI": 40, "R": 55, "SB": 14, "BA": 0.275},
        {"Player": "Freddie Freeman", "fullName": "Freddie Freeman", "Primary Position": "1B", "Eligible Positions": "1B", "MLB Team": "LAD", "HR": 16, "RBI": 52, "R": 48, "SB": 4, "BA": 0.295},
        {"Player": "Pete Alonso", "fullName": "Pete Alonso", "Primary Position": "1B", "Eligible Positions": "1B", "MLB Team": "BAL", "HR": 22, "RBI": 58, "R": 44, "SB": 1, "BA": 0.250},
        {"Player": "Will Smith", "fullName": "Will Smith", "Primary Position": "C", "Eligible Positions": "C", "MLB Team": "LAD", "HR": 14, "RBI": 42, "R": 38, "SB": 2, "BA": 0.270},
        {"Player": "Cal Raleigh", "fullName": "Cal Raleigh", "Primary Position": "C", "Eligible Positions": "C", "MLB Team": "SEA", "HR": 20, "RBI": 50, "R": 36, "SB": 1, "BA": 0.240},
        {"Player": "William Contreras", "fullName": "William Contreras", "Primary Position": "C", "Eligible Positions": "C", "MLB Team": "MIL", "HR": 11, "RBI": 36, "R": 34, "SB": 3, "BA": 0.268},
    ]
    session["_fantasy_current_hitter_stats"] = pd.DataFrame(free_agents)


def apply_isolated_browser_seed(st: Any) -> None:
    if _query_value(st, "isolated_seed") != SEED_NAME:
        return
    session = st.session_state
    session["_isolated_browser_seed"] = SEED_NAME
    session["_suite_autosave_blocked::baseball"] = True
    extra: tuple[tuple[str, str], ...] = ()
    if _query_value(st, "isolated_action") == "draft_catcher" or session.get("_isolated_drafted_catcher"):
        extra = ((TEAM, CATCHER_TO_DRAFT),)
        if not session.get("_isolated_drafted_catcher"):
            session["_isolated_drafted_catcher"] = True
            session.pop("draft_need_positions_auto", None)
            session.pop("da_position_needs_overridden", None)
            session.pop("da_position_needs_auto_sig", None)
            try:
                from live_draft_ui_cache import DA_SCORING_CACHE_KEY

                session.pop(DA_SCORING_CACHE_KEY, None)
            except ImportError:
                session.pop("_draft_assistant_scoring_cache", None)
    _install_board(session, extra)
    _install_league(session)
    _install_stats(session)
    session["_isolated_seed_applied"] = True
    st.caption("Isolated seed c1b active. This session is not a saved league.")
