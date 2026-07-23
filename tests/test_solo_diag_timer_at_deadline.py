"""Tests for query-param gated solo_diag_timer at deadline creation."""

from __future__ import annotations

import time
import unittest
from unittest import mock


class SoloDiagTimerAtDeadlineTests(unittest.TestCase):
    def test_apply_only_when_query_param_present(self) -> None:
        from live_draft_solo_component_diagnostics import (
            SOLO_DIAG_TIMER_SESSION_KEY,
            maybe_apply_solo_diag_timer_at_deadline_creation,
        )

        session: dict = {}
        room = {"config": {"timer_seconds": 60}, "current_pick_index": 0}
        st = mock.MagicMock()
        with mock.patch(
            "live_draft_solo_component_diagnostics._qp_get",
            return_value="",
        ):
            self.assertFalse(maybe_apply_solo_diag_timer_at_deadline_creation(st, session, room))
        self.assertEqual(room["config"]["timer_seconds"], 60)

        with mock.patch(
            "live_draft_solo_component_diagnostics._qp_get",
            side_effect=lambda _st, name: "10" if name == "solo_diag_timer" else "",
        ):
            self.assertTrue(maybe_apply_solo_diag_timer_at_deadline_creation(st, session, room))
        self.assertEqual(session[SOLO_DIAG_TIMER_SESSION_KEY], 10)
        self.assertEqual(room["config"]["timer_seconds"], 10)
        self.assertEqual(room["_solo_diag_timer_seconds"], 10)

    def test_record_deadline_after_reset(self) -> None:
        from live_draft_solo_component_diagnostics import (
            SOLO_DIAG_DEADLINE_KEY,
            SOLO_DIAG_TIMER_SESSION_KEY,
            record_solo_diag_deadline_after_reset,
        )
        from live_draft_timer_logic import live_draft_reset_timer

        session = {SOLO_DIAG_TIMER_SESSION_KEY: 10}
        room = {
            "status": "in_progress",
            "config": {"timer_seconds": 10},
            "_solo_diag_timer_seconds": 10,
            "current_pick_index": 0,
        }
        live_draft_reset_timer(room)
        record_solo_diag_deadline_after_reset(session, room)
        row = session.get(SOLO_DIAG_DEADLINE_KEY) or {}
        self.assertAlmostEqual(float(row.get("remaining_seconds") or 0), 10, delta=1)
        self.assertGreater(float(row.get("deadline") or 0), time.time())


if __name__ == "__main__":
    unittest.main()
