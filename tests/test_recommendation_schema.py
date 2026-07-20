"""Regression: recommendation ranking schema — never KeyError on sort columns."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from recommendation_schema import (
    SORT_CRITICAL_COLUMNS,
    USER_REC_UNAVAILABLE,
    ensure_recommendation_ranking_schema,
    missing_ranking_columns,
    safe_sort_recommendations,
    score_or_empty_recommendations,
)


def _raw_pool(*, positions: list[str] | None = None) -> pd.DataFrame:
    positions = positions or ["C", "1B", "OF", "P"]
    rows = []
    for i, pos in enumerate(positions):
        rows.append(
            {
                "playerID": f"p{i}",
                "fullName": f"Player {i}",
                "Primary Position": pos,
                "Expected Fantasy Value": float(100 - i),
                "Model Rank": i + 1,
                "Market Rank": i + 1,
                "Fantasy Edge": float(5 - i),
                "Sleeper Score": float(i),
            }
        )
    return pd.DataFrame(rows)


class RecommendationSchemaTests(unittest.TestCase):
    def test_available_lacking_draft_fit_score_safe_sort(self) -> None:
        available = _raw_pool()
        self.assertIn("Draft Fit Score", missing_ranking_columns(available))
        ranked = safe_sort_recommendations(available, ["Draft Fit Score"], ascending=False)
        self.assertIsInstance(ranked, pd.DataFrame)
        self.assertIn("Draft Fit Score", ranked.columns)

    def test_balanced_lacking_decision_score_safe_sort(self) -> None:
        balanced = _raw_pool()
        # Simulate partial scored frame missing Decision Score / Draft Fit Score.
        out = safe_sort_recommendations(
            balanced, ["Decision Score", "Expected Fantasy Value"], ascending=[False, False]
        )
        self.assertFalse(out.empty)
        self.assertIn("Decision Score", out.columns)

    def test_empty_eligible_pool(self) -> None:
        scored, gaps, diag = score_or_empty_recommendations(
            pd.DataFrame(), pd.DataFrame(), path="empty"
        )
        self.assertTrue(scored.empty)
        self.assertEqual(diag.get("status"), "empty_pool")

    def test_one_row_pool_scoring_or_empty(self) -> None:
        pool = _raw_pool(positions=["OF"])

        def _fake_score(available, roster_df, **kwargs):
            out = available.copy()
            out["Draft Fit Score"] = 50.0
            out["Decision Score"] = 50.0
            out["Positional Fit"] = 1.0
            return out, ["OF"]

        scored, gaps, diag = score_or_empty_recommendations(
            pool, pd.DataFrame(), score_fn=_fake_score, path="one_row"
        )
        self.assertEqual(len(scored), 1)
        self.assertEqual(diag.get("status"), "ok")
        self.assertEqual(gaps, ["OF"])

    def test_hitter_only_and_pitcher_only(self) -> None:
        for positions in (["C", "1B", "OF"], ["P", "P", "P"]):
            pool = _raw_pool(positions=positions)
            ensured = ensure_recommendation_ranking_schema(pool)
            for col in SORT_CRITICAL_COLUMNS:
                self.assertIn(col, ensured.columns)
            sorted_df = safe_sort_recommendations(
                ensured, ["Draft Fit Score", "Decision Score"], ascending=False
            )
            self.assertEqual(len(sorted_df), len(positions))

    def test_unscored_nonempty_fails_closed(self) -> None:
        pool = _raw_pool()

        def _unscored(available, roster_df, **kwargs):
            return available.copy(), []

        scored, _gaps, diag = score_or_empty_recommendations(
            pool, pd.DataFrame(), score_fn=_unscored, path="unscored"
        )
        self.assertTrue(scored.empty)
        self.assertEqual(diag.get("status"), "missing_after_score")
        self.assertIn("Draft Fit Score", diag.get("missing_ranking_columns") or [])

    def test_scoring_exception_fails_closed(self) -> None:
        pool = _raw_pool()

        def _boom(available, roster_df, **kwargs):
            raise RuntimeError("score pipeline broken")

        session: dict = {}
        scored, _gaps, diag = score_or_empty_recommendations(
            pool, pd.DataFrame(), score_fn=_boom, path="boom", session=session
        )
        self.assertTrue(scored.empty)
        self.assertEqual(diag.get("status"), "scoring_failed")
        self.assertEqual(session.get("_recommendation_schema_diag", {}).get("status"), "scoring_failed")

    def test_user_message_has_no_traceback_language(self) -> None:
        self.assertNotIn("Manage app", USER_REC_UNAVAILABLE)
        self.assertNotIn("traceback", USER_REC_UNAVAILABLE.lower())
        self.assertNotIn("KeyError", USER_REC_UNAVAILABLE)


class LiveDraftRecommendationsNoCrashTests(unittest.TestCase):
    def test_sort_sites_tolerate_unscored_balanced(self) -> None:
        from live_draft_recommendations import _live_draft_recommendations_impl

        room = {
            "status": "in_progress",
            "current_pick_index": 0,
            "config": {
                "num_teams": 2,
                "picks_per_team": 5,
                "fantasy_format": "5x5 Roto",
                "your_team": "Team A",
                "slots": {"C": 1, "OF": 1, "P": 1, "BN": 1},
            },
            "teams": ["Team A", "Team B"],
            "pick_order": [
                {"Pick": 1, "Round": 1, "Team": "Team A"},
                {"Pick": 2, "Round": 1, "Team": "Team B"},
            ],
            "draft_board": [],
            "rosters": {"Team A": [], "Team B": []},
            "drafted_player_ids": [],
            "pool": _raw_pool(),
        }

        def _unscored(available, roster_df, **kwargs):
            return available.copy(), ["OF"]

        session: dict = {}
        with patch(
            "live_draft_pick_scoring.apply_draft_pick_scoring",
            side_effect=_unscored,
        ):
            with patch(
                "live_draft_pick_scoring.enrich_player_survival_metrics",
                side_effect=lambda df, **kw: df,
            ):
                tables = _live_draft_recommendations_impl(room, top_n=3, session=session)
        for frame in tables:
            self.assertIsInstance(frame, pd.DataFrame)
        # Fail closed → empty tables, no KeyError.
        self.assertTrue(all(f.empty for f in tables))

    def test_live_draft_recommendations_exception_boundary(self) -> None:
        from live_draft_recommendations import live_draft_recommendations

        session: dict = {}
        with patch(
            "live_draft_recommendations._live_draft_recommendations_impl",
            side_effect=KeyError("Decision Score"),
        ):
            tables = live_draft_recommendations({}, top_n=3, session=session)
        self.assertEqual(len(tables), 4)
        self.assertTrue(all(t.empty for t in tables))
        self.assertIn("KeyError", session.get("_live_draft_recommendations_error") or "")


class OldCachedSchemaTests(unittest.TestCase):
    def test_old_cache_without_ranking_columns_is_safe(self) -> None:
        stale = pd.DataFrame(
            [{"playerID": "x", "fullName": "Stale", "Primary Position": "OF"}]
        )
        # Mimic Draft Assistant sort sites.
        if missing_ranking_columns(stale):
            ranked = pd.DataFrame()
        else:
            ranked = safe_sort_recommendations(stale, ["Draft Fit Score"], ascending=False)
        self.assertTrue(ranked.empty)


if __name__ == "__main__":
    unittest.main()
