"""Draft Board Market Rank / Fantasy Edge consistency (hosted phone screenshot 2026-10-26).

Auto-picked players showed Model Rank 8, Market Rank None, Fantasy Edge +22: the auto-pick
saved a trimmed pick record without Market Rank, while Fantasy Edge (Market Rank - Model Rank,
computed on the full pool row: Market Rank 30) was kept.
"""

from __future__ import annotations

import unittest

import pandas as pd

from live_draft_autopick import _row_to_candidate


def _board_df(room):
    import streamlit_app as app

    return app.live_draft_build_board_df(room)


class AutoPickRecordTests(unittest.TestCase):
    def test_slim_auto_pick_record_keeps_market_rank(self) -> None:
        row = pd.Series({"playerID": "p1", "fullName": "Auto Pick", "Model Rank": 8, "Market Rank": 30,
                         "Fantasy Edge": 22, "ADP": 29.5, "Projected HR": 30})
        cand = _row_to_candidate(row, slim=True)
        self.assertEqual((cand["Model Rank"], cand["Market Rank"], cand["Fantasy Edge"]), (8, 30, 22))
        self.assertNotIn("Projected HR", cand)


class BoardRankColumnsTests(unittest.TestCase):
    def _room(self, pick: dict, pool_rows: list[dict] | None = None) -> dict:
        room = {"draft_board": [{"Round": 1, "Pick": 1, "Fantasy Team": "Team A", "playerID": "p1",
                                 "fullName": "Auto Pick", **pick}]}
        if pool_rows is not None:
            room["pool"] = pd.DataFrame(pool_rows)
        return room

    def test_saved_board_missing_market_rank_is_filled_from_the_pool(self) -> None:
        df = _board_df(self._room({"Model Rank": 8, "Fantasy Edge": 22},
                                  [{"playerID": "p1", "Model Rank": 8, "Market Rank": 30}]))
        row = df.iloc[0]
        self.assertEqual((row["Model Rank"], row["Market Rank"], row["Fantasy Edge"]), (8, 30, 22))

    def test_no_market_rank_anywhere_means_no_edge(self) -> None:
        df = _board_df(self._room({"Model Rank": 8, "Fantasy Edge": 22}))
        row = df.iloc[0]
        self.assertTrue(pd.isna(row["Market Rank"]))
        self.assertTrue(pd.isna(row["Fantasy Edge"]))

    def test_placeholder_rank_is_not_shown_as_a_rank(self) -> None:
        df = _board_df(self._room({"Model Rank": 8, "Market Rank": 9999, "Fantasy Edge": 9991}))
        row = df.iloc[0]
        self.assertTrue(pd.isna(row["Market Rank"]))
        self.assertTrue(pd.isna(row["Fantasy Edge"]))

    def test_complete_human_pick_is_unchanged(self) -> None:
        df = _board_df(self._room({"Model Rank": 12, "Market Rank": 9, "Fantasy Edge": -3}))
        row = df.iloc[0]
        self.assertEqual((row["Model Rank"], row["Market Rank"], row["Fantasy Edge"]), (12, 9, -3))


if __name__ == "__main__":
    unittest.main()
