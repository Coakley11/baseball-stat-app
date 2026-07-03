"""Tests for performance pass part 2 instrumentation and caches."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from fantasy_perf_cache import (
    get_cached_lineup_scores,
    get_cached_standings_results,
    lineup_scores_cache_key,
    store_lineup_scores,
    store_standings_results,
)
from live_draft_ui_cache import (
    enrich_live_draft_recommendations_with_why,
    live_draft_ui_cache_key,
    WHY_COLUMN_CACHE_KEY,
)
from page_perf_phases import record_cache_event, record_perf_phase, top_slow_phases


class PagePerfPhasesTests(unittest.TestCase):
    def test_record_and_rank_phases_when_dev_enabled(self) -> None:
        session: dict = {"_suite_dev_mode": True}
        with patch("page_perf_phases.dev_perf_enabled", return_value=True):
            record_perf_phase(session, "projection_pool", 0.5)
            record_perf_phase(session, "live_draft_recommendations", 1.2)
            record_cache_event(session, "live_draft_recommendations", hit=True)
            top = top_slow_phases(session, limit=2)
        self.assertEqual(top[0][0], "live_draft_recommendations")
        audit = session.get("_page_perf_cache_audit") or []
        self.assertTrue(any(row.get("label") == "live_draft_recommendations" for row in audit))


class LiveDraftWhyCacheTests(unittest.TestCase):
    def test_why_columns_cached_for_same_pick(self) -> None:
        session: dict = {}
        ui_key = (1, 2, "Team A", 10)
        tables = {
            "top_rec": pd.DataFrame([{"fullName": "Player A", "Primary Position": "OF"}]),
        }
        with patch("live_draft_room_ui.add_why_this_pick_column") as mock_why:
            mock_why.side_effect = lambda df, **_: df.assign(**{"Why this pick": ["reason"]})
            first = enrich_live_draft_recommendations_with_why(session, ui_key, tables)
            second = enrich_live_draft_recommendations_with_why(session, ui_key, tables)
        self.assertEqual(mock_why.call_count, 1)
        self.assertIn("Why this pick", first["top_rec"].columns)
        self.assertIn(WHY_COLUMN_CACHE_KEY, session)
        pd.testing.assert_frame_equal(first["top_rec"], second["top_rec"])


class LiveDraftCacheKeyTests(unittest.TestCase):
    def test_queue_changes_do_not_bust_recommendation_cache(self) -> None:
        room = {
            "current_pick_index": 3,
            "draft_board": [{"Pick": 1}, {"Pick": 2}],
            "config": {"slots": {"OF": 3}, "fantasy_format": "5x5 Roto"},
            "rosters": {"Team A": []},
            "meta": {"sync": {"revision": 1}},
        }
        session_a: dict = {"draft_queue": ["Aaron Judge"]}
        session_b: dict = {"draft_queue": ["Juan Soto"]}
        key_a = live_draft_ui_cache_key(session_a, room, top_n=10, team="Team A")
        key_b = live_draft_ui_cache_key(session_b, room, top_n=10, team="Team A")
        self.assertEqual(key_a, key_b)


class FantasyPerfCacheTests(unittest.TestCase):
    def test_standings_results_round_trip(self) -> None:
        session: dict = {}
        roster = pd.DataFrame([{"Team": "A", "Player": "X", "HR": 1}])
        standings = pd.DataFrame([{"Team": "A", "Total Roto Points": 10}])
        key = ("", "sig", "MLB API Auto-Fetch", 2026, "5x5 Roto", "stats_sig")
        store_standings_results(session, key, roster, standings)
        r2, s2 = get_cached_standings_results(session, key)
        assert r2 is not None and s2 is not None
        self.assertEqual(len(r2), 1)
        self.assertEqual(len(s2), 1)

    def test_lineup_scores_round_trip(self) -> None:
        session: dict = {}
        scored = pd.DataFrame([{"Player": "X", "Lineup Confidence": 0.9}])
        key = lineup_scores_cache_key(
            team="Team A",
            lineup_format="5x5 Roto",
            roster_sig="abc",
            custom_weights=None,
            slot_sig="C,1B,OF",
        )
        store_lineup_scores(session, key, scored)
        cached = get_cached_lineup_scores(session, key)
        assert cached is not None
        self.assertEqual(len(cached), 1)


if __name__ == "__main__":
    unittest.main()
