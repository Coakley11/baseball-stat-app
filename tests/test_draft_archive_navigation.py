"""Tests for Saved Draft Library fantasy page navigation helpers."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_archive_ui import (
    FANTASY_LINEUP_PAGE,
    FANTASY_STANDINGS_PAGE,
    schedule_fantasy_analysis_navigation,
)
from fantasy_league_context import (
    PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY,
    apply_pending_league_context_activation,
    save_simulator_league_context,
)


class DraftArchiveNavigationTests(unittest.TestCase):
    def test_schedule_fantasy_analysis_navigation_sets_pending_and_target(self) -> None:
        session: dict = {}
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1}])
        save_simulator_league_context(session, board, my_team_name="Daniel")
        self.assertTrue(schedule_fantasy_analysis_navigation(session, FANTASY_STANDINGS_PAGE))
        self.assertEqual(session["_navigate_to_page"], FANTASY_STANDINGS_PAGE)
        self.assertEqual(session["_skip_page_restore_for"], FANTASY_STANDINGS_PAGE)
        self.assertIn(PENDING_LEAGUE_CONTEXT_ACTIVATION_KEY, session)
        apply_pending_league_context_activation(session)
        self.assertEqual(session.get("room_your_team"), "Daniel")

    def test_schedule_fantasy_analysis_navigation_without_active_context(self) -> None:
        session: dict = {}
        self.assertFalse(schedule_fantasy_analysis_navigation(session, FANTASY_LINEUP_PAGE))


if __name__ == "__main__":
    unittest.main()
