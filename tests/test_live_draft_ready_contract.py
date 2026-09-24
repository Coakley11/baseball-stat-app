"""Ready-state contract — no sticky Pick-1-of-0 Start stubs."""

from __future__ import annotations

import unittest

import pandas as pd

from live_draft_ready_contract import (
    clear_uninhabitable_solo_ready_stub,
    is_uninhabitable_solo_ready_stub,
    is_valid_solo_ready_room,
    solo_ready_contract,
)


def _valid_room(**overrides):
    room = {
        "status": "not_started",
        "draft_room_id": "ABC123",
        "teams": ["Team A", "Team B"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team A"},
            {"Pick": 2, "Round": 1, "Team": "Team B"},
        ],
        "draft_board": [],
        "config": {
            "timer_seconds": 8,
            "your_team": "Team A",
            "picks_per_team": 1,
        },
        "pool": pd.DataFrame(
            {
                "fullName": ["A", "B"],
                "Blended Projection Score": [1.0, 0.5],
                "proj_HR": [30.0, 20.0],
                "proj_RBI": [90.0, 70.0],
                "Market Rank": [1, 2],
                "Model Rank": [1, 3],
            }
        ),
    }
    room.update(overrides)
    return room


class ReadyContractTests(unittest.TestCase):
    def test_valid_room_can_start(self) -> None:
        c = solo_ready_contract(_valid_room())
        self.assertTrue(c["can_show_ready"])
        self.assertTrue(c["can_start"])
        self.assertTrue(c["ok"])

    def test_empty_teams_is_uninhabitable_stub(self) -> None:
        room = _valid_room(teams=[], pick_order=[])
        self.assertTrue(is_uninhabitable_solo_ready_stub(room))
        self.assertFalse(is_valid_solo_ready_room(room))
        c = solo_ready_contract(room)
        self.assertFalse(c["can_show_ready"])
        self.assertIn("teams_incomplete", c["reasons"])
        self.assertIn("pick_order_empty", c["reasons"])

    def test_clear_stub_from_session(self) -> None:
        session = {
            "live_draft_room": _valid_room(teams=[], pick_order=[]),
            "baseball_workspace_state": {
                "live_draft": {"draft_room_id": "ABC123", "status": "not_started"}
            },
        }
        self.assertTrue(clear_uninhabitable_solo_ready_stub(session))
        room_left = session.get("live_draft_room")
        self.assertTrue(room_left is None or "live_draft_room" not in session)
        self.assertTrue(session.get("_live_draft_force_setup_after_delete"))
        ws = session.get("baseball_workspace_state") or {}
        self.assertNotIn("live_draft", ws)

    def test_structural_phase_preparing_without_projections(self) -> None:
        from draft_scoring_pool import POOL_KIND_FAST_MARKET_FALLBACK, POOL_VALUE_KIND_KEY
        from live_draft_ready_contract import PHASE_PREPARING, PHASE_READY

        pool = pd.DataFrame({"fullName": ["A"], "Market Rank": [1]})
        pool.attrs[POOL_VALUE_KIND_KEY] = POOL_KIND_FAST_MARKET_FALLBACK
        room = _valid_room(pool=pool)
        c = solo_ready_contract(room)
        self.assertEqual(c["phase"], PHASE_PREPARING)
        self.assertTrue(c["can_show_ready"])
        self.assertFalse(c["can_start"])
        room2 = _valid_room()
        c2 = solo_ready_contract(room2)
        self.assertEqual(c2["phase"], PHASE_READY)

    def test_timer_armed_blocks_ready(self) -> None:
        room = _valid_room(timer_deadline=1234567890.0)
        c = solo_ready_contract(room)
        self.assertFalse(c["can_show_ready"])
        self.assertIn("timer_already_armed", c["reasons"])

    def test_fast_pool_without_blend_blocks_start_not_structure(self) -> None:
        from draft_scoring_pool import POOL_KIND_FAST_MARKET_FALLBACK, POOL_VALUE_KIND_KEY

        pool = pd.DataFrame(
            {
                "fullName": ["A"],
                "Market Rank": [1],
                "Expected Fantasy Value": [0.9],
            }
        )
        pool.attrs[POOL_VALUE_KIND_KEY] = POOL_KIND_FAST_MARKET_FALLBACK
        room = _valid_room(pool=pool)
        c = solo_ready_contract(room)
        self.assertTrue(c["can_show_ready"])
        self.assertFalse(c["can_start"])
        self.assertFalse(c["pool_has_projections"])

    def test_is_solo_lobby_rejects_stub(self) -> None:
        from live_draft_setup_mode import is_solo_lobby

        session = {
            "live_draft_setup_mode": "solo",
            "live_draft_room": {
                "status": "not_started",
                "teams": [],
                "pick_order": [],
                "draft_board": [],
                "draft_room_id": "X",
                "config": {"timer_seconds": 60},
                "pool": pd.DataFrame({"fullName": ["A"]}),
            },
        }
        self.assertFalse(is_solo_lobby(session))


if __name__ == "__main__":
    unittest.main()
