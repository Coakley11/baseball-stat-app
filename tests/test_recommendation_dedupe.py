"""Tests for recommendation_dedupe — featured cards vs follow-on lists."""

from __future__ import annotations

import unittest

import pandas as pd

from recommendation_dedupe import (
    add_recommendation_rank_column,
    collect_featured_player_ids,
    ensure_top_raw_value_in_recommendations,
    exclude_recommendation_player_ids,
    recommendation_player_id,
    remaining_recommendations,
)


def _rows(*specs):
    return pd.DataFrame(
        [
            {
                "playerID": pid,
                "fullName": name,
                "Draft Fit Score": score,
                "Expected Fantasy Value": score,
            }
            for pid, name, score in specs
        ]
    )


class TestRecommendationPlayerId(unittest.TestCase):
    def test_prefers_player_id(self):
        row = pd.Series({"playerID": "592450", "fullName": "Aaron Judge"})
        self.assertEqual(recommendation_player_id(row), "592450")

    def test_falls_back_to_name(self):
        row = pd.Series({"fullName": "Aaron Judge"})
        self.assertEqual(recommendation_player_id(row), "name:aaron judge")


class TestRecommendationDedupe(unittest.TestCase):
    def test_excludes_two_featured_players(self):
        ranked = _rows(
            ("1", "Shohei Ohtani", 95),
            ("2", "Aaron Judge", 90),
            ("3", "Juan Soto", 88),
            ("4", "Kyle Schwarber", 85),
        )
        featured = collect_featured_player_ids(ranked.head(1), ranked.iloc[1:2])
        remaining = remaining_recommendations(ranked, featured, limit=10)
        self.assertEqual(remaining["playerID"].tolist(), ["3", "4"])

    def test_same_player_featured_once(self):
        ranked = _rows(
            ("1", "Shohei Ohtani", 95),
            ("2", "Aaron Judge", 90),
            ("3", "Juan Soto", 88),
        )
        same = ranked.head(1)
        featured = collect_featured_player_ids(same, same)
        self.assertEqual(featured, {"1"})
        remaining = remaining_recommendations(ranked, featured, limit=10)
        self.assertEqual(remaining["playerID"].tolist(), ["2", "3"])

    def test_limit_preserves_count_after_exclusion(self):
        ranked = _rows(
            ("1", "A", 10),
            ("2", "B", 9),
            ("3", "C", 8),
            ("4", "D", 7),
            ("5", "E", 6),
        )
        featured = {"1", "2"}
        remaining = remaining_recommendations(ranked, featured, limit=3)
        self.assertEqual(len(remaining), 3)
        self.assertEqual(remaining["playerID"].tolist(), ["3", "4", "5"])

    def test_dedupe_by_id_not_name(self):
        ranked = pd.DataFrame(
            [
                {"playerID": "99", "fullName": "Duplicate Name", "Draft Fit Score": 10},
                {"playerID": "2", "fullName": "Other", "Draft Fit Score": 9},
            ]
        )
        featured = collect_featured_player_ids(pd.DataFrame([{"playerID": "99", "fullName": "Other Spelling"}]))
        out = exclude_recommendation_player_ids(ranked, featured)
        self.assertEqual(out["playerID"].tolist(), ["2"])

    def test_rank_column_starts_after_featured(self):
        df = _rows(("3", "Juan Soto", 88), ("4", "Kyle Schwarber", 85))
        ranked_display = add_recommendation_rank_column(df, start_rank=3)
        self.assertEqual(ranked_display["Rank"].tolist(), [3, 4])

    def test_ranked_head_includes_featured_players(self):
        ranked = _rows(
            ("1", "Shohei Ohtani", 95),
            ("2", "Aaron Judge", 90),
            ("3", "Juan Soto", 88),
        )
        table = ranked.head(3)
        self.assertEqual(table["playerID"].tolist(), ["1", "2", "3"])
        ranked_display = add_recommendation_rank_column(table, start_rank=1)
        self.assertEqual(ranked_display["Rank"].tolist(), [1, 2, 3])

    def test_top_pick_matches_table_first_row(self) -> None:
        """Draft Assistant table row #1 must match the top ranked recommendation."""
        ranked = _rows(
            ("1", "Shohei Ohtani", 95),
            ("2", "Aaron Judge", 90),
            ("3", "Juan Soto", 88),
        )
        best_fit = ranked.head(1)
        table = ranked.head(3)
        self.assertEqual(
            recommendation_player_id(best_fit.iloc[0]),
            recommendation_player_id(table.iloc[0]),
        )
        self.assertEqual(str(best_fit.iloc[0]["fullName"]), str(table.iloc[0]["fullName"]))


class TestDraftAssistantDedupeImports(unittest.TestCase):
    """Regression: streamlit_app.py Draft Assistant block imports these symbols (~18874)."""

    def test_streamlit_import_symbols_exist(self) -> None:
        from recommendation_dedupe import (
            add_recommendation_rank_column,
            collect_featured_player_ids,
            ensure_top_raw_value_in_recommendations,
            recommendation_player_id,
            remaining_recommendations,
        )

        for fn in (
            add_recommendation_rank_column,
            collect_featured_player_ids,
            ensure_top_raw_value_in_recommendations,
            recommendation_player_id,
            remaining_recommendations,
        ):
            self.assertTrue(callable(fn))

    def test_ensure_top_raw_value_in_recommendations(self) -> None:
        available = _rows(
            ("99", "Shohei Ohtani", 0.99),
            ("2", "Aaron Judge", 0.90),
            ("3", "Juan Soto", 0.88),
        )
        recs = available.sort_values("Expected Fantasy Value", ascending=False).iloc[1:].copy()
        out = ensure_top_raw_value_in_recommendations(recs, available, limit=2)
        self.assertEqual(out.iloc[0]["playerID"], "99")


if __name__ == "__main__":
    unittest.main()
