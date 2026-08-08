"""Observability tests for fragment exec gate classification and heavy-paint ledger re-emit."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from live_draft_heavy_paint_ui import HEAVY_PAINT_DONE_KEY, render_deferred_heavy_paint_fragment
from live_draft_rec_fragment_exec_diag import (
    FRAGMENT_CALLBACK_LEDGER_KEY,
    append_fragment_callback_ledger,
    on_recommendation_fragment_probe_click,
    record_rec_queue_callback_entry,
)
from stage1_rec_fragment_exec_gate import (
    OBSERVABILITY_FRAGMENT_LEDGER_NOT_VISIBLE,
    callback_ledger_dom_observable,
    classify_fragment_gate,
)


class RecFragmentObservabilityTests(unittest.TestCase):
    def test_callback_ledger_dom_observable_requires_impl_rev(self) -> None:
        self.assertFalse(callback_ledger_dom_observable({}))
        self.assertTrue(
            callback_ledger_dom_observable({"impl_rev": "rec_fragment_exec_diag_v2", "ledger_len": "0"})
        )

    def test_f4_requires_both_trusted_clicks_and_no_callbacks(self) -> None:
        c = classify_fragment_gate(
            pause_ok=True,
            pause_dom={"trusted_dom_click": True},
            probe_step={
                "trusted_dom_click": True,
                "callback_entered": False,
                "ledger_dom_observable": True,
                "callback_ledger_last": {},
            },
            francisco_step={
                "trusted_dom_click": True,
                "callback_entered": False,
                "mutation_proven": False,
                "ledger_dom_observable": True,
                "callback_ledger_last": {},
            },
            probe_render_ok=True,
        )
        self.assertEqual(c, "QUEUE1C3A2F4")

    def test_missing_ledger_visibility_is_observability_not_f4(self) -> None:
        c = classify_fragment_gate(
            pause_ok=True,
            pause_dom={"trusted_dom_click": True},
            probe_step={"trusted_dom_click": True, "ledger_dom_observable": False},
            francisco_step={"trusted_dom_click": True, "ledger_dom_observable": True},
            probe_render_ok=True,
        )
        self.assertEqual(c, OBSERVABILITY_FRAGMENT_LEDGER_NOT_VISIBLE)

    def test_probe_callback_appends_one_ledger_event(self) -> None:
        session: dict[str, Any] = {}
        on_recommendation_fragment_probe_click(session, "R1", 0, "key")
        self.assertEqual(len(session[FRAGMENT_CALLBACK_LEDGER_KEY]), 1)

    def test_francisco_callback_entry_before_mutation(self) -> None:
        session: dict[str, Any] = {}
        record_rec_queue_callback_entry(
            session,
            event_id="e1",
            room_id="R1",
            pick_index=0,
            player_id="1",
            player_name="Francisco Lindor",
            widget_key="wk",
            queue_before=[],
        )
        self.assertEqual(session[FRAGMENT_CALLBACK_LEDGER_KEY][0]["source"], "rec_card_add_to_queue")

    def test_heavy_paint_done_reemits_callback_ledger_probe(self) -> None:
        st = MagicMock()
        session: dict[str, Any] = {HEAVY_PAINT_DONE_KEY: True}
        append_fragment_callback_ledger(session, {"event_id": "x", "callback_entered": True, "source": "fragment_widget_probe"})

        def body() -> None:
            raise AssertionError("paint body must not run when heavy paint done")

        with patch("live_draft_fast_solo_start.should_defer_heavy_first_paint", return_value=True):
            with patch("live_draft_fast_solo_start.note_start_stage"):
                with patch("live_draft_rec_fragment_exec_diag.reemit_fragment_callback_ledger_probe") as reemit:
                    render_deferred_heavy_paint_fragment(st, session, body)
                    reemit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
