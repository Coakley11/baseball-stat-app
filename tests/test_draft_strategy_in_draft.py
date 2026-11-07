"""Draft Strategies inside drafts (2026-11-06): the viewer's strategy shapes the recommendation cards in
Solo and Live/Shared drafts; Balanced leaves them as scored; nothing reaches the room."""

from __future__ import annotations

import copy
import unittest

import pandas as pd
from streamlit.testing.v1 import AppTest

import draft_strategy_in_draft as sid


def pool() -> pd.DataFrame:
    # Two shortstops (scarce), six outfielders (deep), one catcher with a big roster fit.
    rows = [
        ("p1", "Big OF", "OF", 300, 90, 0.1, 0.1),
        ("p2", "OF Two", "OF", 290, 88, 0.1, 0.1),
        ("p3", "OF Three", "OF", 280, 86, 0.1, 0.1),
        ("p4", "OF Four", "OF", 270, 84, 0.1, 0.1),
        ("p5", "OF Five", "OF", 260, 82, 0.1, 0.1),
        ("p6", "OF Six", "OF", 250, 80, 0.1, 0.1),
        ("p7", "Top SS", "SS", 240, 85, 0.95, 0.2),
        ("p8", "Last SS", "SS", 120, 60, 0.95, 0.2),
        ("p9", "Need C", "C", 150, 70, 0.5, 0.99),
    ]
    return pd.DataFrame(rows, columns=["playerID", "fullName", "Primary Position", "Expected Fantasy Value",
                                       "Decision Score", "Position Scarcity Score", "Positional Fit"])


def room(drafted: tuple[str, ...] = ()) -> dict:
    board = [{"playerID": pid, "fullName": pid, "Pick": i + 1} for i, pid in enumerate(drafted)]
    return {"draft_room_id": "R1", "teams": ["A", "B"], "draft_board": board,
            "config": {"num_teams": 2, "slots": {"C": 1, "SS": 1, "OF": 3}}}


def tables(df: pd.DataFrame) -> tuple:
    e = pd.DataFrame()
    return (df.sort_values("Decision Score", ascending=False), e, e, e)


class RankingTests(unittest.TestCase):
    def test_balanced_is_the_default_and_changes_nothing(self) -> None:
        session: dict = {}
        t = tables(pool())
        self.assertEqual(sid.current_approach(session), "balanced")
        self.assertIs(sid.apply_strategy_to_recommendations(session, room(), t), t)

    def test_best_available_is_pure_projected_value(self) -> None:
        ranked = sid.rank_pool(pool(), "best_available", room=room())
        self.assertEqual(ranked["fullName"].tolist()[:3], ["Big OF", "OF Two", "OF Three"])
        self.assertEqual(ranked["Strategy Reason"].iloc[0], "Best available: #1 by projected value")

    def test_value_based_prefers_value_over_replacement(self) -> None:
        # 2 teams × 1 SS starter: replacement SS is the 2nd SS (120) → Top SS is +120;
        # 2 teams × 3 OF: replacement OF is the 6th (250) → Big OF is only +50.
        ranked = sid.rank_pool(pool(), "value_based", room=room())
        self.assertEqual(ranked["fullName"].iloc[0], "Top SS")
        self.assertEqual(ranked["Strategy Reason"].iloc[0], "Value-based: 40% above the SS replacement level")  # 120 of 300

    def test_positional_scarcity_lifts_the_thin_position(self) -> None:
        ranked = sid.rank_pool(pool(), "positional_scarcity", room=room())
        self.assertEqual(ranked["fullName"].iloc[0], "Top SS")
        self.assertIn("startable SS left", ranked["Strategy Reason"].iloc[0])

    def test_roster_aware_lifts_the_needed_position(self) -> None:
        ranked = sid.rank_pool(pool(), "roster_aware", room=room())
        self.assertEqual(ranked["fullName"].iloc[0], "Need C")
        self.assertEqual(ranked["Strategy Reason"].iloc[0], "Roster-aware: fills a C need")

    def test_only_this_drafts_available_players_and_the_room_is_untouched(self) -> None:
        session = {sid.APPROACH_KEY: "best_available"}
        r = room(drafted=("p1",))
        before = copy.deepcopy(r)
        sid.remember_scored_pool(session, r, pool())
        top = sid.apply_strategy_to_recommendations(session, r, tables(pool()), top_n=3)[0]
        self.assertNotIn("Big OF", top["fullName"].tolist())
        self.assertEqual(top["fullName"].iloc[0], "OF Two")
        self.assertEqual(r, before)  # the room never holds anyone's strategy

    def test_another_viewer_keeps_their_own_strategy(self) -> None:
        a, b = {sid.APPROACH_KEY: "roster_aware"}, {}
        r = room()
        top_a = sid.apply_strategy_to_recommendations(a, r, tables(pool()))[0]
        top_b = sid.apply_strategy_to_recommendations(b, r, tables(pool()))[0]
        self.assertEqual(top_a["fullName"].iloc[0], "Need C")
        self.assertEqual(top_b["fullName"].iloc[0], "Big OF")

    def test_the_card_reason_leads_with_the_strategy(self) -> None:
        from live_draft_room_ui import build_why_this_pick_summary

        row = sid.rank_pool(pool(), "value_based", room=room()).iloc[0]
        self.assertTrue(build_why_this_pick_summary(row, "SS").startswith("Value-based: 40% above the SS replacement level"))


def _selector_script() -> None:
    import streamlit as st

    import draft_strategy_in_draft as sid

    import draft_strategy_store

    draft_strategy_store.list_strategies = lambda _s: [{"id": "1", "name": "Punt saves", "approach": "positional_scarcity"}]
    sid.render_strategy_selector(st, st.session_state, key_prefix="t")
    st.write("approach:", sid.current_approach(st.session_state))


class SelectorTests(unittest.TestCase):
    def test_defaults_to_balanced_and_a_saved_strategy_applies_its_approach(self) -> None:
        at = AppTest.from_function(_selector_script, default_timeout=30)
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state[sid.APPROACH_KEY], "balanced")
        saved = next(s for s in at.selectbox if s.key == "t_saved_strategy_select")
        saved.select("Punt saves").run()
        self.assertEqual(at.session_state[sid.APPROACH_KEY], "positional_scarcity")
        self.assertTrue(any("Positional scarcity" in str(c.value) for c in at.caption))


if __name__ == "__main__":
    unittest.main()
