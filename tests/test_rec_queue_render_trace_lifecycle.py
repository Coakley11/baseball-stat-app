"""Render-trace observability: per-card markers and heavy-paint re-emit (QUEUE1C3A5)."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd

from live_draft_heavy_paint_ui import HEAVY_PAINT_DONE_KEY, render_deferred_heavy_paint_fragment
from live_draft_rec_queue_click_trace import (
    PER_CARD_RENDER_TRACE_CLASS,
    RENDER_TRACE_PROBE_ELEMENT_ID,
    REC_QUEUE_CALLBACK_ID,
    REC_QUEUE_RENDER_TRACE_IMPL_REV,
    register_rec_queue_render_trace,
    reemit_rec_queue_render_trace_diagnostics,
    render_per_card_rec_queue_render_trace_marker,
    render_rec_queue_render_trace_probe,
)


class RecQueueRenderTraceLifecycleTests(unittest.TestCase):
    def _francisco_trace(self, session: dict[str, Any]) -> dict[str, Any]:
        return register_rec_queue_render_trace(
            session,
            room_id="E667FBC4",
            pick_index=0,
            player_id="592789",
            player_name="Francisco Lindor",
            widget_key="rec_card_queue_E667FBC4_0_592789_rec_card",
            surface="rec_card",
            render_run_seq=1,
        )

    def test_francisco_card_render_registers_and_emits_per_card_marker(self) -> None:
        st = MagicMock()
        session: dict[str, Any] = {}
        row = self._francisco_trace(session)
        with patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            render_per_card_rec_queue_render_trace_marker(st, session, row)
        html = str(st.markdown.call_args[0][0])
        self.assertIn(PER_CARD_RENDER_TRACE_CLASS, html)
        self.assertIn("Francisco Lindor", html)
        self.assertIn("rec_card_queue_E667FBC4_0_592789_rec_card", html)
        self.assertIn(REC_QUEUE_CALLBACK_ID, html)
        self.assertIn(REC_QUEUE_RENDER_TRACE_IMPL_REV, html)

    def test_reemit_from_registry_without_repainting_cards(self) -> None:
        st = MagicMock()
        session: dict[str, Any] = {}
        self._francisco_trace(session)
        with patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            reemit_rec_queue_render_trace_diagnostics(st, session)
        self.assertGreaterEqual(st.markdown.call_count, 2)
        combined = " ".join(str(c[0][0]) for c in st.markdown.call_args_list)
        self.assertIn(RENDER_TRACE_PROBE_ELEMENT_ID, combined)
        self.assertIn(PER_CARD_RENDER_TRACE_CLASS, combined)
        self.assertIn("Francisco Lindor", combined)

    def test_heavy_paint_done_reemits_render_trace_only(self) -> None:
        st = MagicMock()
        session: dict[str, Any] = {HEAVY_PAINT_DONE_KEY: True}
        self._francisco_trace(session)
        painted = {"count": 0}

        def paint_body() -> None:
            painted["count"] += 1

        with patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            render_deferred_heavy_paint_fragment(st, session, paint_body)
        self.assertEqual(painted["count"], 0)
        self.assertGreater(st.markdown.call_count, 0)

    def test_render_live_draft_rec_cards_francisco_with_diag(self) -> None:
        from live_draft_room_ui import render_live_draft_rec_cards

        st = MagicMock()
        col_a, col_b, col_c = MagicMock(), MagicMock(), MagicMock()
        st.columns.return_value = [col_a, col_b, col_c]
        st.container.return_value.__enter__ = MagicMock(return_value=st)
        st.container.return_value.__exit__ = MagicMock(return_value=False)
        session: dict[str, Any] = {
            "draft_queue": [],
            "live_draft_room": {"draft_room_id": "E667FBC4", "current_pick_index": 0, "status": "paused"},
        }
        rec_df = pd.DataFrame(
            [
                {
                    "fullName": "Francisco Lindor",
                    "Primary Position": "SS",
                    "playerID": "592789",
                    "Fantasy Edge": 1.0,
                    "Survival Probability": 0.5,
                }
            ]
        )
        with patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ), patch(
            "draft_actions.resolve_manual_draft_panel_gate",
            return_value={"draft_enabled": True, "draft_complete": False},
        ), patch(
            "draft_actions.resolve_player_draft_gate",
            return_value={"allowed": True, "disable_message": ""},
        ):
            render_live_draft_rec_cards(
                st,
                session,
                session["live_draft_room"],
                rec_df,
                max_cards=1,
            )
        combined = " ".join(str(c[0][0]) for c in st.markdown.call_args_list)
        self.assertIn(PER_CARD_RENDER_TRACE_CLASS, combined)
        self.assertIn(RENDER_TRACE_PROBE_ELEMENT_ID, combined)
        self.assertIn("Francisco Lindor", combined)

    def test_diag_disabled_emits_no_probe(self) -> None:
        st = MagicMock()
        session: dict[str, Any] = {}
        row = self._francisco_trace(session)
        with patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=False,
        ):
            render_rec_queue_render_trace_probe(st, session)
            render_per_card_rec_queue_render_trace_marker(st, session, row)
        st.markdown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
