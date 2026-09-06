"""Corrupt in_progress stubs (Pick 1 of 0) must clear so Create/setup is reachable."""

from __future__ import annotations

import unittest

from live_draft_state import (
    LIVE_DRAFT_ROOM_KEY,
    clear_uninhabitable_in_progress_stub,
    is_uninhabitable_in_progress_stub,
    prepare_live_draft_state,
)


class UninhabitableInProgressStubTests(unittest.TestCase):
    def test_stub_without_teams_or_config_is_uninhabitable(self) -> None:
        room = {"draft_room_id": "893DE667", "status": "in_progress"}
        self.assertTrue(is_uninhabitable_in_progress_stub(room))

    def test_healthy_in_progress_room_is_habitable(self) -> None:
        room = {
            "draft_room_id": "OKROOM01",
            "status": "in_progress",
            "teams": ["Team A", "Team B"],
            "config": {"picks_per_team": 15, "num_teams": 2, "draft_setup_mode": "solo"},
            "draft_board": [],
        }
        self.assertFalse(is_uninhabitable_in_progress_stub(room))

    def test_clear_removes_runtime_and_workspace_compact(self) -> None:
        session = {
            LIVE_DRAFT_ROOM_KEY: {"draft_room_id": "893DE667", "status": "in_progress"},
            "baseball_workspace_state": {
                "live_draft": {
                    "draft_room_id": "893DE667",
                    "status": "in_progress",
                    "current_pick_index": 0,
                    "board_len": 0,
                    "pool_len": 699,
                }
            },
        }
        self.assertTrue(clear_uninhabitable_in_progress_stub(session))
        self.assertFalse(isinstance(session.get(LIVE_DRAFT_ROOM_KEY), dict))
        ws = session.get("baseball_workspace_state") or {}
        self.assertNotIn("live_draft", ws)

    def test_prepare_clears_stub_so_setup_can_render(self) -> None:
        session = {
            "live_draft_setup_mode": "shared_multiplayer",
            LIVE_DRAFT_ROOM_KEY: {"draft_room_id": "893DE667", "status": "in_progress"},
            "baseball_workspace_state": {
                "live_draft": {"draft_room_id": "893DE667", "status": "in_progress"}
            },
        }
        prepared = prepare_live_draft_state(session)
        self.assertFalse(isinstance(prepared, dict) and prepared.get("draft_room_id") == "893DE667")
        self.assertFalse(isinstance(session.get(LIVE_DRAFT_ROOM_KEY), dict))
        self.assertEqual(
            (session.get("_live_draft_cleared_uninhabitable_stub") or {}).get("reason"),
            "prepare_uninhabitable_stub",
        )


if __name__ == "__main__":
    unittest.main()
