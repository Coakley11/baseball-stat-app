"""Queue fast-paint must never abort the active-draft full page render."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


class QueueFastPaintNoPageStopTests(unittest.TestCase):
    def test_queue_tick_does_not_set_fast_paint(self) -> None:
        from live_draft_rerun_scope import (
            QUEUE_FAST_PAINT_KEY,
            QUEUE_TICK_KEY,
            live_draft_expensive_recompute_required,
            mark_live_draft_queue_tick,
        )

        session: dict = {}
        mark_live_draft_queue_tick(session)
        self.assertTrue(session.get(QUEUE_TICK_KEY))
        self.assertFalse(session.get(QUEUE_FAST_PAINT_KEY))
        self.assertFalse(live_draft_expensive_recompute_required(session))
        self.assertFalse(session.get(QUEUE_FAST_PAINT_KEY))
        self.assertFalse(session.get(QUEUE_TICK_KEY))

    def test_consume_never_authorizes_stop(self) -> None:
        from live_draft_rerun_scope import (
            QUEUE_FAST_PAINT_KEY,
            consume_live_draft_queue_fast_paint,
        )

        session = {QUEUE_FAST_PAINT_KEY: True}
        self.assertFalse(consume_live_draft_queue_fast_paint(session))
        self.assertFalse(session.get(QUEUE_FAST_PAINT_KEY))
        ignored = session.get("_live_draft_queue_fast_paint_ignored")
        self.assertIsInstance(ignored, dict)
        self.assertFalse(ignored.get("stop_authorized"))

    def test_leftover_flag_cleared_on_active_page_enter(self) -> None:
        from live_draft_creation_trace import (
            POST_CREATE_OPEN_KEY,
            arm_post_create_open,
            mark_active_draft_page_entered,
        )
        from live_draft_rerun_scope import QUEUE_FAST_PAINT_KEY

        session = {QUEUE_FAST_PAINT_KEY: True, POST_CREATE_OPEN_KEY: True}
        arm_post_create_open(session, lifecycle="active_draft")
        self.assertFalse(session.get(QUEUE_FAST_PAINT_KEY))
        session[QUEUE_FAST_PAINT_KEY] = True
        mark_active_draft_page_entered(session, lifecycle="active_draft")
        self.assertFalse(session.get(QUEUE_FAST_PAINT_KEY))

    def test_flag_does_not_survive_into_next_run_after_clear(self) -> None:
        from live_draft_rerun_scope import (
            QUEUE_FAST_PAINT_KEY,
            clear_live_draft_queue_fast_paint,
            mark_live_draft_queue_tick,
        )

        session = {QUEUE_FAST_PAINT_KEY: True}
        clear_live_draft_queue_fast_paint(session, reason="active_page_full_render")
        self.assertFalse(session.get(QUEUE_FAST_PAINT_KEY))
        mark_live_draft_queue_tick(session)
        self.assertFalse(session.get(QUEUE_FAST_PAINT_KEY))

    def test_streamlit_active_path_has_no_queue_stop(self) -> None:
        """Static guard: no st.stop() immediately after queue fast-paint consume."""
        app_path = Path(__file__).resolve().parents[1] / "streamlit_app.py"
        src = app_path.read_text(encoding="utf-8")
        self.assertIn("NEVER page-level st.stop() for queue fast-paint", src)
        # Old abort pattern must be gone.
        self.assertNotIn("if (not _post_create_open) and consume_live_draft_queue_fast_paint", src)
        # Consume must not gate a stop in the active-draft block.
        tree = ast.parse(src)
        stop_after_consume = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test_src = ast.dump(node.test)
            if "consume_live_draft_queue_fast_paint" not in test_src:
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and getattr(child.func, "attr", "") == "stop":
                    stop_after_consume = True
        self.assertFalse(stop_after_consume)

    def test_active_page_receipt_checkpoints(self) -> None:
        from live_draft_render_checkpoints import (
            ACTIVE_PAGE_RECEIPT_KEY,
            note_active_page_receipt,
            reset_live_draft_render_checkpoints,
        )

        session: dict = {}
        reset_live_draft_render_checkpoints(session)
        for key in (
            "active_page_render_started",
            "control_center_complete",
            "queue_complete",
            "board_complete",
            "recommendations_complete",
            "rosters_complete",
            "active_page_render_complete",
        ):
            note_active_page_receipt(session, key, True)
        receipt = session[ACTIVE_PAGE_RECEIPT_KEY]
        self.assertTrue(receipt["active_page_render_started"])
        self.assertTrue(receipt["control_center_complete"])
        self.assertTrue(receipt["queue_complete"])
        self.assertTrue(receipt["board_complete"])
        self.assertTrue(receipt["recommendations_complete"])
        self.assertTrue(receipt["rosters_complete"])
        self.assertTrue(receipt["active_page_render_complete"])
        self.assertFalse(receipt["page_level_queue_stop"])


if __name__ == "__main__":
    unittest.main()
