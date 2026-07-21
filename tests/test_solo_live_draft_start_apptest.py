"""Rendered AppTest: click Start New Live Draft and assert UI / session outcomes."""

from __future__ import annotations

import unittest
from pathlib import Path

from fantasy_roster_validation import LIVE_DRAFT_SETUP_ERROR
from live_draft_start_setup import SETUP_VALIDATION_ERROR_KEY, gate_start_new_live_draft_click

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "solo_live_draft_start_apptest.py"


def _five_slot_session(**overrides):
    session = {
        "live_draft_setup_mode": "solo",
        "live_draft_picks_per_team": 4,
        "live_slot_c": 1,
        "live_slot_1b": 1,
        "live_slot_2b": 1,
        "live_slot_3b": 0,
        "live_slot_ss": 1,
        "live_slot_of": 1,
        "live_slot_dh": 0,
        "live_slot_p": 0,
        "live_slot_bench": 0,
    }
    session.update(overrides)
    return session


class GateStartClickPathTests(unittest.TestCase):
    def test_invalid_click_stores_error_and_does_not_arm_pending(self) -> None:
        session = _five_slot_session(live_draft_picks_per_team=4)
        gate = gate_start_new_live_draft_click(session)
        self.assertFalse(gate["armed"])
        self.assertFalse(gate["ok"])
        self.assertEqual(gate["error"], LIVE_DRAFT_SETUP_ERROR)
        self.assertEqual(session.get(SETUP_VALIDATION_ERROR_KEY), LIVE_DRAFT_SETUP_ERROR)
        self.assertFalse(bool(session.get("_start_live_draft_pending")))

    def test_valid_click_arms_pending(self) -> None:
        session = _five_slot_session(live_draft_picks_per_team=5)
        gate = gate_start_new_live_draft_click(session)
        self.assertTrue(gate["armed"])
        self.assertTrue(gate["ok"])
        self.assertTrue(session.get("_start_live_draft_pending"))
        self.assertFalse(session.get(SETUP_VALIDATION_ERROR_KEY))

    def test_resumable_slot_blocks_pending_but_invalid_still_errors_first(self) -> None:
        session = _five_slot_session(live_draft_picks_per_team=4)
        session["resumable_live_draft_slot"] = {
            "kind": "resumable_live_draft_slot",
            "draft_id": "D1",
            "summary": {"mode_label": "Solo", "current_pick": 1, "total_picks": 10},
            "room": {"status": "paused", "config": {"picks_per_team": 5}},
        }
        gate = gate_start_new_live_draft_click(session)
        self.assertFalse(gate["armed"])
        self.assertFalse(gate["ok"])
        self.assertEqual(session.get(SETUP_VALIDATION_ERROR_KEY), LIVE_DRAFT_SETUP_ERROR)
        self.assertFalse(bool(session.get("_live_draft_start_replace_resumable_pending")))


class SoloLiveDraftStartAppTest(unittest.TestCase):
    def test_click_start_four_picks_five_starters_shows_exact_error(self) -> None:
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(_FIXTURE), default_timeout=120)
        at.session_state["live_draft_picks_per_team"] = 4
        at.session_state["live_slot_c"] = 1
        at.session_state["live_slot_1b"] = 1
        at.session_state["live_slot_2b"] = 1
        at.session_state["live_slot_3b"] = 0
        at.session_state["live_slot_ss"] = 1
        at.session_state["live_slot_of"] = 1
        at.session_state["live_slot_dh"] = 0
        at.session_state["live_slot_p"] = 0
        at.session_state["live_slot_bench"] = 0
        at.run()
        self.assertFalse(at.exception)
        start = [b for b in at.button if b.key == "live_draft_start_btn"]
        self.assertTrue(start)
        start[0].click().run()
        self.assertFalse(at.exception)
        error_texts = [e.value for e in at.error]
        self.assertIn(LIVE_DRAFT_SETUP_ERROR, error_texts)
        self.assertEqual(
            at.session_state["_live_draft_setup_validation_error"]
            if "_live_draft_setup_validation_error" in at.session_state
            else None,
            LIVE_DRAFT_SETUP_ERROR,
        )
        self.assertTrue(
            "live_draft_room" not in at.session_state
            or at.session_state["live_draft_room"] is None
        )

    def test_click_start_five_picks_starts_in_progress(self) -> None:
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(_FIXTURE), default_timeout=120)
        at.session_state["live_draft_picks_per_team"] = 5
        at.session_state["live_slot_c"] = 1
        at.session_state["live_slot_1b"] = 1
        at.session_state["live_slot_2b"] = 1
        at.session_state["live_slot_3b"] = 0
        at.session_state["live_slot_ss"] = 1
        at.session_state["live_slot_of"] = 1
        at.session_state["live_slot_dh"] = 0
        at.session_state["live_slot_p"] = 0
        at.session_state["live_slot_bench"] = 0
        at.run()
        start = [b for b in at.button if b.key == "live_draft_start_btn"]
        start[0].click().run()
        self.assertFalse(at.exception)
        self.assertIn("live_draft_room", at.session_state)
        room = at.session_state["live_draft_room"]
        self.assertIsInstance(room, dict)
        self.assertEqual(room.get("status"), "in_progress")
        self.assertIsNotNone(room.get("timer_deadline"))
        order = room.get("pick_order") or []
        self.assertEqual(str((order[0] or {}).get("Team") or ""), "Team A")
        self.assertNotIn("_live_draft_setup_validation_error", at.session_state)

    def test_click_start_eight_picks_bench_capacity_three(self) -> None:
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(_FIXTURE), default_timeout=120)
        at.session_state["live_draft_picks_per_team"] = 8
        at.session_state["live_slot_c"] = 1
        at.session_state["live_slot_1b"] = 1
        at.session_state["live_slot_2b"] = 1
        at.session_state["live_slot_3b"] = 0
        at.session_state["live_slot_ss"] = 1
        at.session_state["live_slot_of"] = 1
        at.session_state["live_slot_dh"] = 0
        at.session_state["live_slot_p"] = 0
        at.session_state["live_slot_bench"] = 0
        at.run()
        start = [b for b in at.button if b.key == "live_draft_start_btn"]
        start[0].click().run()
        room = at.session_state["live_draft_room"]
        self.assertIsInstance(room, dict)
        self.assertEqual(room.get("status"), "in_progress")
        slots = (room.get("config") or {}).get("slots") or {}
        self.assertEqual(int(slots.get("BN") or 0), 3)


if __name__ == "__main__":
    unittest.main()
