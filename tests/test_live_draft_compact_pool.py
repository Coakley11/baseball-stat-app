"""Tests for compact shared draft room pool serialization."""

from __future__ import annotations

import unittest

import pandas as pd

from live_draft_state import SHARED_DRAFT_POOL_COLUMNS, room_to_persist_dict


class LiveDraftCompactPoolTests(unittest.TestCase):
    def test_compact_pool_keeps_minimal_columns(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "Aaron Judge",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 95.0,
                    "ADP": 12,
                    "Team": "NYY",
                    "extra_stat": 999,
                }
            ]
        )
        room = {"status": "in_progress", "pool": pool}
        full = room_to_persist_dict(room, compact_pool=False)
        compact = room_to_persist_dict(room, compact_pool=True)

        self.assertIn("ADP", full["pool_columns"])
        self.assertEqual(
            compact["pool_columns"],
            ["playerID", "fullName", "Primary Position", "Expected Fantasy Value"],
        )
        self.assertNotIn("ADP", compact["pool_columns"])
        self.assertEqual(compact["pool_records"][0]["playerID"], "p1")
        self.assertNotIn("extra_stat", compact["pool_records"][0])

    def test_compact_pool_keeps_scoring_columns_when_present(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "Aaron Judge",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 95.0,
                    "Fantasy Edge": 8.0,
                    "Model Rank": 12,
                    "Market Rank": 20,
                    "Sleeper Score": 0.4,
                    "Expert Std Dev": 3.0,
                    "Team": "NYY",
                }
            ]
        )
        room = {"status": "in_progress", "pool": pool}
        compact = room_to_persist_dict(room, compact_pool=True)
        self.assertEqual(compact["pool_columns"], list(SHARED_DRAFT_POOL_COLUMNS))
        self.assertEqual(compact["pool_records"][0]["Fantasy Edge"], 8.0)
        self.assertNotIn("Team", compact["pool_columns"])


if __name__ == "__main__":
    unittest.main()
