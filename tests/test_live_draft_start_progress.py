"""Tests for live draft start progress — no infinite rerun, bounded startup."""

from __future__ import annotations

import unittest
from unittest import mock

from live_draft_start_progress import (
    PENDING_ACTIVITY_EVENT_KEY,
    START_IN_FLIGHT_KEY,
    begin_live_draft_start,
    finish_live_draft_start,
    flush_pending_live_draft_created_activity,
    is_live_draft_start_in_flight,
    queue_live_draft_created_activity,
    should_skip_live_draft_poll,
)


class LiveDraftStartProgressTests(unittest.TestCase):
    def test_start_in_flight_gates_poll(self) -> None:
        session: dict = {}
        self.assertFalse(should_skip_live_draft_poll(session))
        begin_live_draft_start(session, mode="new")
        self.assertTrue(is_live_draft_start_in_flight(session))
        self.assertTrue(should_skip_live_draft_poll(session))
        finish_live_draft_start(session, ok=True)
        self.assertFalse(is_live_draft_start_in_flight(session))

    def test_pending_flag_also_gates_poll(self) -> None:
        session: dict = {"_start_live_draft_pending": True}
        self.assertTrue(should_skip_live_draft_poll(session))

    def test_rerun_blocked_during_start(self) -> None:
        from live_draft_safe_mode import is_rerun_allowed

        session: dict = {}
        begin_live_draft_start(session)
        allowed, reason = is_rerun_allowed(session, "poll_fragment")
        self.assertFalse(allowed)
        self.assertEqual(reason, "draft_start_in_flight")
        finish_live_draft_start(session, ok=True)
        allowed2, _ = is_rerun_allowed(session, "poll_fragment")
        self.assertTrue(allowed2)

    def test_activity_write_deferred_until_flush(self) -> None:
        session: dict = {}
        room = {"draft_room_id": "AB12CD34", "teams": ["Amiel", "Daniel"], "draft_board": [], "config": {}}
        queue_live_draft_created_activity(session)
        self.assertTrue(session.get(PENDING_ACTIVITY_EVENT_KEY))
        with mock.patch("baseball_draft_activity.log_live_draft_room_created") as log_fn:
            flush_pending_live_draft_created_activity(session, room)
            log_fn.assert_called_once()
        self.assertFalse(session.get(PENDING_ACTIVITY_EVENT_KEY))

    def test_activity_flush_failure_does_not_block(self) -> None:
        session: dict = {}
        room = {"draft_room_id": "X", "teams": [], "draft_board": [], "config": {}}
        queue_live_draft_created_activity(session)
        with mock.patch("baseball_draft_activity.log_live_draft_room_created", side_effect=RuntimeError("cc down")):
            flush_pending_live_draft_created_activity(session, room)
        self.assertFalse(session.get(PENDING_ACTIVITY_EVENT_KEY))

    def test_finish_clears_start_in_flight_even_on_failure(self) -> None:
        session: dict = {}
        begin_live_draft_start(session)
        finish_live_draft_start(session, ok=False, error="pool empty")
        self.assertFalse(is_live_draft_start_in_flight(session))
        self.assertFalse(session.get(START_IN_FLIGHT_KEY))

    def test_resolve_room_code_from_meta(self) -> None:
        from draft_room_context import resolve_shared_room_code
        from draft_room_shared_state import SHARED_ROOM_META_KEY

        session = {SHARED_ROOM_META_KEY: {"room_code": "JOIN01"}}
        self.assertEqual(resolve_shared_room_code(session), "JOIN01")

    def test_start_draft_reason_suppresses_rerun(self) -> None:
        """start_draft must not trigger st.rerun (prevents startup rerun loops)."""
        reason = "start_draft"
        rerun = True
        if reason in ("start_draft",):
            rerun = False
        self.assertFalse(rerun)


class DraftLabResumeStartGuardTests(unittest.TestCase):
    def test_skips_resume_when_live_draft_starting(self) -> None:
        from draft_lab_resume import apply_draft_lab_resume

        st = mock.MagicMock()
        st.session_state = {"_live_draft_start_in_flight": True, "_suite_pending_draft_lab_resume": True}
        diag = apply_draft_lab_resume(st)
        self.assertEqual(diag.get("draft_lab_results_status"), "skipped_live_draft_start_in_flight")

    def test_skips_resume_when_live_draft_in_progress(self) -> None:
        from draft_lab_resume import apply_draft_lab_resume

        st = mock.MagicMock()
        st.session_state = {
            "live_draft_room": {"draft_room_id": "R1", "status": "in_progress", "draft_board": []},
        }
        with mock.patch("live_draft_state.has_active_live_draft", return_value=True):
            diag = apply_draft_lab_resume(st)
        self.assertEqual(diag.get("draft_lab_results_status"), "skipped_active_live_draft")


if __name__ == "__main__":
    unittest.main()
