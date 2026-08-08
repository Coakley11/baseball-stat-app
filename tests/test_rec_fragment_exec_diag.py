"""Tests for recommendation-fragment execution diagnostics."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from live_draft_heavy_paint_ui import HEAVY_PAINT_DONE_KEY, render_deferred_heavy_paint_fragment
from live_draft_rec_fragment_exec_diag import (
    FRAGMENT_CALLBACK_LEDGER_KEY,
    FRAGMENT_PROBE_COUNTER_KEY,
    RECOMMENDATION_FRAGMENT_RUN_SEQ_KEY,
    append_fragment_callback_ledger,
    enter_recommendation_paint_invocation,
    execution_context_map,
    fragment_callback_ledger_export,
    on_recommendation_fragment_probe_click,
    record_rec_queue_callback_entry,
    render_fragment_callback_ledger_probe,
)


class RecFragmentExecDiagTests(unittest.TestCase):
    def test_fragment_run_seq_increments_independently_of_full_app(self) -> None:
        session: dict[str, Any] = {"_solo_stage1_script_run_seq": 10}
        r1 = enter_recommendation_paint_invocation(session, None, via="fragment")
        session["_solo_stage1_script_run_seq"] = 10
        r2 = enter_recommendation_paint_invocation(session, None, via="fragment")
        self.assertEqual(r1["recommendation_fragment_run_seq"], 1)
        self.assertEqual(r2["recommendation_fragment_run_seq"], 2)
        self.assertEqual(r1["full_app_run_seq"], 10)
        self.assertTrue(r1["fragment_context"])
        self.assertEqual(session[RECOMMENDATION_FRAGMENT_RUN_SEQ_KEY], 2)

    def test_durable_callback_ledger_survives_without_dom(self) -> None:
        session: dict[str, Any] = {RECOMMENDATION_FRAGMENT_RUN_SEQ_KEY: 3}
        record_rec_queue_callback_entry(
            session,
            event_id="evt_a",
            room_id="ROOM1",
            pick_index=0,
            player_id="231",
            player_name="Francisco Lindor",
            widget_key="rec_card_queue_ROOM1_0_231_rec_card",
            queue_before=[],
        )
        export = fragment_callback_ledger_export(session)
        self.assertEqual(export["ledger_len"], 1)
        self.assertTrue(export["last"].get("callback_entered"))
        self.assertEqual(export["last"]["recommendation_fragment_run_seq"], 3)

    def test_fragment_probe_callback_increments_counter(self) -> None:
        session: dict[str, Any] = {}
        on_recommendation_fragment_probe_click(session, "R1", 0, "rec_fragment_widget_probe_R1_0_diag")
        self.assertEqual(session[FRAGMENT_PROBE_COUNTER_KEY], 1)
        book = session[FRAGMENT_CALLBACK_LEDGER_KEY]
        self.assertEqual(book[-1]["source"], "fragment_widget_probe")

    def test_ledger_probe_renders_when_solo_diag(self) -> None:
        st = MagicMock()
        session: dict[str, Any] = {}
        append_fragment_callback_ledger(
            session,
            {"event_id": "x", "callback_entered": True, "source": "fragment_widget_probe"},
        )
        with patch(
            "live_draft_rec_fragment_exec_diag._solo_diag_enabled",
            return_value=True,
        ):
            render_fragment_callback_ledger_probe(st, session)
        html = str(st.markdown.call_args[0][0])
        self.assertIn("solo-stage1-rec-fragment-callback-ledger", html)

    def test_heavy_paint_invokes_fragment_paint_counter(self) -> None:
        st = MagicMock()
        session: dict[str, Any] = {HEAVY_PAINT_DONE_KEY: False}
        painted = {"n": 0}

        def body() -> None:
            painted["n"] += 1

        with patch(
            "live_draft_fast_solo_start.should_defer_heavy_first_paint",
            return_value=False,
        ):
            with patch("live_draft_fast_solo_start.note_start_stage"):
                render_deferred_heavy_paint_fragment(st, session, body)
        self.assertEqual(painted["n"], 1)
        self.assertGreaterEqual(session.get(RECOMMENDATION_FRAGMENT_RUN_SEQ_KEY, 0), 1)

    def test_execution_context_map_names_pause_vs_fragment(self) -> None:
        m = execution_context_map()
        self.assertIn("pause_control", m)
        self.assertIn("recommendation_fragment_wrapper", m)
        self.assertNotEqual(m["pause_control"], m["recommendation_cards"])

    def test_full_app_unchanged_does_not_block_fragment_seq_advance(self) -> None:
        session: dict[str, Any] = {"_solo_stage1_script_run_seq": 15}
        enter_recommendation_paint_invocation(session, None, via="fragment")
        self.assertEqual(session["_solo_stage1_script_run_seq"], 15)
        self.assertEqual(session[RECOMMENDATION_FRAGMENT_RUN_SEQ_KEY], 1)

    def test_classify_fragment_exec_f1_and_f4(self) -> None:
        from scripts.stage1_rec_fragment_exec_scrape import classify_fragment_exec_comparison

        self.assertEqual(
            classify_fragment_exec_comparison(
                pause_functional=True,
                probe_ledger_last={"callback_entered": True},
                francisco_ledger_last={"callback_entered": False},
                probe_dom_click=True,
                francisco_dom_click=True,
            ),
            "QUEUE1C3A2F1",
        )
        self.assertEqual(
            classify_fragment_exec_comparison(
                pause_functional=True,
                probe_ledger_last={"callback_entered": False},
                francisco_ledger_last={"callback_entered": False},
                probe_dom_click=True,
                francisco_dom_click=True,
            ),
            "QUEUE1C3A2F4",
        )


if __name__ == "__main__":
    unittest.main()
