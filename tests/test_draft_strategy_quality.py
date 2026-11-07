"""Draft Strategy quality on realistic drafts (2026-11-06).

The real-app harness draft (4 teams, snake order, slots C/1B/2B/3B/SS/OF×3) scored by the app's own
live_draft_recommendations, with real picks made by the pick engine. Checks what the owner asked:
Balanced unchanged; Best player available by projected value; Value-based replacement from league
size × starting slots; Scarcity from the remaining pool; Roster-aware reacting to the team's roster;
bounded bonuses; drafted players excluded; private per-manager selections; changing the strategy
leaves the queue, the draft and other preferences alone.
"""

from __future__ import annotations

import copy
import unittest

import pandas as pd
from streamlit.testing.v1 import AppTest

import draft_strategy_in_draft as sid
from live_draft_pick_engine import live_draft_make_pick
from live_draft_recommendations import live_draft_recommendations
from tests import live_draft_real_app_harness as h

APPROACHES = ("balanced", "best_available", "value_based", "positional_scarcity", "roster_aware")


def scored(room: dict, session: dict, team: str = "Team A") -> tuple:
    tables = live_draft_recommendations(room, top_n=8, team=team, session=session)
    return tables, session[sid.SCORED_POOL_KEY]["df"]


def pick(room: dict, player_id: str) -> None:
    pool = room["pool"]
    ok, msg = live_draft_make_pick(room, pool[pool["playerID"] == player_id].iloc[0].to_dict(), "Manual pick",
                                   enrich_pick_context=False)
    assert ok, msg


def top_for(approach: str, room: dict, session: dict, n: int = 8) -> pd.DataFrame:
    tables, _pool = scored(room, session)
    session[sid.APPROACH_KEY] = approach
    return sid.apply_strategy_to_recommendations(session, room, tables, top_n=n)[0]


class StrategyQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.room = h.active_room("solo")

    def test_balanced_preserves_the_draft_assistant_recommendations(self) -> None:
        session: dict = {}
        tables, _ = scored(self.room, session)
        self.assertIs(sid.apply_strategy_to_recommendations(session, self.room, tables), tables)

    def test_best_available_ranks_by_projected_value(self) -> None:
        top = top_for("best_available", self.room, {})
        values = pd.to_numeric(top["Expected Fantasy Value"]).tolist()
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertEqual(top["Strategy Reason"].iloc[0], "Best available: #1 by projected value")

    def test_value_based_replacement_comes_from_league_size_and_starting_slots(self) -> None:
        session: dict = {}
        _tables, pool = scored(self.room, session)
        ranked = sid.rank_pool(pool, "value_based", room=self.room)
        teams, of_starters = 4, 3  # harness: 4 teams, slots OF=3
        ofs = pd.to_numeric(pool[pool["Primary Position"] == "OF"]["Expected Fantasy Value"]).sort_values(ascending=False)
        replacement = float(ofs.iloc[min(teams * of_starters, len(ofs)) - 1])
        best_of = ranked[ranked["Primary Position"] == "OF"].iloc[0]
        expected = round((float(best_of["Expected Fantasy Value"]) - replacement) / float(pd.to_numeric(pool["Expected Fantasy Value"]).max()) * 100)
        self.assertEqual(best_of["Strategy Reason"], f"Value-based: {expected}% above the OF replacement level")

    def test_positional_scarcity_reads_the_remaining_pool(self) -> None:
        # Outfield has 3 slots per team, so it stays eligible while its remaining pool shrinks.
        left = lambda reason: int(reason.split(": ")[1].split(" ")[0])  # noqa: E731
        _t, pool = scored(self.room, {})
        before = sid.rank_pool(pool, "positional_scarcity", room=self.room)
        of_before = left(before[before["Primary Position"] == "OF"]["Strategy Reason"].iloc[0])
        for pid in self.room["pool"].query("`Primary Position` == 'OF'")["playerID"].tolist()[:4]:
            pick(self.room, pid)
        _t, pool_after = scored(self.room, {})
        after = sid.rank_pool(pool_after, "positional_scarcity", room=self.room)
        of_after = left(after[after["Primary Position"] == "OF"]["Strategy Reason"].iloc[0])
        self.assertEqual(of_after, of_before - 4)  # four outfielders drafted, four fewer left

    def test_roster_aware_responds_to_the_teams_actual_roster(self) -> None:
        # Team A (picks 1, 8, 9, 16 in the snake) drafts outfielders; roster-aware then stops leading with OF.
        order = [s["Team"] for s in self.room["pick_order"]]
        of_ids = self.room["pool"].query("`Primary Position` == 'OF'")["playerID"].tolist()
        other_ids = [p for p in self.room["pool"].query("`Primary Position` != 'OF'")["playerID"].tolist()]
        for i in range(16):
            pick(self.room, of_ids.pop(0) if order[i] == "Team A" else other_ids.pop(0))
        session: dict = {}
        tables, pool = scored(self.room, session, team="Team A")
        session[sid.APPROACH_KEY] = "roster_aware"
        top = sid.apply_strategy_to_recommendations(session, self.room, tables, top_n=5)[0]
        # Scoring already drops a position the team has filled; roster-aware never leads with it.
        positions = set(pool["Primary Position"].astype(str))
        if "OF" in positions:
            fit = pool.groupby("Primary Position")["Positional Fit"].max()
            self.assertLess(float(fit["OF"]), float(fit.drop("OF").max()))
        self.assertNotIn("OF", top["Primary Position"].tolist())

    def test_bonuses_stay_bounded(self) -> None:
        session: dict = {}
        _t, pool = scored(self.room, session)
        best = float(pd.to_numeric(pool["Expected Fantasy Value"]).max())
        for approach in APPROACHES[1:]:
            top = sid.rank_pool(pool, approach, room=self.room).iloc[0]
            self.assertGreaterEqual(float(top["Expected Fantasy Value"]), 0.5 * best, approach)

    def test_drafted_players_are_never_recommended(self) -> None:
        for pid in ("p001", "p002", "p003"):
            pick(self.room, pid)
        drafted = {"Player 001", "Player 002", "Player 003"}
        for approach in APPROACHES:
            top = top_for(approach, self.room, {}, n=20)
            self.assertFalse(drafted & set(top["fullName"].tolist()), approach)

    def test_managers_keep_private_selections_and_the_room_is_untouched(self) -> None:
        a, b = {}, {}
        tables_a, _ = scored(self.room, a)
        tables_b, _ = scored(self.room, b)
        before = copy.deepcopy({k: v for k, v in self.room.items() if k != "pool"})  # after scoring
        a[sid.APPROACH_KEY], b[sid.APPROACH_KEY] = "value_based", "balanced"
        top_a = sid.apply_strategy_to_recommendations(a, self.room, tables_a)[0]
        top_b = sid.apply_strategy_to_recommendations(b, self.room, tables_b)[0]
        self.assertEqual(a[sid.APPROACH_KEY], "value_based")
        self.assertEqual(b[sid.APPROACH_KEY], "balanced")
        self.assertIn("Strategy Reason", top_a.columns)
        self.assertNotIn("Strategy Reason", top_b.columns)
        self.assertEqual({k: v for k, v in self.room.items() if k != "pool"}, before)


def _change_strategy_script() -> None:
    import streamlit as st

    import draft_strategy_in_draft as sid

    ss = st.session_state
    if "draft_queue" not in ss:
        ss["draft_queue"] = ["Player 010", "Player 004", "Player 007"]
        ss["live_draft_room"] = {"draft_room_id": "R", "current_pick_index": 3, "draft_board": [{"Pick": 1}]}
        ss["projection_window"] = "3y"
    sid.render_strategy_selector(st, ss, key_prefix="t")


class ChangingStrategyTests(unittest.TestCase):
    def test_changing_strategy_keeps_queue_order_draft_state_and_preferences(self) -> None:
        at = AppTest.from_function(_change_strategy_script, default_timeout=30)
        at.run()
        before = {k: copy.deepcopy(at.session_state[k]) for k in ("draft_queue", "live_draft_room", "projection_window")}
        at.selectbox(key=sid.APPROACH_KEY).select("value_based").run()
        at.run()  # a rerun keeps the choice
        self.assertEqual(at.session_state[sid.APPROACH_KEY], "value_based")
        self.assertEqual({k: at.session_state[k] for k in before}, before)


if __name__ == "__main__":
    unittest.main()
