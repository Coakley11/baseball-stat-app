"""Rendered mixed-action matrix — mirrors accelerated harness pick cycles (4×8 × 3)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from live_draft_pick_commit import PickCommitResult
from live_draft_timer_logic import live_draft_current_slot
from tests.live_draft_accelerated_harness import assert_no_timer_frozen, assert_surfaces_agree

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "live_draft_mixed_matrix_apptest.py"
_PICKS = 32
_REPEAT = 3
_TIMEOUT = 240


def _fast_score(available, roster_df, rule_key, target_counts, config=None):
    scored = available.copy()
    if "Decision Score" not in scored.columns:
        scored["Decision Score"] = range(len(scored), 0, -1)
    return scored.sort_values("Decision Score", ascending=False), []


def _noop_persist(*_args, **_kwargs):
    return PickCommitResult(
        ok=True,
        message="ok",
        error="",
        commit_path="mixed_matrix_apptest",
        board_size_before=0,
        board_size_after=0,
        current_pick_index_before=0,
        current_pick_index_after=0,
    )


def _last_button(at, key: str):
    buttons = [b for b in at.button if b.key == key]
    return buttons[-1] if buttons else None


def _ss_get(at, key: str, default=None):
    if key in at.session_state:
        return at.session_state[key]
    return default


def _click_last(at, key: str):
    btn = _last_button(at, key)
    assert btn is not None, f"missing button {key}"
    btn.click().run()
    assert not at.exception, f"exception after clicking {key}"


class LiveDraftMixedMatrixRenderedTests(unittest.TestCase):
    def _during_clock_ops(self, pick_cycle: int, at) -> None:
        room = at.session_state["live_draft_room"]
        if str(room.get("status") or "") != "in_progress":
            return
        assert_surfaces_agree(at.session_state, room, label=f"cycle_{pick_cycle}_start")
        assert_no_timer_frozen(room)

        if pick_cycle == 7:
            _click_last(at, "matrix_queue_add")
        elif pick_cycle == 9:
            _click_last(at, "matrix_queue_remove")
        elif pick_cycle == 11:
            _click_last(at, "live_draft_pause")
            self.assertEqual(at.session_state["live_draft_room"].get("status"), "paused")
            _click_last(at, "live_draft_resume")
            self.assertEqual(at.session_state["live_draft_room"].get("status"), "in_progress")
        elif pick_cycle == 12:
            _click_last(at, "live_draft_reset_timer")
        elif pick_cycle == 13:
            _click_last(at, "matrix_queue_reorder")
        elif pick_cycle == 14:
            _click_last(at, "matrix_nav_away")
            _click_last(at, "matrix_nav_back")
            assert_surfaces_agree(
                at.session_state,
                at.session_state["live_draft_room"],
                label="nav_return",
            )

    def _complete_pick(self, pick_cycle: int, at) -> dict:
        room = at.session_state["live_draft_room"]
        board_before = len(room.get("draft_board") or [])
        if pick_cycle == 6:
            _click_last(at, "matrix_manual_pick")
        elif pick_cycle in (8, 15, 22):
            _click_last(at, "live_draft_auto_now")
        else:
            _click_last(at, "matrix_force_expire")

        room = at.session_state["live_draft_room"]
        board = list(room.get("draft_board") or [])
        self.assertEqual(len(board), board_before + 1, f"board lag at cycle {pick_cycle}")
        idx = int(room.get("current_pick_index") or -1)
        self.assertEqual(idx, pick_cycle, f"index lag at cycle {pick_cycle}")
        assert_surfaces_agree(at.session_state, room, label=f"after_pick_{pick_cycle}")
        if str(room.get("status") or "") == "in_progress":
            assert_no_timer_frozen(room)
        paint = _ss_get(at, "_live_draft_paint_snapshot") or {}
        if isinstance(paint, dict) and paint:
            slot = live_draft_current_slot(room)
            if slot and paint.get("team_on_clock"):
                self.assertEqual(str(paint.get("team_on_clock")), str(slot.get("Team") or ""))
        return board[-1]

    def _run_mixed_matrix_once(self) -> int:
        from streamlit.testing.v1 import AppTest

        seen: set[str] = set()
        with patch("live_draft_autopick.score_available_for_rule", side_effect=_fast_score):
            with patch("live_draft_pick_commit.persist_applied_pick", side_effect=_noop_persist):
                at = AppTest.from_file(str(_FIXTURE), default_timeout=_TIMEOUT)
                at.run()
                self.assertFalse(at.exception)

                for pick_cycle in range(1, _PICKS + 1):
                    room = at.session_state["live_draft_room"]
                    if str(room.get("status") or "") == "complete":
                        break
                    self._during_clock_ops(pick_cycle, at)
                    last = self._complete_pick(pick_cycle, at)
                    pid = str(last.get("playerID") or "")
                    self.assertTrue(pid)
                    self.assertNotIn(pid, seen, f"duplicate at cycle {pick_cycle}")
                    seen.add(pid)

                room = at.session_state["live_draft_room"]
                self.assertEqual(str(room.get("status") or ""), "complete")
                self.assertEqual(len(room.get("draft_board") or []), _PICKS)
                return len(seen)

    def test_mixed_matrix_thirty_two_pick_rendered_three_runs(self) -> None:
        for run in range(_REPEAT):
            count = self._run_mixed_matrix_once()
            self.assertEqual(count, _PICKS, f"run {run + 1}")


if __name__ == "__main__":
    unittest.main()
