"""Tests for cross-app blob candidate selection."""

from __future__ import annotations

import unittest

from suite_analytical_question import _select_best_blob_payload


class TestBlobCandidateSelection(unittest.TestCase):
    def test_prefers_richer_pool_when_timestamps_equal(self) -> None:
        sparse = {
            "payload_hash": "sparse1111",
            "blob_diagnostics": {"available_players_count": 0, "current_pick": 1},
            "context": {"current_pick": 1, "draft_snapshot": {}},
        }
        rich = {
            "payload_hash": "rich222222",
            "saved_at": "2026-05-27T12:00:00+00:00",
            "blob_diagnostics": {"available_players_count": 51, "current_pick": 8},
            "context": {"current_pick": 8, "available_players": [{}] * 51},
        }
        picked = _select_best_blob_payload(
            [
                ("2026-05-27T12:00:00+00:00", "applied_intelligence", sparse),
                ("2026-05-27T12:00:00+00:00", "baseball", rich),
            ]
        )
        self.assertIsNotNone(picked)
        assert picked is not None
        self.assertEqual(picked.get("blob_store_app"), "baseball")
        self.assertEqual(picked.get("payload_hash"), "rich222222")
        self.assertIn("blob_load_candidates", picked)

    def test_prefers_newer_timestamp(self) -> None:
        older = {
            "payload_hash": "old111111",
            "blob_diagnostics": {"available_players_count": 51},
            "context": {"available_players": [{}] * 51},
        }
        newer = {
            "payload_hash": "new222222",
            "blob_diagnostics": {"available_players_count": 51},
            "context": {"available_players": [{}] * 51},
        }
        picked = _select_best_blob_payload(
            [
                ("2026-05-27T10:00:00+00:00", "applied_intelligence", older),
                ("2026-05-27T12:00:00+00:00", "baseball", newer),
            ]
        )
        self.assertEqual(picked.get("payload_hash"), "new222222")


if __name__ == "__main__":
    unittest.main()
