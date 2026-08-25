"""Pre-DONE production-equivalent: fragment compute must not own Add-to-Queue buttons."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from live_draft_heavy_paint_ui import HEAVY_PAINT_DONE_KEY, render_deferred_heavy_paint_fragment
from live_draft_rec_fragment_exec_diag import enter_recommendation_paint_invocation
from live_draft_rec_queue_click_trace import (
    build_rec_card_queue_widget_key,
    lifecycle_for_widget,
    note_rec_queue_widget_button_rendered,
)
from live_draft_room_ui import execute_rec_card_queue_click


ROOM = "E195B517"


class PreDoneQueueClickOwnershipTests(unittest.TestCase):
    def test_fragment_compute_marks_deferred_owner_without_button_registration(self) -> None:
        st = MagicMock()
        session: dict[str, Any] = {"_live_draft_defer_heavy_loading": True}
        interactive = {"n": 0}

        def _fragment_decorator(**kwargs):
            def _wrap(fn):
                st._heavy_frag_fn = fn
                return fn

            return _wrap

        st.fragment = _fragment_decorator

        def paint_body() -> None:
            enter_recommendation_paint_invocation(session, st, via="fragment")
            self.assertTrue(session.get("_solo_stage1_in_fragment_run"))
            # Product paint_body must only prepare — simulate owner latch used in streamlit_app.
            session["_live_draft_rec_queue_interactive_owner"] = "deferred_to_script_run_handoff"

        def paint_interactive() -> None:
            interactive["n"] += 1
            session["_live_draft_rec_queue_interactive_owner"] = "script_run_no_run_every"
            enter_recommendation_paint_invocation(session, st, via="full_page_interactive_live")
            key = build_rec_card_queue_widget_key(
                room_id=ROOM, pick_index=0, stable_key="231", surface="rec_card"
            )
            note_rec_queue_widget_button_rendered(session, widget_key=key)

        with patch("live_draft_fast_solo_start.should_defer_heavy_first_paint", return_value=False):
            with patch("live_draft_fast_solo_start.note_start_stage"):
                with patch("live_draft_fast_solo_start.clear_defer_heavy_first_paint"):
                    render_deferred_heavy_paint_fragment(
                        st,
                        session,
                        paint_body,
                        paint_interactive=paint_interactive,
                    )
                    st._heavy_frag_fn()

        self.assertTrue(session.get(HEAVY_PAINT_DONE_KEY))
        self.assertEqual(interactive["n"], 0)
        self.assertEqual(session.get("_live_draft_rec_queue_interactive_owner"), "pending_script_run_handoff")
        st.rerun.assert_called()

        # Post-rerun ScriptRun ownership path (production handoff).
        with patch("live_draft_fast_solo_start.should_defer_heavy_first_paint", return_value=False):
            with patch("live_draft_fast_solo_start.note_start_stage"):
                render_deferred_heavy_paint_fragment(
                    st,
                    session,
                    paint_body,
                    paint_interactive=paint_interactive,
                )

        self.assertEqual(interactive["n"], 1)
        self.assertEqual(session.get("_live_draft_rec_queue_interactive_owner"), "script_run_no_run_every")
        key = build_rec_card_queue_widget_key(
            room_id=ROOM, pick_index=0, stable_key="231", surface="rec_card"
        )
        lc = lifecycle_for_widget(session, key)
        self.assertTrue(lc.get("server_registered"))
        self.assertTrue(lc.get("callback_attached"))
        self.assertEqual(lc.get("paint_via_at_render"), "full_page_interactive_live")
        self.assertFalse(lc.get("inside_fragment"))
        self.assertIsNone(lc.get("fragment_run_every"))
        self.assertTrue(lc.get("heavy_paint_done_at_render"))

    def test_pre_done_handoff_then_click_mutates_queue_and_ticks(self) -> None:
        session: dict[str, Any] = {
            HEAVY_PAINT_DONE_KEY: True,
            "draft_queue": [],
            "_live_draft_rec_queue_interactive_owner": "script_run_no_run_every",
            "_solo_stage1_last_recommendation_paint": {"via": "full_page_interactive_live"},
            "_solo_stage1_script_run_seq": 4,
            "_solo_stage1_in_fragment_run": False,
        }
        roster = [
            ("Francisco Lindor", "231"),
            ("Ketel Marte", "414"),
            ("Pete Alonso", "576"),
        ]
        with patch("live_draft_rerun_scope.mark_live_draft_queue_tick") as tick:
            for name, pid in roster:
                key = build_rec_card_queue_widget_key(
                    room_id=ROOM, pick_index=0, stable_key=pid, surface="rec_card"
                )
                note_rec_queue_widget_button_rendered(session, widget_key=key)
                lc = lifecycle_for_widget(session, key)
                self.assertTrue(lc.get("server_registered"))
                self.assertFalse(lc.get("inside_fragment"))
                self.assertEqual(lc.get("interactive_owner"), "script_run_no_run_every")
                before = len(list(session.get("draft_queue") or []))
                execute_rec_card_queue_click(
                    session,
                    name=name,
                    event_id=f"e{pid}",
                    widget_key=key,
                    room_id=ROOM,
                    pick_idx=0,
                    player_id=pid,
                )
                self.assertEqual(len(session.get("draft_queue") or []), before + 1)
        self.assertEqual(
            session.get("draft_queue"),
            ["Francisco Lindor", "Ketel Marte", "Pete Alonso"],
        )
        self.assertGreaterEqual(tick.call_count, 3)
        ledger = session.get("_live_draft_rec_fragment_callback_ledger") or []
        self.assertEqual([r.get("player_id") for r in ledger], ["231", "414", "576"])

    def test_fragment_registration_is_flagged_as_bad_owner_if_it_happens(self) -> None:
        session: dict[str, Any] = {
            HEAVY_PAINT_DONE_KEY: False,
            "_solo_stage1_in_fragment_run": True,
            "_solo_stage1_last_recommendation_paint": {"via": "fragment"},
            "_solo_stage1_script_run_seq": 2,
        }
        key = build_rec_card_queue_widget_key(
            room_id=ROOM, pick_index=0, stable_key="231", surface="rec_card"
        )
        note_rec_queue_widget_button_rendered(session, widget_key=key)
        lc = lifecycle_for_widget(session, key)
        self.assertTrue(lc.get("inside_fragment"))
        self.assertEqual(lc.get("fragment_run_every"), 1)
        self.assertFalse(lc.get("heavy_paint_done_at_render"))
        self.assertEqual(lc.get("paint_via_at_render"), "fragment")


if __name__ == "__main__":
    unittest.main()
