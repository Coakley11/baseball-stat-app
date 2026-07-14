"""Tests for live draft safe mode, reconcile, and rerun gating."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from live_draft_safe_mode import (
    is_rerun_allowed,
    is_safe_mode_active,
    reconcile_live_draft_room,
    request_live_draft_rerun,
    prepare_manual_pick_recovery,
)
from live_draft_state import analyze_live_draft_progress


def _room(**overrides: object) -> dict:
    base = {
        "status": "complete",
        "current_pick_index": 6,
        "teams": ["Daniel", "Guest"],
        "pick_order": [{"Pick": i + 1, "Round": 1, "Team": "Daniel" if i % 2 == 0 else "Guest"} for i in range(6)],
        "draft_board": [{"playerID": f"p{i}"} for i in range(4)],
        "drafted_player_ids": [f"p{i}" for i in range(4)],
        "config": {"picks_per_team": 3},
        "timer_started_at": 1_700_000_000.0,
    }
    base.update(overrides)
    return base


class ReconcileTests(unittest.TestCase):
    def test_stale_complete_reopened_to_in_progress(self) -> None:
        session: dict = {"live_draft_room": _room()}
        result = reconcile_live_draft_room(session, session["live_draft_room"])
        self.assertEqual(result.draft_status_after, "in_progress")
        self.assertTrue(result.stale_draft_status_detected)
        self.assertEqual(result.board_size, 4)
        self.assertEqual(result.room["current_pick_index"], 4)

    def test_index_ahead_of_board_reconciled(self) -> None:
        session: dict = {"live_draft_room": _room(current_pick_index=6, status="in_progress")}
        result = reconcile_live_draft_room(session, session["live_draft_room"])
        self.assertEqual(result.room["current_pick_index"], 4)
        self.assertFalse(result.draft_state_error)

    def test_analyze_progress_not_complete_when_board_incomplete(self) -> None:
        session: dict = {"live_draft_room": _room()}
        reconcile_live_draft_room(session, session["live_draft_room"])
        progress = analyze_live_draft_progress(session["live_draft_room"])
        self.assertFalse(progress["draft_complete"])
        self.assertEqual(progress["on_clock_team"], "Daniel")

    def test_rerun_loop_bookkeeping_does_not_activate_safe_mode(self) -> None:
        """Soft throttle flags must not freeze the draft engine at 0s."""
        from live_draft_expired_pick import RERUN_LOOP_PREVENTED_KEY

        room = _room(status="in_progress", current_pick_index=4, timer_started_at=None)
        session: dict = {
            "live_draft_room": room,
            RERUN_LOOP_PREVENTED_KEY: True,
            "_live_draft_rerun_count": 20,
            "_live_draft_last_rerun_source": "page_autopick",
        }
        result = reconcile_live_draft_room(session, room)
        self.assertFalse(result.safe_mode_active)
        self.assertFalse(is_safe_mode_active(session))
        self.assertNotIn("rerun_loop_prevented", result.draft_state_error_reason or "")
        self.assertTrue(result.timer_should_run)


class RerunGateTests(unittest.TestCase):
    def test_safe_mode_blocks_timer_fragment_rerun(self) -> None:
        session: dict = {"_live_draft_safe_mode_active": True}
        allowed, reason = is_rerun_allowed(session, "timer_fragment")
        self.assertFalse(allowed)
        self.assertIn("safe_mode", reason)

    def test_manual_pick_rerun_allowed_in_safe_mode(self) -> None:
        session: dict = {"_live_draft_safe_mode_active": True}
        allowed, _ = is_rerun_allowed(session, "manual_pick")
        self.assertTrue(allowed)

    def test_request_rerun_blocked_does_not_call_st(self) -> None:
        session: dict = {"_live_draft_safe_mode_active": True}
        st = MagicMock()
        ok = request_live_draft_rerun(st, session, "poll_shared_draft")
        self.assertFalse(ok)
        st.rerun.assert_not_called()

    def test_excessive_reruns_soft_block_does_not_latch_loop_prevented(self) -> None:
        from live_draft_expired_pick import RERUN_LOOP_PREVENTED_KEY

        session: dict = {"_live_draft_rerun_count": 20}
        allowed, reason = is_rerun_allowed(session, "page_autopick")
        self.assertFalse(allowed)
        self.assertEqual(reason, "excessive_reruns_blocked")
        self.assertFalse(bool(session.get(RERUN_LOOP_PREVENTED_KEY)))


class ManualRecoveryTests(unittest.TestCase):
    def test_manual_recovery_clears_safe_mode_and_reconciles(self) -> None:
        session: dict = {"live_draft_room": _room(), "_live_draft_safe_mode_active": True}
        result = prepare_manual_pick_recovery(session)
        self.assertIsNotNone(result)
        self.assertEqual(result.room["status"], "in_progress")  # type: ignore[union-attr]
        self.assertFalse(is_safe_mode_active(session))


if __name__ == "__main__":
    unittest.main()
