"""Rendered AppTest: Shared mode + replace-resumable Start Draft validation."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from fantasy_roster_validation import LIVE_DRAFT_SETUP_ERROR
from live_draft_setup_mode import SETUP_MODE_SHARED, SETUP_MODE_SOLO
from live_draft_start_setup import SETUP_VALIDATION_ERROR_KEY, gate_start_new_live_draft_click

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "live_draft_start_replace_apptest.py"


def _resumable_slot(*, shared: bool = False) -> dict:
    mode = SETUP_MODE_SHARED if shared else SETUP_MODE_SOLO
    room = {
        "draft_room_id": "OLD-SLOT",
        "status": "saved_for_later",
        "current_pick_index": 2,
        "config": {
            "num_teams": 2,
            "picks_per_team": 5,
            "draft_setup_mode": mode,
            "teams": ["Team A", "Team B"],
        },
        "teams": ["Team A", "Team B"],
        "pick_order": [{"Pick": 1, "Team": "Team A"}],
        "draft_board": [{"Pick": 1, "Team": "Team A"}],
        "rosters": {"Team A": [], "Team B": []},
        "drafted_player_ids": [],
        "pool": pd.DataFrame(
            [{"playerID": f"p{i}", "fullName": f"P{i}", "Primary Position": "OF"} for i in range(20)]
        ),
    }
    return {
        "kind": "resumable_live_draft_slot",
        "draft_id": "OLD-SLOT",
        "is_shared": shared,
        "room": room,
        "summary": {"mode_label": "Shared" if shared else "Solo", "current_pick": 2, "total_picks": 10},
    }


class SharedStartGateTests(unittest.TestCase):
    def test_shared_invalid_setup_blocks_before_replace(self) -> None:
        session = {
            "live_draft_setup_mode": SETUP_MODE_SHARED,
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
            "resumable_live_draft_slot": _resumable_slot(shared=True),
        }
        gate = gate_start_new_live_draft_click(session)
        self.assertFalse(gate["ok"])
        self.assertEqual(session.get(SETUP_VALIDATION_ERROR_KEY), LIVE_DRAFT_SETUP_ERROR)
        self.assertFalse(bool(session.get("_live_draft_start_replace_resumable_pending")))

    def test_shared_valid_setup_with_resumable_arms_replace(self) -> None:
        session = {
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            "live_draft_picks_per_team": 5,
            "live_slot_c": 1,
            "live_slot_1b": 1,
            "live_slot_2b": 1,
            "live_slot_3b": 0,
            "live_slot_ss": 1,
            "live_slot_of": 1,
            "live_slot_dh": 0,
            "live_slot_p": 0,
            "live_slot_bench": 0,
            "resumable_live_draft_slot": _resumable_slot(shared=True),
        }
        gate = gate_start_new_live_draft_click(session)
        self.assertTrue(gate["ok"])
        self.assertTrue(gate["replace_pending"])
        self.assertTrue(session.get("_live_draft_start_replace_resumable_pending"))


class StartReplaceAppTest(unittest.TestCase):
    def test_shared_mode_invalid_click_shows_error(self) -> None:
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(_FIXTURE), default_timeout=30)
        at.session_state["live_draft_setup_mode"] = SETUP_MODE_SHARED
        at.session_state["live_draft_picks_per_team"] = 4
        at.run()
        start = [b for b in at.button if b.key == "live_draft_start_btn"]
        start[0].click().run()
        self.assertFalse(at.exception)
        self.assertIn(LIVE_DRAFT_SETUP_ERROR, [e.value for e in at.error])

    def test_replace_confirm_starts_fresh_solo_room(self) -> None:
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(_FIXTURE), default_timeout=60)
        at.session_state["live_draft_setup_mode"] = SETUP_MODE_SOLO
        at.session_state["live_draft_picks_per_team"] = 5
        at.session_state["resumable_live_draft_slot"] = _resumable_slot(shared=True)
        at.run()
        start = [b for b in at.button if b.key == "live_draft_start_btn"]
        start[0].click().run()
        self.assertFalse(at.exception)
        pending = "_live_draft_start_replace_resumable_pending" in at.session_state and bool(
            at.session_state["_live_draft_start_replace_resumable_pending"]
        )
        markdown = " ".join(str(m.value) for m in at.markdown)
        self.assertTrue(pending or "REPLACE_PENDING=1" in markdown)
        confirm = [b for b in at.button if b.key == "live_draft_start_replace_confirm_btn"]
        self.assertTrue(confirm)
        with patch("live_draft_termination.persist_durable_tombstones", return_value=None):
            with patch(
                "live_draft_resumable_slot.clear_resumable_live_draft_slot",
                side_effect=lambda s: s.pop("resumable_live_draft_slot", None),
            ):
                confirm[0].click().run()
        self.assertFalse(at.exception)
        room = at.session_state["live_draft_room"] if "live_draft_room" in at.session_state else None
        self.assertIsInstance(room, dict)
        self.assertEqual(room.get("status"), "in_progress")
        self.assertEqual(
            str((room.get("config") or {}).get("draft_setup_mode") or ""),
            SETUP_MODE_SOLO,
        )
        self.assertFalse("resumable_live_draft_slot" in at.session_state and at.session_state["resumable_live_draft_slot"])
        self.assertTrue(
            "_replace_result_ok" in at.session_state and at.session_state["_replace_result_ok"]
        )

    def test_valid_shared_gate_passes_same_as_solo(self) -> None:
        session = {
            "live_draft_setup_mode": SETUP_MODE_SHARED,
            "live_draft_picks_per_team": 8,
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
        gate = gate_start_new_live_draft_click(session)
        self.assertTrue(gate["armed"])
        self.assertTrue(gate["ok"])


if __name__ == "__main__":
    unittest.main()
