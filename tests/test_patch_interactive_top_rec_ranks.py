"""Unit: pool upgrade patches ranks onto frozen interactive snapshot (no remount)."""

from __future__ import annotations

import unittest

import pandas as pd

from live_draft_rec_live_paint import (
    INTERACTIVE_TOP_REC_SNAPSHOT_KEY,
    patch_interactive_top_rec_ranks_from_pool,
    store_interactive_top_rec_snapshot,
)


class PatchInteractiveRanksTests(unittest.TestCase):
    def test_patch_keeps_player_identity_and_updates_model_rank(self) -> None:
        snap = pd.DataFrame(
            [
                {
                    "fullName": "Francisco Lindor",
                    "playerID": "231",
                    "Primary Position": "SS",
                    "Market Rank": 12,
                    "Model Rank": 12,
                    "Fantasy Edge": 0,
                    "Expected Fantasy Value": 0.4,
                },
                {
                    "fullName": "Aaron Judge",
                    "playerID": "99",
                    "Primary Position": "OF",
                    "Market Rank": 1,
                    "Model Rank": 1,
                    "Fantasy Edge": 0,
                    "Expected Fantasy Value": 0.9,
                },
            ]
        )
        pool = pd.DataFrame(
            [
                {
                    "fullName": "Francisco Lindor",
                    "playerID": "231",
                    "Market Rank": 12,
                    "Model Rank": 5,
                    "Fantasy Edge": 7,
                    "Expected Fantasy Value": 0.82,
                    "Blended Projection Score": 91.0,
                },
                {
                    "fullName": "Aaron Judge",
                    "playerID": "99",
                    "Market Rank": 1,
                    "Model Rank": 2,
                    "Fantasy Edge": -1,
                    "Expected Fantasy Value": 0.95,
                    "Blended Projection Score": 99.0,
                },
            ]
        )
        session: dict = {}
        room = {"draft_room_id": "SOLOPATCH"}
        store_interactive_top_rec_snapshot(session, snap, room_id="SOLOPATCH")
        report = patch_interactive_top_rec_ranks_from_pool(session, room, pool)
        self.assertTrue(report["patched"])
        self.assertEqual(report["matched"], 2)
        self.assertGreaterEqual(report["model_ne_market"], 1)
        out = session[INTERACTIVE_TOP_REC_SNAPSHOT_KEY]["top_rec"]
        lindor = out[out["playerID"].astype(str) == "231"].iloc[0]
        self.assertEqual(int(lindor["Model Rank"]), 5)
        self.assertEqual(int(lindor["Market Rank"]), 12)
        self.assertEqual(int(lindor["Fantasy Edge"]), 7)
        # Identity unchanged — same players in same order (widget keys stable).
        self.assertEqual(list(out["playerID"].astype(str)), ["231", "99"])


if __name__ == "__main__":
    unittest.main()
