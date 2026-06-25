"""Pending handoff staging — never mutate widget keys after render."""

from __future__ import annotations

import unittest

from draft_lab_handoff import apply_live_draft_handoff_to_session
from draft_lab_state import (
    PENDING_DRAFT_LAB_HANDOFF_KEY,
    apply_pending_draft_lab_widget_keys,
    has_pending_draft_lab_handoff,
    prepare_draft_lab_page_widgets,
    stage_draft_lab_handoff_settings,
)


def _sample_room() -> dict:
    return {
        "draft_room_id": "AB12CD34",
        "status": "complete",
        "teams": ["Ariel", "Daniel"],
        "draft_board": [{"playerID": "p1"}, {"playerID": "p2"}],
        "config": {
            "num_teams": 2,
            "picks_per_team": 4,
            "scoring_type": "Roto (5x5)",
            "projection_style": "Aggressive",
            "projection_window": 4,
        },
    }


class DraftLabHandoffPendingTests(unittest.TestCase):
    def test_handoff_stages_without_touching_widget_keys(self) -> None:
        session: dict = {"draft_lab_window": 3}
        apply_live_draft_handoff_to_session(session, _sample_room())
        self.assertTrue(has_pending_draft_lab_handoff(session))
        self.assertEqual(session["draft_lab_window"], 3)
        pending = session[PENDING_DRAFT_LAB_HANDOFF_KEY]
        self.assertEqual(pending["draft_lab_window"], 4)
        self.assertEqual(pending["draft_lab_picks_per_team"], 4)

    def test_apply_pending_before_widget_creation(self) -> None:
        session: dict = {}
        stage_draft_lab_handoff_settings(
            session,
            {
                "draft_lab_window": 5,
                "draft_lab_scoring_type": "Points League",
                "draft_lab_projection_style": "Balanced",
                "draft_lab_picks_per_team": 12,
            },
        )
        self.assertNotIn("draft_lab_window", session)
        self.assertTrue(apply_pending_draft_lab_widget_keys(session))
        self.assertEqual(session["draft_lab_window"], 5)
        self.assertEqual(session["draft_lab_scoring_type"], "Points League")
        self.assertEqual(session["draft_lab_picks_per_team"], 12)
        self.assertFalse(has_pending_draft_lab_handoff(session))

    def test_prepare_draft_lab_page_widgets_applies_pending_then_defaults(self) -> None:
        session: dict = {}
        stage_draft_lab_handoff_settings(session, {"draft_lab_window": 4, "draft_lab_picks_per_team": 8})
        prepare_draft_lab_page_widgets(session)
        self.assertEqual(session["draft_lab_window"], 4)
        self.assertEqual(session["draft_lab_picks_per_team"], 8)
        self.assertIn("draft_lab_scoring_type", session)

    def test_resume_hydration_does_not_mutate_existing_widget_state(self) -> None:
        """Simulate widget already bound — handoff stays pending until pre-widget apply."""
        session: dict = {"draft_lab_window": 3, "draft_lab_scoring_type": "5x5 Roto"}
        apply_live_draft_handoff_to_session(session, _sample_room())
        self.assertEqual(session["draft_lab_window"], 3)
        prepare_draft_lab_page_widgets(session)
        self.assertEqual(session["draft_lab_window"], 4)


if __name__ == "__main__":
    unittest.main()
