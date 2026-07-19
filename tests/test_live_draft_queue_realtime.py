"""Phase 1 Live Draft real-time: queue mutations stay off the force-save / rescoring critical path."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from draft_state import (
    DRAFT_QUEUE_KEY,
    add_player_to_draft_queue,
    clear_draft_queue,
    move_queue_item_up,
    remove_player_from_draft_queue,
)
from live_draft_queue_persist import (
    DRAFT_QUEUE_AUTOSAVE_SEC,
    DRAFT_QUEUE_PERSIST_DIRTY_KEY,
    flush_draft_queue_persist,
    is_draft_queue_persist_dirty,
    maybe_flush_deferred_draft_queue_autosave,
)
from live_draft_rerun_scope import (
    QUEUE_TICK_KEY,
    live_draft_expensive_recompute_required,
    live_draft_should_skip_recommendations,
    mark_live_draft_queue_tick,
)
from live_draft_safe_mode import request_live_draft_rerun
from live_draft_ui_cache import REC_CACHE_KEY


class QueueRealtimePersistTests(unittest.TestCase):
    def test_add_does_not_force_save(self) -> None:
        session: dict = {}
        with patch("baseball_persistent_state.force_save_baseball_state") as mock_save:
            q, added = add_player_to_draft_queue(session, "Mike Trout")
            self.assertTrue(added)
            self.assertEqual(q, ["Mike Trout"])
            self.assertEqual(session[DRAFT_QUEUE_KEY], ["Mike Trout"])
            mock_save.assert_not_called()
        self.assertTrue(is_draft_queue_persist_dirty(session))

    def test_remove_and_reorder_do_not_force_save(self) -> None:
        session: dict = {DRAFT_QUEUE_KEY: ["A", "B", "C"]}
        with patch("baseball_persistent_state.force_save_baseball_state") as mock_save:
            remove_player_from_draft_queue(session, "B")
            move_queue_item_up(session, 1)
            clear_draft_queue(session)
            mock_save.assert_not_called()
        self.assertEqual(session[DRAFT_QUEUE_KEY], [])
        self.assertTrue(is_draft_queue_persist_dirty(session))

    def test_queue_mutation_preserves_recommendation_cache(self) -> None:
        session: dict = {
            REC_CACHE_KEY: {"key": ("rec",), "tables": {"ok": True}},
            DRAFT_QUEUE_KEY: [],
        }
        add_player_to_draft_queue(session, "Shohei Ohtani")
        self.assertIn(REC_CACHE_KEY, session)
        mark_live_draft_queue_tick(session)
        self.assertFalse(live_draft_expensive_recompute_required(session))
        self.assertNotIn(QUEUE_TICK_KEY, session)
        # Cache not cleared by queue mutate or queue tick.
        self.assertEqual(session[REC_CACHE_KEY]["key"], ("rec",))

    def test_queue_tick_skips_recommendations(self) -> None:
        session: dict = {}
        mark_live_draft_queue_tick(session)
        self.assertTrue(live_draft_should_skip_recommendations(session, {"status": "in_progress"}))

    def test_request_live_draft_rerun_queue_is_light(self) -> None:
        session: dict = {"_live_draft_rerun_count": 0}
        room = {
            "status": "in_progress",
            "draft_board": [],
            "pick_order": [{"Pick": 1} for _ in range(4)],
            "teams": ["A", "B"],
        }
        st = MagicMock()

        def _capture_rerun():
            # Inspect session flags set immediately before st.rerun().
            self.assertTrue(session.get(QUEUE_TICK_KEY))
            self.assertFalse(session.get("_live_draft_force_expensive_recompute"))

        st.rerun.side_effect = _capture_rerun
        with patch("live_draft_safe_mode.is_rerun_allowed", return_value=(True, None)):
            request_live_draft_rerun(st, session, "live_draft_queue", room=room)
        st.rerun.assert_called_once()

    def test_deferred_flush_calls_force_save_once(self) -> None:
        session: dict = {}
        add_player_to_draft_queue(session, "Aaron Judge")
        st = MagicMock()
        with patch("baseball_persistent_state.force_save_baseball_state", return_value=True) as mock_save:
            ok = flush_draft_queue_persist(st, session, reason="live_draft_page_end")
            self.assertTrue(ok)
            mock_save.assert_called_once()
        self.assertFalse(is_draft_queue_persist_dirty(session))

    def test_debounce_waits_before_flush(self) -> None:
        session: dict = {}
        add_player_to_draft_queue(session, "Juan Soto")
        session["_draft_queue_persist_dirty_ts"] = time.time()
        st = MagicMock()
        with patch("baseball_persistent_state.force_save_baseball_state", return_value=True) as mock_save:
            self.assertFalse(maybe_flush_deferred_draft_queue_autosave(st, session))
            mock_save.assert_not_called()
            session["_draft_queue_persist_dirty_ts"] = time.time() - (max(DRAFT_QUEUE_AUTOSAVE_SEC, 2.0) + 0.5)
            self.assertTrue(maybe_flush_deferred_draft_queue_autosave(st, session))
            mock_save.assert_called_once()

    def test_flush_skipped_on_queue_fast_paint(self) -> None:
        session: dict = {}
        add_player_to_draft_queue(session, "Trea Turner")
        session["_draft_queue_persist_dirty_ts"] = time.time() - 10.0
        session["_live_draft_skip_queue_flush_this_run"] = True
        st = MagicMock()
        with patch("baseball_persistent_state.force_save_baseball_state") as mock_save:
            self.assertFalse(maybe_flush_deferred_draft_queue_autosave(st, session))
            mock_save.assert_not_called()

    def test_queue_fast_paint_flag_survives_expensive_check(self) -> None:
        from live_draft_rerun_scope import QUEUE_FAST_PAINT_KEY, consume_live_draft_queue_fast_paint

        session: dict = {}
        mark_live_draft_queue_tick(session)
        self.assertTrue(session.get(QUEUE_FAST_PAINT_KEY))
        self.assertFalse(live_draft_expensive_recompute_required(session))
        self.assertTrue(session.get(QUEUE_FAST_PAINT_KEY))
        self.assertTrue(consume_live_draft_queue_fast_paint(session))
        self.assertFalse(session.get(QUEUE_FAST_PAINT_KEY))


class QueueLatencyProbeTests(unittest.TestCase):
    """Lightweight before/after style probe (engine path; no Streamlit / force_save)."""

    def test_twenty_queue_ops_under_budget(self) -> None:
        session: dict = {}
        names = [f"Player {i}" for i in range(20)]
        t0 = time.perf_counter()
        with patch("baseball_persistent_state.force_save_baseball_state") as mock_save:
            for name in names:
                add_player_to_draft_queue(session, name)
            for name in names:
                remove_player_from_draft_queue(session, name)
            mock_save.assert_not_called()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        # 40 mutations; budget for engine path well under 1s total.
        self.assertLess(elapsed_ms, 1000.0, f"40 queue ops took {elapsed_ms:.1f}ms")
        self.assertEqual(session.get(DRAFT_QUEUE_KEY), [])
        self.assertTrue(session.get(DRAFT_QUEUE_PERSIST_DIRTY_KEY))


if __name__ == "__main__":
    unittest.main()
