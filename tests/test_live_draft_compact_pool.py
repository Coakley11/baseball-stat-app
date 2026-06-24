"""Tests for compact shared draft room pool serialization."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_scoring_pool import LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS
from live_draft_state import room_from_persist_dict, room_to_persist_dict


def _full_scoring_row() -> dict:
    return {
        "playerID": "p1",
        "fullName": "Aaron Judge",
        "Primary Position": "OF",
        "Team": "NYY",
        "Expected Fantasy Value": 0.91,
        "Model Rank": 8,
        "Market Rank": 15,
        "Fantasy Edge": 7,
        "ADP": 15,
        "Expert Std Dev": 4.0,
        "Sleeper Score": 0.62,
        "Scarcity Score": 0.44,
        "Projection Confidence Score": 0.8,
        "Trend Signal": 0.12,
        "proj_HR": 42,
        "proj_RBI": 98,
        "proj_R": 88,
        "proj_SB": 8,
        "proj_BA": 0.285,
        "proj_OPS": 0.920,
        "G": 140,
        "AB": 520,
        "extra_lahman_col": 999,
        "another_stat": 12345,
    }


class LiveDraftCompactPoolTests(unittest.TestCase):
    def test_compact_pool_preserves_scoring_columns_and_values(self) -> None:
        pool = pd.DataFrame([_full_scoring_row()])
        room = {"status": "in_progress", "pool": pool}
        compact = room_to_persist_dict(room, compact_pool=True)
        restored = room_from_persist_dict(compact)
        self.assertIsInstance(restored, dict)
        frame = restored.get("pool")
        self.assertIsInstance(frame, pd.DataFrame)
        assert isinstance(frame, pd.DataFrame)
        self.assertEqual(float(frame.loc[0, "Model Rank"]), 8.0)
        self.assertEqual(float(frame.loc[0, "Market Rank"]), 15.0)
        self.assertEqual(float(frame.loc[0, "Fantasy Edge"]), 7.0)
        self.assertIn("Sleeper Score", frame.columns)
        self.assertNotIn("extra_lahman_col", frame.columns)
        self.assertNotIn("another_stat", frame.columns)

    def test_compact_payload_much_smaller_than_full_pool(self) -> None:
        pool = pd.DataFrame([_full_scoring_row()])
        room = {"status": "in_progress", "pool": pool}
        full = room_to_persist_dict(room, compact_pool=False)
        compact = room_to_persist_dict(room, compact_pool=True)
        self.assertLess(len(compact["pool_columns"]), len(full["pool_columns"]))
        self.assertLessEqual(len(compact["pool_columns"]), len(LIVE_DRAFT_REQUIRED_PLAYER_COLUMNS))

    def test_manual_draft_sort_on_compact_pool(self) -> None:
        """Manual Draft sort by Expected Fantasy Value + Model Rank must not crash."""
        try:
            from streamlit_app import live_draft_get_available
        except ImportError:
            from Streamlit_app import live_draft_get_available  # type: ignore[no-redef]

        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "High Value",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.95,
                    "Model Rank": 3,
                    "Market Rank": 10,
                    "Fantasy Edge": 7,
                },
                {
                    "playerID": "p2",
                    "fullName": "Mid Value",
                    "Primary Position": "SP",
                    "Expected Fantasy Value": 0.80,
                    "Model Rank": 20,
                    "Market Rank": 25,
                    "Fantasy Edge": 5,
                },
            ]
        )
        room = {"status": "in_progress", "pool": pool, "drafted_player_ids": []}
        blob = room_to_persist_dict(room, compact_pool=True)
        restored = room_from_persist_dict(blob)
        assert isinstance(restored, dict)
        available = live_draft_get_available(restored)
        sorted_names = available.sort_values(
            ["Expected Fantasy Value", "Model Rank"], ascending=[False, True]
        )["fullName"].astype(str).tolist()
        self.assertEqual(sorted_names[0], "High Value")
        self.assertLess(float(available.loc[available["fullName"] == "High Value", "Model Rank"].iloc[0]), 9000)


if __name__ == "__main__":
    unittest.main()
