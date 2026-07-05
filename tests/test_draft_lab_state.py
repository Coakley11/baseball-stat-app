"""Tests for Draft Simulation Test Mode widget key seeding before save."""
from __future__ import annotations

import unittest
from pathlib import Path

import page_state as pg
from draft_lab_state import DRAFT_LAB_PAGE, DRAFT_LAB_RESULT_TABS, ensure_draft_lab_widget_keys, sync_draft_lab_session_before_save


class TestDraftLabWidgetSeeding(unittest.TestCase):
    def test_ensure_seeds_page_only_keys(self) -> None:
        session: dict = {"page_filter_state": {}}
        ensure_draft_lab_widget_keys(session)
        for key in (
            "draft_lab_picks_per_team",
            "draft_lab_roster_team",
            "draft_lab_active_tab",
        ):
            self.assertIn(key, session)

    def test_ensure_restores_page_only_keys_from_snapshot(self) -> None:
        session = {
            "page_filter_state": {
                DRAFT_LAB_PAGE: {
                    "draft_lab_picks_per_team": 20,
                    "draft_lab_roster_team": "Team B",
                    "draft_lab_active_tab": "Team Analysis",
                }
            }
        }
        ensure_draft_lab_widget_keys(session)
        self.assertEqual(session["draft_lab_picks_per_team"], 20)
        self.assertEqual(session["draft_lab_roster_team"], "Team B")
        self.assertEqual(session["draft_lab_active_tab"], "Team Analysis")

    def test_save_page_state_after_onchange_seeds_full_snapshot(self) -> None:
        """Simulate on_change: only the changed widget is in session; others must still save."""
        from shared_draft_context import write_canonical_draft_settings

        session = {
            "page_filter_state": {
                DRAFT_LAB_PAGE: {
                    "draft_lab_picks_per_team": 20,
                }
            },
            "draft_lab_window": 5,
            "draft_lab_scoring_type": "Points League",
        }
        write_canonical_draft_settings(
            session,
            lookback_window=5,
            fantasy_format="Points League",
            source_page="Draft Lab / Simulation",
        )
        ensure_draft_lab_widget_keys(session)
        sync_draft_lab_session_before_save(session)
        self.assertEqual(session["draft_lab_scoring_type"], "Points League")
        pg.save_page_state(session, DRAFT_LAB_PAGE, session["page_filter_state"])
        snap = session["page_filter_state"][DRAFT_LAB_PAGE]
        self.assertEqual(snap.get("draft_lab_picks_per_team"), 20)
        self.assertIn("draft_lab_roster_team", snap)
        self.assertEqual(session.get("_draft_lab_picks_per_team_value"), snap.get("draft_lab_picks_per_team"))


class TestDraftLabResultTabs(unittest.TestCase):
    def test_no_trade_simulator_tab(self) -> None:
        self.assertNotIn("Trade Simulator", DRAFT_LAB_RESULT_TABS)

    def test_draft_analysis_tabs_present(self) -> None:
        for label in (
            "Draft Board",
            "Team Rosters",
            "Team Analysis",
            "Best / Questionable Picks",
            "Exports",
        ):
            self.assertIn(label, DRAFT_LAB_RESULT_TABS)

    def test_exports_is_last_tab(self) -> None:
        self.assertEqual(DRAFT_LAB_RESULT_TABS[-1], "Exports")
        self.assertEqual(len(DRAFT_LAB_RESULT_TABS), 5)

    def test_trade_helper_still_available_globally(self) -> None:
        from streamlit_app import suggest_draft_lab_trades

        self.assertTrue(callable(suggest_draft_lab_trades))

    def test_trade_analyzer_page_unchanged(self) -> None:
        app_path = Path(__file__).resolve().parents[1] / "streamlit_app.py"
        source = app_path.read_text(encoding="utf-8")
        self.assertIn("Trade Analyzer / Roster Move Assistant", source)
        self.assertNotIn('"Trade Simulator", "Exports"', source)


if __name__ == "__main__":
    unittest.main()
