"""Solo vs Shared isolation when disregarding a saved draft; timer pick-order repair."""

from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from live_draft_completion import LIFECYCLE_ACTIVE_DRAFT, resolve_live_draft_lifecycle
from live_draft_resumable_ops import (
    build_replacement_live_room,
    execute_continue_saved,
    execute_replace_transactional,
)
from live_draft_safe_mode import is_draft_truly_complete, total_expected_picks
from live_draft_setup_mode import SETUP_MODE_SHARED, SETUP_MODE_SOLO
from live_draft_timer_logic import ensure_full_pick_order, live_draft_current_slot


def _valid_solo_setup_slots() -> dict:
    """Explicit widgets so fail_closed_setup_check does not apply 8-starter defaults.

    Product defaults are C/1B/2B/3B/SS/OF×3/DH = 8 required starters. This isolation
    fixture keeps 4 picks/team (2×4 pick_order); slots must therefore total 4 starters.
    """
    return {
        "live_slot_c": 1,
        "live_slot_1b": 1,
        "live_slot_2b": 1,
        "live_slot_3b": 1,
        "live_slot_ss": 0,
        "live_slot_of": 0,
        "live_slot_dh": 0,
        "live_slot_p": 0,
        "live_slot_bench": 0,
    }


def _shared_slot() -> dict:
    room = {
        "draft_room_id": "OLDSHARED",
        "status": "saved_for_later",
        "current_pick_index": 2,
        "config": {
            "num_teams": 2,
            "picks_per_team": 4,
            "timer_seconds": 60,
            "teams": ["Team A", "Team B"],
            "your_team": "Team B",
            "user_team": "Team B",
            "draft_setup_mode": SETUP_MODE_SHARED,
        },
        "teams": ["Team A", "Team B"],
        "pick_order": [{"Pick": 1, "Round": 1, "Team": "Team A"}],
        "draft_board": [{"Pick": 1, "Team": "Team A", "Player": "X"}],
        "rosters": {"Team A": [], "Team B": []},
        "drafted_player_ids": [],
        "pool": pd.DataFrame(
            [{"playerID": f"p{i}", "fullName": f"P{i}", "Primary Position": "OF"} for i in range(20)]
        ),
    }
    return {
        "kind": "resumable_live_draft_slot",
        "draft_id": "OLDSHARED",
        "room_id": "OLDSHARED",
        "room_code": "ABC123",
        "is_shared": True,
        "participant_team": "Team B",
        "room": room,
        "summary": {"mode_label": "Shared", "num_teams": 2, "current_pick": 2, "total_picks": 8},
    }


class DisregardSavedStartsSoloTests(unittest.TestCase):
    def test_solo_selected_does_not_inherit_shared_slot_mode(self) -> None:
        session = {
            "live_draft_setup_mode": SETUP_MODE_SOLO,
            "preferred_next_draft_mode": SETUP_MODE_SOLO,
            "live_draft_team_count": 2,
            "live_draft_picks_per_team": 4,
            "live_draft_timer_seconds": 30,
            "live_draft_host_team_pick": "Team B",  # stale from prior Shared
            "resumable_live_draft_slot": _shared_slot(),
            "active_shared_draft_room_code": "ABC123",
        }
        room, host = build_replacement_live_room(session, slot=_shared_slot())
        self.assertEqual(host, "Team A")
        self.assertEqual(str((room.get("config") or {}).get("draft_setup_mode")), SETUP_MODE_SOLO)
        self.assertEqual(session.get("live_draft_host_team_pick"), "Team A")

    def test_execute_replace_uses_solo_radio_not_shared_slot(self) -> None:
        session = {
            "live_draft_setup_mode": SETUP_MODE_SOLO,
            "preferred_next_draft_mode": SETUP_MODE_SOLO,
            "live_draft_team_count": 2,
            "live_draft_picks_per_team": 4,
            "live_draft_timer_seconds": 30,
            **_valid_solo_setup_slots(),
            "resumable_live_draft_slot": _shared_slot(),
            "active_shared_draft_room_code": "ABC123",
        }
        with mock.patch(
            "live_draft_setup_mode.finalize_shared_room_create",
            side_effect=AssertionError("must not create Shared when Solo selected"),
        ):
            with mock.patch("live_draft_termination.persist_durable_tombstones", return_value=None):
                with mock.patch(
                    "live_draft_resumable_slot.clear_resumable_live_draft_slot",
                    side_effect=lambda s: s.pop("resumable_live_draft_slot", None),
                ):
                    result = execute_replace_transactional(session, st=None)
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("mode"), "solo")
        live = session.get("live_draft_room")
        assert isinstance(live, dict)
        self.assertEqual(str((live.get("config") or {}).get("draft_setup_mode")), SETUP_MODE_SOLO)
        self.assertFalse(bool(session.get("active_shared_draft_room_code")))
        self.assertFalse(bool(session.get("_live_draft_resume_lobby")))
        self.assertEqual(str(live.get("status") or ""), "in_progress")
        self.assertEqual(int(live.get("current_pick_index")), 0)
        self.assertEqual(str((live.get("config") or {}).get("your_team") or ""), "Team A")
        self.assertFalse(bool(str(live.get("room_code") or "").strip()))
        self.assertGreaterEqual(len(live.get("pick_order") or []), 8)
        self.assertIsNone(session.get("resumable_live_draft_slot"))

    def test_continue_saved_keeps_shared_room_and_lobby(self) -> None:
        slot = _shared_slot()
        session = {
            "live_draft_setup_mode": SETUP_MODE_SOLO,  # setup radio must not flip Continue
            "preferred_next_draft_mode": SETUP_MODE_SOLO,
            "resumable_live_draft_slot": slot,
            "auth_user_id": "commissioner-1",
        }
        with mock.patch(
            "shared_draft_permissions.can_continue_saved_draft_slot",
            return_value=True,
        ):
            with mock.patch(
                "live_draft_resumable_slot.continue_saved_draft",
                return_value={"ok": True, "room_code": "ABC123"},
            ) as cont:
                result = execute_continue_saved(session, st=None)
        self.assertTrue(result.get("ok"), result)
        cont.assert_called_once()
        self.assertTrue(bool(session.get("_live_draft_resume_lobby")))


