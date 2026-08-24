"""Product Add-to-Queue: ScriptRun registration (not run_every) → callback → queue +1."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from live_draft_heavy_paint_ui import HEAVY_PAINT_DONE_KEY, render_deferred_heavy_paint_fragment
from live_draft_rec_queue_click_trace import (
    build_rec_card_queue_widget_key,
    lifecycle_for_widget,
    note_rec_queue_widget_button_rendered,
)
from live_draft_room_ui import execute_rec_card_queue_click


ROOM = "C2EA863B"


class RecCardQueueClickCallbackContractTests(unittest.TestCase):
    def test_post_heavy_paint_owner_is_script_run_not_run_every(self) -> None:
        st = MagicMock()
        fragment_kwargs: list[dict[str, Any]] = []

        def _fragment_decorator(**kwargs):
            fragment_kwargs.append(dict(kwargs))
            return lambda fn: fn

        st.fragment = _fragment_decorator
        session: dict[str, Any] = {HEAVY_PAINT_DONE_KEY: True}
        with patch("live_draft_fast_solo_start.should_defer_heavy_first_paint", return_value=False):
            with patch("live_draft_fast_solo_start.note_start_stage"):
                render_deferred_heavy_paint_fragment(
                    st,
                    session,
                    lambda: None,
                    paint_interactive=lambda: None,
                )
        self.assertEqual(session.get("_live_draft_rec_queue_interactive_owner"), "script_run_no_run_every")
        self.assertEqual(fragment_kwargs, [])

    def test_button_render_records_server_registration_for_stable_key(self) -> None:
        session: dict[str, Any] = {
            HEAVY_PAINT_DONE_KEY: True,
            "_solo_stage1_script_run_seq": 7,
            "_live_draft_rec_queue_interactive_owner": "script_run_no_run_every",
            "_solo_stage1_last_recommendation_paint": {"via": "full_page_interactive_live"},
        }
        key = build_rec_card_queue_widget_key(
            room_id=ROOM, pick_index=0, stable_key="231", surface="rec_card"
        )
        self.assertEqual(key, f"rec_card_queue_{ROOM}_0_231_rec_card")
        note_rec_queue_widget_button_rendered(session, widget_key=key)
        lc = lifecycle_for_widget(session, key)
        self.assertTrue(lc.get("server_registered"))
        self.assertEqual(lc.get("interactive_owner"), "script_run_no_run_every")
        self.assertEqual(lc.get("paint_via_at_render"), "full_page_interactive_live")
        self.assertEqual(lc.get("callback_id"), "_on_rec_queue_click")
        self.assertTrue(lc.get("widget_rendered_this_run"))

    def test_execute_callback_adds_exactly_one_and_marks_rerun_tick(self) -> None:
        session: dict[str, Any] = {
            "draft_queue": [],
            "_live_draft_rec_queue_interactive_owner": "script_run_no_run_every",
            "_solo_stage1_last_recommendation_paint": {"via": "full_page_interactive_live"},
        }
        key = build_rec_card_queue_widget_key(
            room_id=ROOM, pick_index=0, stable_key="231", surface="rec_card"
        )
        with patch("live_draft_rerun_scope.mark_live_draft_queue_tick") as tick:
            execute_rec_card_queue_click(
                session,
                name="Francisco Lindor",
                event_id="evt1",
                widget_key=key,
                room_id=ROOM,
                pick_idx=0,
                player_id="231",
            )
            self.assertGreaterEqual(tick.call_count, 1)
        self.assertEqual(session.get("draft_queue"), ["Francisco Lindor"])
        ledger = session.get("_live_draft_rec_fragment_callback_ledger") or []
        self.assertTrue(ledger)
        last = ledger[-1]
        self.assertTrue(last.get("callback_entered"))
        self.assertEqual(last.get("player_id"), "231")
        self.assertEqual(last.get("interactive_owner"), "script_run_no_run_every")

    def test_three_distinct_keys_each_mutate_queue_by_one(self) -> None:
        roster = [
            ("Francisco Lindor", "231"),
            ("Ketel Marte", "414"),
            ("Pete Alonso", "576"),
        ]
        session: dict[str, Any] = {
            "draft_queue": [],
            "_live_draft_rec_queue_interactive_owner": "script_run_no_run_every",
            "_solo_stage1_script_run_seq": 3,
            "_solo_stage1_last_recommendation_paint": {"via": "full_page_interactive_live"},
            HEAVY_PAINT_DONE_KEY: True,
        }
        keys: list[str] = []
        with patch("live_draft_rerun_scope.mark_live_draft_queue_tick") as tick:
            for i, (name, pid) in enumerate(roster):
                key = build_rec_card_queue_widget_key(
                    room_id=ROOM, pick_index=0, stable_key=pid, surface="rec_card"
                )
                keys.append(key)
                note_rec_queue_widget_button_rendered(session, widget_key=key)
                before = len(list(session.get("draft_queue") or []))
                execute_rec_card_queue_click(
                    session,
                    name=name,
                    event_id=f"evt{i}",
                    widget_key=key,
                    room_id=ROOM,
                    pick_idx=0,
                    player_id=pid,
                )
                after = list(session.get("draft_queue") or [])
                self.assertEqual(len(after), before + 1)
                self.assertEqual(after[-1], name)
                lc = lifecycle_for_widget(session, key)
                self.assertTrue(lc.get("server_registered"))
                self.assertEqual(lc.get("interactive_owner"), "script_run_no_run_every")
        self.assertEqual(len(set(keys)), 3)
        self.assertEqual(
            session.get("draft_queue"),
            ["Francisco Lindor", "Ketel Marte", "Pete Alonso"],
        )
        self.assertGreaterEqual(tick.call_count, 3)
        ledger = session.get("_live_draft_rec_fragment_callback_ledger") or []
        self.assertEqual(len(ledger), 3)
        self.assertEqual([r.get("player_id") for r in ledger], ["231", "414", "576"])

    def test_no_duplicate_stable_keys_across_three_cards(self) -> None:
        keys = [
            build_rec_card_queue_widget_key(
                room_id=ROOM, pick_index=0, stable_key=pid, surface="rec_card"
            )
            for pid in ("231", "414", "576")
        ]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(k.endswith("_rec_card") for k in keys))
        self.assertTrue(all(ROOM in k for k in keys))


if __name__ == "__main__":
    unittest.main()
