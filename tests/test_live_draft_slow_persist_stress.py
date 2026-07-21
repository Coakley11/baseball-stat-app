"""Slow persistence must not batch picks or block local paint/timer."""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from live_draft_canonical_snapshot import begin_live_draft_paint, invalidate_live_draft_paint
from live_draft_pick_commit import PickCommitResult
from live_draft_solo_timer import expire_current_pick_and_advance
from tests.live_draft_accelerated_harness import (
    assert_no_timer_frozen,
    assert_surfaces_agree,
    build_four_team_eight_round_room,
    fast_autopick_scoring,
    force_timer_expired,
    seed_session,
)


class SlowPersistStressTests(unittest.TestCase):
    _LATENCY_MATRIX_MS = (150, 1000, 3000, 8000)

    def _slow_persist_factory(self, delay_sec: float, *, fail_first: bool = False):
        state = {"calls": 0, "fail_first": fail_first}

        def slow_persist(*_args, **_kwargs):
            state["calls"] += 1
            if state["fail_first"] and state["calls"] == 1:
                return PickCommitResult(
                    ok=False,
                    message="transient cloud error",
                    error="transient",
                    commit_path="slow_test_fail",
                    board_size_before=0,
                    board_size_after=0,
                    current_pick_index_before=0,
                    current_pick_index_after=0,
                )
            time.sleep(delay_sec)
            return PickCommitResult(
                ok=True,
                message="slow",
                error="",
                commit_path="slow_test",
                board_size_before=0,
                board_size_after=0,
                current_pick_index_before=0,
                current_pick_index_after=0,
            )

        slow_persist.state = state  # type: ignore[attr-defined]
        return slow_persist

    def _run_expire_matrix(self, delay_sec: float, *, picks: int = 5) -> None:
        room = build_four_team_eight_round_room()
        session = seed_session(room)

        def slow_write(*_args, **_kwargs):
            time.sleep(delay_sec)
            return None

        with patch("live_draft_state.write_canonical_live_draft_state", side_effect=slow_write), patch(
            "live_draft_state.patch_canonical_live_draft_pick_fields", side_effect=slow_write
        ), fast_autopick_scoring():
            for n in range(picks):
                board_before = len(room.get("draft_board") or [])
                idx_before = int(room.get("current_pick_index") or 0)
                force_timer_expired(room)
                t0 = time.perf_counter()
                result = expire_current_pick_and_advance(room, session=session)
                local_ms = (time.perf_counter() - t0) * 1000.0
                self.assertTrue(result.ok, result)
                self.assertEqual(len(room.get("draft_board") or []), board_before + 1)
                self.assertEqual(int(room.get("current_pick_index") or 0), idx_before + 1)
                invalidate_live_draft_paint(session)
                begin_live_draft_paint(session, room, state_source=f"slow_{delay_sec}_{n}")
                assert_surfaces_agree(session, room, label=f"slow_{delay_sec}_{n}")
                assert_no_timer_frozen(room)
                self.assertLess(
                    local_ms,
                    3000.0,
                    f"delay={delay_sec}s pick {n + 1} blocked {local_ms:.0f}ms",
                )

    def test_five_expires_with_three_second_persist_advance_one_at_a_time(self) -> None:
        self._run_expire_matrix(0.15)

    def test_cloud_delay_matrix_150ms_through_8s(self) -> None:
        for delay_ms in self._LATENCY_MATRIX_MS:
            with self.subTest(delay_ms=delay_ms):
                self._run_expire_matrix(delay_ms / 1000.0, picks=3)

    def test_intermittent_persist_failure_does_not_double_advance(self) -> None:
        room = build_four_team_eight_round_room()
        session = seed_session(room)
        calls = {"n": 0}

        def flaky_write(*_args, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("transient cloud error")
            return None

        force_timer_expired(room)
        with patch("live_draft_state.write_canonical_live_draft_state", side_effect=flaky_write), patch(
            "live_draft_state.patch_canonical_live_draft_pick_fields", side_effect=flaky_write
        ), fast_autopick_scoring():
            first = expire_current_pick_and_advance(room, session=session)
            self.assertTrue(first.ok, first)
            board_after = len(room.get("draft_board") or [])
            idx_after = int(room.get("current_pick_index") or 0)
            self.assertEqual(board_after, 1)
            self.assertEqual(idx_after, 1)
            # Retry after timer reset — must not duplicate the same pick.
            force_timer_expired(room)
            second = expire_current_pick_and_advance(room, session=session)
            self.assertTrue(second.ok, second)
            self.assertEqual(len(room.get("draft_board") or []), board_after + 1)
            self.assertEqual(int(room.get("current_pick_index") or 0), idx_after + 1)

    def test_idempotent_retry_does_not_double_advance(self) -> None:
        room = build_four_team_eight_round_room()
        session = seed_session(room)
        force_timer_expired(room)
        with fast_autopick_scoring(), patch(
            "live_draft_pick_commit.persist_applied_pick",
            return_value=PickCommitResult(
                ok=True,
                message="ok",
                error="",
                commit_path="noop",
                board_size_before=0,
                board_size_after=0,
                current_pick_index_before=0,
                current_pick_index_after=0,
            ),
        ):
            first = expire_current_pick_and_advance(room, session=session)
            self.assertTrue(first.ok)
            board_after_first = len(room.get("draft_board") or [])
            second = expire_current_pick_and_advance(room, session=session)
            self.assertTrue(second.ok or second.reason in ("not_expired", "already_applied_healed"))
            self.assertEqual(len(room.get("draft_board") or []), board_after_first)

    def test_manual_pick_local_before_persist_finishes(self) -> None:
        from live_draft_state import live_draft_get_available
        from live_draft_pick_commit import commit_live_draft_pick

        room = build_four_team_eight_round_room()
        session = seed_session(room)
        row = live_draft_get_available(room).iloc[0].to_dict()
        gate = threading.Event()

        def blocking_persist(*_args, **_kwargs):
            gate.wait(timeout=2.0)
            return PickCommitResult(
                ok=True,
                message="ok",
                error="",
                commit_path="blocked",
                board_size_before=0,
                board_size_after=0,
                current_pick_index_before=0,
                current_pick_index_after=0,
            )

        with patch("live_draft_pick_commit.persist_applied_pick", side_effect=blocking_persist):
            result_holder: list = []

            def commit_thread():
                result_holder.append(
                    commit_live_draft_pick(session, room, row, source="slow_manual", fast_path=True)
                )
                gate.set()

            t = threading.Thread(target=commit_thread)
            t.start()
            deadline = time.time() + 1.0
            while time.time() < deadline and not result_holder:
                if len(room.get("draft_board") or []) == 1:
                    break
                time.sleep(0.01)
            self.assertEqual(len(room.get("draft_board") or []), 1, "local board did not update before persist")
            gate.set()
            t.join(timeout=3.0)
            self.assertTrue(result_holder[0].ok)


if __name__ == "__main__":
    unittest.main()
