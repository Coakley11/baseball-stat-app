"""Accelerated 32+ pick Solo Live Draft integration — deterministic, repeated runs."""

from __future__ import annotations

import unittest

from tests.live_draft_accelerated_harness import (
    DraftRunMetrics,
    run_accelerated_full_draft,
)

# Internal acceptance: local control + expire → next pick (ms)
_MAX_LOCAL_MS = 3000.0
_REPEAT = 3
_PICKS_PER_RUN = 32


class AcceleratedFullDraftTests(unittest.TestCase):
    metrics: list[DraftRunMetrics]

    @classmethod
    def setUpClass(cls) -> None:
        cls.metrics = run_accelerated_full_draft(repeat=_REPEAT)

    def test_runs_completed(self) -> None:
        self.assertEqual(len(self.metrics), _REPEAT)

    def test_pick_counts(self) -> None:
        for m in self.metrics:
            self.assertEqual(m.picks, _PICKS_PER_RUN, m)

    def test_no_duplicate_players(self) -> None:
        for m in self.metrics:
            self.assertEqual(m.duplicates, 0, m)

    def test_no_batch_jumps(self) -> None:
        for m in self.metrics:
            self.assertEqual(m.batch_jumps, 0, m)

    def test_no_frozen_zero_timers(self) -> None:
        for m in self.metrics:
            self.assertEqual(m.frozen_zero, 0, m)

    def test_no_surface_mismatches(self) -> None:
        for m in self.metrics:
            self.assertEqual(m.surface_mismatches, 0, m)

    def test_local_action_latency(self) -> None:
        slow: list[str] = []
        for m in self.metrics:
            for sample in m.latencies:
                if sample.action in ("expire", "manual_pick", "auto_pick_now", "pause_resume", "reset_timer"):
                    if sample.elapsed_ms > _MAX_LOCAL_MS:
                        slow.append(f"{sample.action}={sample.elapsed_ms:.0f}ms")
        self.assertEqual(slow, [], f"actions exceeded {_MAX_LOCAL_MS}ms: {slow[:10]}")

    def test_queue_ops_do_not_block_timer_owner(self) -> None:
        for m in self.metrics:
            for sample in m.latencies:
                if sample.action.startswith("queue_") and sample.elapsed_ms > 500:
                    self.fail(f"queue op too slow: {sample.action}={sample.elapsed_ms:.0f}ms")


if __name__ == "__main__":
    unittest.main()
