"""Tests for shared draft context sync across draft pages."""

from __future__ import annotations

import unittest

from shared_draft_context import (
    GLOBAL_PROJECTION_STYLE_KEY,
    GLOBAL_WINDOW_KEY,
    is_draft_sync_page,
    prepare_shared_draft_context,
    write_shared_draft_context,
)


class TestSharedDraftContext(unittest.TestCase):
    def test_draft_sync_pages(self) -> None:
        self.assertTrue(is_draft_sync_page("Draft Assistant Simulator"))
        self.assertFalse(is_draft_sync_page("Historical Explorer"))

    def test_write_mirrors_lookback_and_projection_without_active_draft(self) -> None:
        session: dict = {"draft_window": 3, "live_draft_proj_style": "Balanced"}
        write_shared_draft_context(
            session,
            lookback=5,
            projection_style="Conservative",
            source_page="Draft Assistant Simulator",
            reason="test",
        )
        self.assertEqual(session[GLOBAL_WINDOW_KEY], 5)
        self.assertEqual(session["draft_window"], 5)
        self.assertEqual(session["live_draft_proj_window"], 5)
        self.assertEqual(session["fantasy_market_window"], 5)
        self.assertEqual(session[GLOBAL_PROJECTION_STYLE_KEY], "Conservative")
        self.assertEqual(session["live_draft_proj_style"], "Conservative")
        self.assertEqual(session["draft_lab_projection_style"], "Conservative")

    def test_prepare_inherits_canonical_to_aliases_on_draft_page(self) -> None:
        session = {
            GLOBAL_WINDOW_KEY: 4,
            GLOBAL_PROJECTION_STYLE_KEY: "Conservative",
            "draft_window": 3,
            "draft_lab_window": 3,
        }
        prepare_shared_draft_context(session, active_page="Draft Assistant Simulator", force_mirror=True)
        self.assertEqual(session["draft_window"], 4)
        self.assertEqual(session["live_draft_proj_window"], 4)
        self.assertEqual(session["draft_lab_window"], 4)

    def test_prepare_skips_research_pages(self) -> None:
        session = {
            GLOBAL_WINDOW_KEY: 5,
            "draft_window": 3,
        }
        prepare_shared_draft_context(session, active_page="Historical Explorer", force_mirror=True)
        self.assertEqual(session["draft_window"], 3)


if __name__ == "__main__":
    unittest.main()
