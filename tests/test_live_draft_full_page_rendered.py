"""Rendered full Live Draft page — strict 32-pick surface agreement (4×8)."""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest.mock import patch

from live_draft_pick_commit import PickCommitResult
from tests.live_draft_accelerated_harness import assert_no_timer_frozen
from live_draft_timer_logic import live_draft_current_slot

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "live_draft_full_page_apptest.py"
_PICKS = 32
_TEAMS = 4
_PICKS_PER_TEAM = 8
_REPEAT = 3
_TIMEOUT = 180


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
        commit_path="full_page_apptest",
        board_size_before=0,
        board_size_after=0,
        current_pick_index_before=0,
        current_pick_index_after=0,
    )


def _expire_button(at):
    buttons = [b for b in at.button if b.key == "full_page_force_expire"]
    if not buttons:
        return None
    return buttons[-1]


class LiveDraftFullPageRenderedTests(unittest.TestCase):
    def _run_full_draft_once(self) -> tuple[int, list[float]]:
        from streamlit.testing.v1 import AppTest

        latencies: list[float] = []
        with patch("live_draft_autopick.score_available_for_rule", side_effect=_fast_score):
            with patch("live_draft_pick_commit.persist_applied_pick", side_effect=_noop_persist):
                at = AppTest.from_file(str(_FIXTURE), default_timeout=_TIMEOUT)
                at.run()
                self.assertFalse(at.exception)

                room = at.session_state["live_draft_room"]
                self.assertEqual(int(room.get("current_pick_index") or 0), 0)
                self.assertEqual(len(room.get("draft_board") or []), 0)

                seen: set[str] = set()
                for n in range(1, _PICKS + 1):
                    expire = _expire_button(at)
                    self.assertIsNotNone(expire, f"missing expire button at pick {n}")
                    t0 = time.perf_counter()
                    expire.click().run()
                    latencies.append((time.perf_counter() - t0) * 1000.0)
                    self.assertFalse(at.exception, f"exception on pick {n}")

                    room = at.session_state["live_draft_room"]
                    board = list(room.get("draft_board") or [])
                    self.assertEqual(len(board), n, f"board length after pick {n}")
                    pid = str(board[-1].get("playerID") or "")
                    self.assertTrue(pid, f"missing player id on pick {n}")
                    self.assertNotIn(pid, seen, f"duplicate player on pick {n}")
                    seen.add(pid)

                    idx = int(room.get("current_pick_index") or -1)
                    self.assertEqual(idx, n, f"current_pick_index lag after pick {n}")

                    if "_live_draft_paint_snapshot" in at.session_state:
                        paint = at.session_state["_live_draft_paint_snapshot"]
                    else:
                        paint = {}
                    if isinstance(paint, dict) and paint:
                        self.assertEqual(
                            int(paint.get("current_pick_index") or -1),
                            n,
                            f"paint index lag after pick {n}",
                        )
                        slot = live_draft_current_slot(room)
                        if slot and paint.get("team_on_clock"):
                            self.assertEqual(
                                str(paint.get("team_on_clock") or ""),
                                str(slot.get("Team") or ""),
                                f"paint team mismatch after pick {n}",
                            )
                        if paint.get("current_pick") is not None and slot:
                            self.assertEqual(
                                int(paint.get("current_pick") or 0),
                                int(slot.get("Pick") or 0),
                                f"paint pick number mismatch after pick {n}",
                            )

                    if str(room.get("status") or "") == "in_progress":
                        assert_no_timer_frozen(room)
                    else:
                        self.assertEqual(n, _PICKS)

                return len(seen), latencies

    def test_full_page_thirty_two_pick_rendered_three_runs(self) -> None:
        for run in range(_REPEAT):
            count, latencies = self._run_full_draft_once()
            self.assertEqual(count, _PICKS, f"run {run + 1}")
            self.assertEqual(len(latencies), _PICKS)
            # Latency SLO is enforced in test_live_draft_accelerated_full_draft.py (harness-only).
            # Full-page AppTest includes every widget and is intentionally slower.


if __name__ == "__main__":
    unittest.main()
