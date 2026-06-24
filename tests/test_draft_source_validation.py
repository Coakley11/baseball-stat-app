"""Tests for controlled draft source validation."""

from __future__ import annotations

import unittest

from draft_source_validation import (
    ALLOW_FREE_POOL_KEY,
    allowed_draft_player_names,
    gather_participant_draft_sources,
    is_allowed_draft_source,
    match_draft_source,
)


class DraftSourceValidationTests(unittest.TestCase):
    def test_match_queue_watchlist_tracked(self) -> None:
        sources = {
            "queue": ["Aaron Judge"],
            "watchlist": ["Juan Soto"],
            "tracked": ["Corbin Carroll"],
        }
        self.assertEqual(match_draft_source("Aaron Judge", sources), "queue")
        self.assertEqual(match_draft_source("Juan Soto (NYY)", sources), "watchlist")
        self.assertEqual(match_draft_source("corbin carroll", sources), "tracked")
        self.assertIsNone(match_draft_source("Mike Trout", sources))

    def test_free_pool_allows_any_name_when_enabled(self) -> None:
        session = {ALLOW_FREE_POOL_KEY: True, "draft_queue": []}
        ok, reason, src = is_allowed_draft_source(session, "Mike Trout")
        self.assertTrue(ok)
        self.assertEqual(src, "free_pool")
        self.assertEqual(reason, "")

    def test_restricted_to_private_sources(self) -> None:
        session = {
            ALLOW_FREE_POOL_KEY: False,
            "draft_queue": ["Aaron Judge"],
            "draft_assistant_focus_players": [],
            "workflow_recently_viewed": [],
        }
        ok, reason, src = is_allowed_draft_source(session, "Aaron Judge")
        self.assertTrue(ok)
        self.assertEqual(src, "queue")
        ok2, reason2, _ = is_allowed_draft_source(session, "Mike Trout")
        self.assertFalse(ok2)
        self.assertIn("Queue", reason2)

    def test_allowed_names_intersects_available(self) -> None:
        session = {
            ALLOW_FREE_POOL_KEY: False,
            "draft_queue": ["Aaron Judge", "Mike Trout"],
        }
        names = allowed_draft_player_names(
            session,
            available_names=["Aaron Judge", "Juan Soto"],
        )
        self.assertEqual(names, ["Aaron Judge"])


if __name__ == "__main__":
    unittest.main()
