"""Recommendation Rankings tables were empty while the recommendation cards were full (owner review, 2026-11-08).

Causes:
* The "Why this pick" enrichment cache was keyed by the board fingerprint only, so one run's empty tables were
  served for the whole pick.
* Light, timer-owned and poll-applied pick runs never recomputed the tables, while the cards rebuilt from their
  own fallback.
* A Solo-only flag leaked into Shared drafts.

These tests pin the fixes: tables come from the cards' cache or this pick's scored pool, drafted players never
appear, and an empty tab explains itself. Scoring and Auto Pick are untouched.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

import live_draft_rankings_tables as rt
from draft_strategy_in_draft import SCORED_POOL_KEY, _pick_marker
from live_draft_ui_cache import REC_CACHE_KEY, WHY_COLUMN_CACHE_KEY, enrich_live_draft_recommendations_with_why

APP = (Path(__file__).resolve().parents[1] / "streamlit_app.py").read_text(encoding="utf-8")


def _pool(names, positions=None) -> pd.DataFrame:
    n = len(names)
    return pd.DataFrame({
        "playerID": [f"id{i}" for i in range(n)], "fullName": names,
        "Primary Position": positions or ["OF"] * n,
        "Decision Score": [1 - i / 10 for i in range(n)], "Expected Fantasy Value": [100 - i for i in range(n)],
        "Positional Fit": [0.5] * n, "Draft Fit Score": [0.5] * n, "Sleeper Score": [i / 10 for i in range(n)],
    })


ROOM = {"draft_room_id": "qa-room", "draft_board": []}
EMPTY = {n: pd.DataFrame() for n in rt.NAMES}


class WhyCacheTests(unittest.TestCase):
    def test_empty_then_full_under_the_same_board_key_returns_the_full_tables(self) -> None:
        session: dict = {}
        key = ("board", 3)
        first = enrich_live_draft_recommendations_with_why(session, key, dict(EMPTY))
        self.assertTrue(all(df.empty for df in first.values()))
        self.assertNotIn(WHY_COLUMN_CACHE_KEY, session)  # "nothing" is never cached
        full = dict(zip(rt.NAMES, rt.split_recommendation_tables(_pool(["Aaron Judge", "Juan Soto"]), ["OF"], 10)))
        second = enrich_live_draft_recommendations_with_why(session, key, full)
        self.assertEqual(len(second["top_rec"]), 2)

    def test_cached_enrichment_is_reused_only_for_the_same_tables(self) -> None:
        session: dict = {}
        key = ("board", 3)
        a = dict(zip(rt.NAMES, rt.split_recommendation_tables(_pool(["Aaron Judge", "Juan Soto"]), None, 10)))
        b = dict(zip(rt.NAMES, rt.split_recommendation_tables(_pool(["Kyle Schwarber"]), None, 10)))
        enrich_live_draft_recommendations_with_why(session, key, a)
        got = enrich_live_draft_recommendations_with_why(session, key, b)
        self.assertEqual(list(got["top_rec"]["fullName"]), ["Kyle Schwarber"])


class FillTests(unittest.TestCase):
    def test_empty_tables_are_filled_from_the_cards_cache(self) -> None:
        cached = dict(zip(rt.NAMES, rt.split_recommendation_tables(_pool(["Aaron Judge", "Juan Soto"]), None, 10)))
        session = {REC_CACHE_KEY: {"key": ("k",), **cached}}
        out, source = rt.fill_missing_ranking_tables(session, ROOM, dict(EMPTY))
        self.assertEqual(source, "cards_cache")
        for n in ("top_rec", "best_avail", "value_sleep"):
            self.assertEqual(len(out[n]), 2, n)
        self.assertTrue(out["pos_fit"].empty)  # no positional gaps: a real answer, explained in the tab

    def test_empty_tables_are_rebuilt_from_this_picks_scored_pool(self) -> None:
        session = {SCORED_POOL_KEY: {"pick": _pick_marker(ROOM), "df": _pool(["Aaron Judge", "Trea Turner"], ["OF", "SS"])}}
        out, source = rt.fill_missing_ranking_tables(session, ROOM, dict(EMPTY), gaps=["SS"])
        self.assertEqual(source, "scored_pool")
        self.assertEqual(list(out["pos_fit"]["fullName"]), ["Trea Turner"])
        self.assertEqual(len(out["best_avail"]), 2)

    def test_a_previous_picks_pool_is_not_used(self) -> None:
        session = {SCORED_POOL_KEY: {"pick": ("qa-room", 7), "df": _pool(["Aaron Judge"])}}
        out, source = rt.fill_missing_ranking_tables(session, ROOM, dict(EMPTY))
        self.assertEqual(source, "current")
        self.assertTrue(out["top_rec"].empty)

    def test_drafted_players_never_appear(self) -> None:
        room = {"draft_room_id": "qa-room", "draft_board": [], "drafted_player_ids": ["id0"]}
        cached = dict(zip(rt.NAMES, rt.split_recommendation_tables(_pool(["Aaron Judge", "Juan Soto"]), None, 10)))
        out, _ = rt.fill_missing_ranking_tables({REC_CACHE_KEY: cached}, room, dict(EMPTY))
        self.assertEqual(list(out["top_rec"]["fullName"]), ["Juan Soto"])

    def test_full_tables_are_left_as_they_are(self) -> None:
        tables = dict(zip(rt.NAMES, rt.split_recommendation_tables(_pool(["Aaron Judge"]), ["OF"], 10)))
        out, source = rt.fill_missing_ranking_tables({}, ROOM, tables, gaps=["OF"])
        self.assertEqual(source, "current")
        self.assertEqual(list(out["top_rec"]["fullName"]), ["Aaron Judge"])

    def test_split_matches_the_scoring_pass(self) -> None:
        pool = _pool(["A", "B", "C"])
        top, best, pos, sleep = rt.split_recommendation_tables(pool, None, 2)
        self.assertEqual(list(top["fullName"]), ["A", "B"])
        self.assertEqual(list(sleep["fullName"]), ["C", "B"])  # by Sleeper Score
        self.assertTrue(pos.empty)


class PageTests(unittest.TestCase):
    def test_empty_tabs_explain_themselves(self) -> None:
        self.assertEqual(rt.empty_tab_message("pos_fit", gaps=[]), rt.NO_POSITIONAL_NEED)
        self.assertEqual(rt.empty_tab_message("top_rec", gaps=["SS"]), rt.REFRESHING)
        for n in ("top_rec", "best_avail", "pos_fit", "value_sleep"):
            self.assertIn(f'_rank_empty_msg("{n}", gaps=_gaps)', APP)
        self.assertNotIn('st.caption("Rankings ready.")', APP)

    def test_the_paint_step_fills_from_the_cards_data_and_the_solo_flag_is_per_run(self) -> None:
        self.assertIn("fill_missing_ranking_tables(", APP)
        start = APP.index('st.session_state.pop("_live_draft_team_needs_rendered", None)\n        # Same for the Solo')
        self.assertIn('st.session_state.pop("_solo_recs_deferred_for_timer", None)', APP[start:start + 400])


if __name__ == "__main__":
    unittest.main()