class LibraryEligibilityTests(unittest.TestCase):
    def test_partial_board_not_library_eligible(self) -> None:
        room = {
            "teams": ["Team A", "Team B"],
            "config": {"num_teams": 2, "picks_per_team": 4},
            "pick_order": [{"Pick": 1}],
            "draft_board": [{"Pick": 1}, {"Pick": 2}],
            "status": "in_progress",
        }
        self.assertFalse(is_draft_truly_complete(room))

    def test_full_board_is_library_eligible(self) -> None:
        room = {
            "teams": ["Team A", "Team B"],
            "config": {"num_teams": 2, "picks_per_team": 2},
            "pick_order": [{"Pick": i} for i in range(1, 5)],
            "draft_board": [{"Pick": i} for i in range(1, 5)],
            "status": "complete",
            "draft_room_id": "DONE-LIB-1",
        }
        self.assertTrue(is_draft_truly_complete(room))
        session = {"live_draft_room": room}
        life = resolve_live_draft_lifecycle(session)
        self.assertEqual(life, LIFECYCLE_ACTIVE_DRAFT)
        self.assertIsInstance(session.get("live_draft_room"), dict)


class TimerPickOrderRepairTests(unittest.TestCase):
    def test_truncated_pick_order_repairs_and_advances(self) -> None:
        room = {
            "status": "in_progress",
            "current_pick_index": 1,
            "teams": ["Team A", "Team B"],
            "config": {"num_teams": 2, "picks_per_team": 4, "timer_seconds": 30, "teams": ["Team A", "Team B"]},
            "pick_order": [{"Pick": 1, "Round": 1, "Team": "Team A"}],
            "draft_board": [{"Pick": 1}],
            "rosters": {"Team A": [], "Team B": []},
            "drafted_player_ids": ["x"],
            "pool": pd.DataFrame(
                [{"playerID": f"p{i}", "fullName": f"P{i}", "Primary Position": "OF"} for i in range(20)]
            ),
        }
        self.assertEqual(total_expected_picks(room), 8)
        self.assertFalse(is_draft_truly_complete(room))
        ensure_full_pick_order(room)
        self.assertEqual(len(room["pick_order"]), 8)
        slot = live_draft_current_slot(room)
        self.assertIsNotNone(slot)
        self.assertEqual(slot["Pick"], 2)

    def test_missing_picks_per_team_not_complete_from_short_order(self) -> None:
        room = {
            "teams": ["Team A", "Team B"],
            "config": {"num_teams": 2},
            "pick_order": [{"Pick": 1, "Team": "Team A"}],
            "draft_board": [{"Pick": 1}],
        }
        self.assertEqual(total_expected_picks(room), 0)
        self.assertFalse(is_draft_truly_complete(room))


if __name__ == "__main__":
    unittest.main()
