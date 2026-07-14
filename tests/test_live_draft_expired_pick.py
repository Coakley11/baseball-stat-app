"""Tests for expired-pick state machine and pick commit."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from live_draft_expired_pick import (
    AUTOPICK_ATTEMPTED_INDEX_KEY,
    AUTOPICK_BACKOFF_INDEX_KEY,
    RERUN_LOOP_PREVENTED_KEY,
    TIMER_ZERO_RERUN_LATCH_KEY,
    autopick_failure_backoff_active,
    claim_timer_zero_rerun,
    clear_autopick_backoff_for_manual,
    expired_pick_detected,
    handle_expired_pick_on_page,
    run_expired_autopick_once,
    should_attach_timer_fragment,
    should_fragment_trigger_full_rerun,
)
from live_draft_pick_commit import PickCommitResult, commit_manual_live_pick, persist_applied_pick


def _room(**overrides: object) -> dict:
    pool = pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p2", "fullName": "Jose Ramirez", "Primary Position": "3B"},
        ]
    )
    base = {
        "status": "in_progress",
        "current_pick_index": 4,
        "config": {"num_teams": 2, "your_team": "Daniel", "timer_seconds": 60},
        "teams": ["Daniel", "Guest"],
        "pick_order": [
            {"Pick": i + 1, "Round": 1, "Team": "Daniel" if i % 2 == 0 else "Guest"}
            for i in range(6)
        ],
        "draft_board": [{} for _ in range(4)],
        "rosters": {"Daniel": [], "Guest": []},
        "drafted_player_ids": ["x1", "x2", "x3", "x4"],
        "pool": pool,
        "timer_started_at": time.time() - 120,
        "timer_handled_index": -1,
    }
    base.update(overrides)
    return base


class ExpiredPickDetectionTests(unittest.TestCase):
    def test_expired_pick_detected_when_timer_at_zero(self) -> None:
        self.assertTrue(expired_pick_detected(_room()))

    def test_fragment_rerun_suppressed_after_backoff(self) -> None:
        session: dict = {}
        room = _room()
        session[RERUN_LOOP_PREVENTED_KEY] = True
        session[AUTOPICK_BACKOFF_INDEX_KEY] = 4
        self.assertFalse(should_fragment_trigger_full_rerun(session, room))

    def test_timer_fragment_detached_when_clock_already_zero(self) -> None:
        session: dict = {}
        room = _room()
        self.assertFalse(should_attach_timer_fragment(session, room))
        self.assertTrue(session.get("_live_draft_timer_expired_pending"))

    def test_timer_zero_rerun_latched_once_per_pick(self) -> None:
        session: dict = {}
        room = _room()
        self.assertTrue(claim_timer_zero_rerun(session, room))
        self.assertEqual(session[TIMER_ZERO_RERUN_LATCH_KEY], 4)
        self.assertFalse(claim_timer_zero_rerun(session, room))
        self.assertFalse(should_fragment_trigger_full_rerun(session, room))

    def test_timer_zero_rerun_blocked_by_safe_mode_gate(self) -> None:
        from live_draft_safe_mode import is_rerun_allowed

        session: dict = {}
        room = _room()
        claim_timer_zero_rerun(session, room)
        allowed, reason = is_rerun_allowed(session, "timer_fragment_zero", room=room)
        self.assertFalse(allowed)
        self.assertEqual(reason, "timer_zero_rerun_already_latched")


class AutopickBackoffTests(unittest.TestCase):
    @patch("live_draft_expired_pick.run_autopick_selection", return_value=(False, "No players remain"))
    def test_failed_autopick_activates_backoff_and_no_rerun(self, _sel: MagicMock) -> None:
        session: dict = {"live_draft_room": _room()}
        result = run_expired_autopick_once(session, session["live_draft_room"])
        self.assertTrue(result.handled)
        self.assertFalse(result.ok)
        self.assertFalse(result.should_rerun)
        self.assertTrue(autopick_failure_backoff_active(session, session["live_draft_room"]))
        self.assertEqual(session[AUTOPICK_ATTEMPTED_INDEX_KEY], 4)

    @patch("live_draft_expired_pick.run_autopick_selection", return_value=(False, "No players remain"))
    def test_second_page_pass_does_not_retry(self, _sel: MagicMock) -> None:
        session: dict = {"live_draft_room": _room()}
        run_expired_autopick_once(session, session["live_draft_room"])
        result2 = handle_expired_pick_on_page(session, session["live_draft_room"])
        self.assertFalse(result2.should_rerun)
        err = result2.error or str(session.get("_live_draft_autopick_error") or "")
        self.assertIn("No players", err)


class ManualRecoveryTests(unittest.TestCase):
    def test_manual_clears_backoff(self) -> None:
        session: dict = {
            RERUN_LOOP_PREVENTED_KEY: True,
            AUTOPICK_BACKOFF_INDEX_KEY: 4,
            AUTOPICK_ATTEMPTED_INDEX_KEY: 4,
        }
        room = _room()
        clear_autopick_backoff_for_manual(session, room)
        self.assertFalse(autopick_failure_backoff_active(session, room))

    @patch("live_draft_pick_commit.persist_applied_pick")
    @patch("live_draft_pick_commit.live_draft_make_pick")
    @patch("live_draft_pick_commit.sync_expected_revision", return_value=None)
    def test_manual_pick_advances_index(
        self,
        _rev: MagicMock,
        mock_make: MagicMock,
        mock_persist: MagicMock,
    ) -> None:
        session: dict = {"live_draft_room": _room()}
        room = session["live_draft_room"]

        def _apply(room_obj, row, verdict="Manual pick", **kwargs):
            room_obj["draft_board"].append(row)
            room_obj["current_pick_index"] = 5
            return True, "Drafted Jose Ramirez to Daniel."

        mock_make.side_effect = _apply
        mock_persist.return_value = PickCommitResult(
            ok=True,
            message="Drafted Jose Ramirez to Daniel.",
            error="",
            commit_path="single_user",
            board_size_before=4,
            board_size_after=5,
            current_pick_index_before=4,
            current_pick_index_after=5,
        )
        row = {"playerID": "p2", "fullName": "Jose Ramirez"}
        result = commit_manual_live_pick(session, room, row, source="live_draft_room")
        self.assertTrue(result.ok)
        self.assertEqual(result.current_pick_index_after, 5)


class PersistAppliedPickTests(unittest.TestCase):
    @patch("live_draft_state.write_canonical_live_draft_state")
    @patch("draft_room_context.is_multiplayer_draft_active", return_value=False)
    def test_persist_after_make_pick(self, _mp: MagicMock, _write: MagicMock) -> None:
        from live_draft_state import LIVE_DRAFT_ROOM_KEY

        session: dict = {}
        room = _room()
        room["draft_board"].append({"playerID": "p2", "fullName": "Jose Ramirez"})
        room["current_pick_index"] = 5
        room["timer_started_at"] = time.time()
        room["timer_handled_index"] = -1
        session[LIVE_DRAFT_ROOM_KEY] = room
        result = persist_applied_pick(session, room, source="test", board_size_before=4, idx_before=4)
        self.assertTrue(result.ok)
        self.assertEqual(result.current_pick_index_after, 5)


if __name__ == "__main__":
    unittest.main()
