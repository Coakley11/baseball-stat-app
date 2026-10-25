"""Tests for Live Draft Room -> Draft Lab handoff settings."""

from __future__ import annotations

import unittest

from draft_lab_handoff import apply_live_draft_handoff_to_session, extract_live_room_lab_settings, live_room_lab_settings_keys


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
            "projection_window": 3,
        },
    }


class DraftLabHandoffTests(unittest.TestCase):
    def test_extracts_live_room_settings(self) -> None:
        session = {"active_shared_draft_room_code": "0LD6RH"}
        extracted = extract_live_room_lab_settings(_sample_room(), session)
        self.assertEqual(extracted["draft_lab_team_count"], 2)
        self.assertEqual(extracted["draft_lab_picks_per_team"], 4)
        self.assertEqual(extracted["draft_lab_window"], 3)
        self.assertEqual(extracted["draft_lab_scoring_type"], "5x5 Roto")
        self.assertEqual(extracted["draft_lab_projection_style"], "Aggressive")
        self.assertEqual(extracted["room_code"], "0LD6RH")
        self.assertEqual(extracted["board_pick_count"], 2)
        self.assertEqual(extracted["expected_pick_count"], 8)

    def test_apply_populates_session_keys(self) -> None:
        session: dict = {"live_draft_room": _sample_room()}
        meta = apply_live_draft_handoff_to_session(session, _sample_room())
        from draft_lab_state import apply_pending_draft_lab_widget_keys

        apply_pending_draft_lab_widget_keys(session)
        self.assertEqual(session["draft_lab_window"], 3)
        self.assertEqual(session["draft_lab_scoring_type"], "5x5 Roto")
        self.assertEqual(session["draft_lab_projection_style"], "Aggressive")
        self.assertEqual(session["draft_lab_picks_per_team"], 4)
        self.assertEqual(session["draft_lab_team_count"], 2)
        self.assertEqual(meta["team_count"], 2)
        self.assertEqual(meta["picks_per_team"], 4)

    def test_live_to_lab_keys_from_room(self) -> None:
        session = {"live_draft_room": _sample_room()}
        keys = live_room_lab_settings_keys(session)
        self.assertEqual(keys["draft_lab_team_count"], 2)
        self.assertEqual(keys["draft_lab_picks_per_team"], 4)

    def test_push_completed_live_draft_to_lab(self) -> None:
        session: dict = {}
        room = _sample_room()
        ok = __import__("draft_lab_handoff", fromlist=["push_completed_live_draft_to_lab"]).push_completed_live_draft_to_lab(
            session, room
        )
        self.assertTrue(ok)
        self.assertIn("draft_lab_results", session)
        self.assertFalse(getattr(session["draft_lab_results"].get("draft"), "empty", True))


if __name__ == "__main__":
    unittest.main()
