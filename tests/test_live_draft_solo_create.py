"""Solo minimal create + hard watchdog."""

from __future__ import annotations

import time
import unittest

from live_draft_solo_create import (
    CREATION_HARD_ABORT_SEC,
    evaluate_creation_hard_watchdog,
    mark_deferred_create_persist,
    needs_deferred_create_persist,
    note_timed_step,
)
from live_draft_start_progress import MONO_START_KEY, START_IN_FLIGHT_KEY, begin_live_draft_start


class SoloCreateMinimalTests(unittest.TestCase):
    def test_note_timed_step_writes_receipt_ms(self) -> None:
        from live_draft_creation_trace import init_creation_trace

        session: dict = {}
        init_creation_trace(session, mode="new")
        t0 = time.perf_counter()
        time.sleep(0.01)
        note_timed_step(session, "pool_build_end", ok=True, t_step0=t0, pool_live_count=12)
        receipt = session["_live_draft_creation_receipt"]
        self.assertGreaterEqual(float(receipt.get("pool_build_end_ms") or 0), 5.0)
        self.assertEqual(receipt.get("pool_live_count"), 12)
        self.assertIn("player_pool_loaded_ms", receipt)

    def test_hard_watchdog_aborts_after_20s(self) -> None:
        from live_draft_creation_trace import init_creation_trace

        session: dict = {
            "live_draft_room": {"draft_room_id": "SOLO-W", "status": "in_progress"},
        }
        init_creation_trace(session, mode="new")
        begin_live_draft_start(session, mode="new")
        session[MONO_START_KEY] = time.monotonic() - (CREATION_HARD_ABORT_SEC + 1.0)
        note_timed_step(session, "pool_build_start", ok=True)
        fail = evaluate_creation_hard_watchdog(session)
        self.assertIsNotNone(fail)
        self.assertEqual((fail or {}).get("level"), "abort")
        self.assertFalse(session.get(START_IN_FLIGHT_KEY))
        self.assertIsInstance(session.get("live_draft_room"), dict)

    def test_deferred_persist_flag(self) -> None:
        session: dict = {}
        self.assertFalse(needs_deferred_create_persist(session))
        mark_deferred_create_persist(session)
        self.assertTrue(needs_deferred_create_persist(session))


if __name__ == "__main__":
    unittest.main()
