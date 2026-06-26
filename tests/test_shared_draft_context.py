"""Tests for shared draft context sync across draft pages."""

from __future__ import annotations

import unittest

from shared_draft_context import (
    GLOBAL_PROJECTION_STYLE_KEY,
    GLOBAL_WINDOW_KEY,
    has_active_draft_context,
    prepare_shared_draft_context,
    write_shared_draft_context,
)


class TestSharedDraftContext(unittest.TestCase):
    def test_inactive_without_draft(self) -> None:
        session: dict = {}
        self.assertFalse(has_active_draft_context(session))

    def test_active_with_live_room_picks(self) -> None:
        session = {
            "live_draft_room": {
                "status": "in_progress",
                "draft_board": [{"Pick": 1, "fullName": "Aaron Judge"}],
                "pick_order": [{"Pick": 1, "Team": "A"}],
            }
        }
        self.assertTrue(has_active_draft_context(session))

    def test_write_mirrors_lookback_and_projection(self) -> None:
        session: dict = {
            "live_draft_room": {
                "status": "in_progress",
                "draft_board": [{"Pick": 1, "fullName": "Player"}],
            },
            "draft_window": 3,
            "live_draft_proj_style": "Balanced",
        }
        write_shared_draft_context(
            session,
            lookback=5,
            projection_style="Aggressive",
            source_page="Live Draft Room",
            reason="test",
        )
        self.assertEqual(session[GLOBAL_WINDOW_KEY], 5)
        self.assertEqual(session["draft_window"], 5)
        self.assertEqual(session["live_draft_proj_window"], 5)
        self.assertEqual(session[GLOBAL_PROJECTION_STYLE_KEY], "Aggressive")
        self.assertEqual(session["live_draft_proj_style"], "Aggressive")

    def test_prepare_inherits_canonical_to_aliases(self) -> None:
        session = {
            "live_draft_room": {"status": "complete", "draft_board": [{"fullName": "X"}]},
            GLOBAL_WINDOW_KEY: 4,
            GLOBAL_PROJECTION_STYLE_KEY: "Conservative",
            "draft_window": 3,
        }
        prepare_shared_draft_context(session, active_page="Draft Assistant Simulator", force_mirror=True)
        self.assertEqual(session["draft_window"], 4)
        self.assertEqual(session["live_draft_proj_window"], 4)


if __name__ == "__main__":
    unittest.main()
