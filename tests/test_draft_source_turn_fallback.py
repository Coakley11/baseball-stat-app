"""Manual draft full-pool fallback on your turn when commissioner mode is off."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from draft_source_validation import (
    ALLOW_FREE_POOL_KEY,
    allowed_draft_player_names,
    is_allowed_draft_source,
    manual_draft_full_pool_on_your_turn,
)


class DraftSourceTurnFallbackTests(unittest.TestCase):
    @patch("draft_actions.draft_action_context")
    def test_manual_draft_full_pool_on_your_turn(self, mock_ctx: object) -> None:
        mock_ctx.return_value = {
            "live_draft_active": True,
            "is_your_pick": True,
            "draft_status": "in_progress",
        }
        session = {ALLOW_FREE_POOL_KEY: False}
        self.assertTrue(manual_draft_full_pool_on_your_turn(session, live_room={"config": {}}))

    @patch("draft_actions.draft_action_context")
    def test_restricted_source_allows_pool_player_on_your_turn(self, mock_ctx: object) -> None:
        mock_ctx.return_value = {
            "live_draft_active": True,
            "is_your_pick": True,
            "draft_status": "in_progress",
        }
        session = {ALLOW_FREE_POOL_KEY: False, "draft_queue": []}
        ok, reason, src = is_allowed_draft_source(session, "Mike Trout", live_room={"config": {ALLOW_FREE_POOL_KEY: False}})
        self.assertTrue(ok, reason)
        self.assertEqual(src, "full_pool_turn_fallback")

    @patch("draft_actions.draft_action_context")
    def test_allowed_names_fallback_on_your_turn(self, mock_ctx: object) -> None:
        mock_ctx.return_value = {
            "live_draft_active": True,
            "is_your_pick": True,
            "draft_status": "in_progress",
        }
        session = {ALLOW_FREE_POOL_KEY: False, "draft_queue": []}
        names = allowed_draft_player_names(
            session,
            live_room={"config": {ALLOW_FREE_POOL_KEY: False}},
            available_names=["Aaron Judge", "Mike Trout"],
        )
        self.assertEqual(names, ["Aaron Judge", "Mike Trout"])


if __name__ == "__main__":
    unittest.main()
