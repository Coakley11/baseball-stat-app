"""Rec-card Add-to-Queue help= A/B diagnostic (solo_component_diag only)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from live_draft_rec_queue_click_trace import (
    PER_CARD_RENDER_TRACE_CLASS,
    REC_QUEUE_CALLBACK_ID,
    REC_QUEUE_RENDER_TRACE_IMPL_REV,
    register_rec_queue_render_trace,
    render_per_card_rec_queue_render_trace_marker,
)
from live_draft_rec_queue_help_ab import (
    SESSION_VARIANT_KEY,
    latch_rec_queue_help_variant_from_query,
    rec_queue_add_button_help_kwargs,
    resolve_rec_queue_help_variant,
)
from live_draft_room_ui import render_live_draft_rec_cards


def _francisco_rec_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "playerID": "231",
                "fullName": "Francisco Lindor",
                "Primary Position": "SS",
                "teamAbbrev": "NYM",
                "Fantasy Edge": 10.0,
                "Survival Probability": 0.5,
            },
        ]
    )


def _room() -> dict[str, Any]:
    pool = _francisco_rec_df()
    return {
        "draft_room_id": "C9A3CB70",
        "status": "paused",
        "current_pick_index": 0,
        "config": {"num_teams": 2, "your_team": "Team 1", "timer_seconds": 120},
        "teams": ["Team 1", "Team 2"],
        "pick_order": [{"Pick": 1, "Round": 1, "Team": "Team 1"}],
        "draft_board": [],
        "rosters": {"Team 1": [], "Team 2": []},
        "drafted_player_ids": [],
        "pool": pool,
    }


class RecQueueHelpAbResolverTests(unittest.TestCase):
    def test_production_path_always_uses_help(self) -> None:
        session: dict[str, Any] = {}
        variant, present = resolve_rec_queue_help_variant(None, session)
        self.assertEqual(variant, "production_default")
        self.assertTrue(present)
        kwargs = rec_queue_add_button_help_kwargs(None, session, player_name="Francisco Lindor")
        self.assertEqual(kwargs["help"], "Add Francisco Lindor to your draft queue.")

    def test_diag_with_help_control(self) -> None:
        session: dict[str, Any] = {"_solo_component_diag_enabled": True, SESSION_VARIANT_KEY: "with_help"}
        variant, present = resolve_rec_queue_help_variant(mock.MagicMock(), session)
        self.assertEqual(variant, "with_help")
        self.assertTrue(present)
        self.assertIn("help", rec_queue_add_button_help_kwargs(mock.MagicMock(), session, player_name="Francisco Lindor"))

    def test_diag_no_help_omits_help_kwarg(self) -> None:
        session: dict[str, Any] = {"_solo_component_diag_enabled": True, SESSION_VARIANT_KEY: "no_help"}
        variant, present = resolve_rec_queue_help_variant(mock.MagicMock(), session)
        self.assertEqual(variant, "no_help")
        self.assertFalse(present)
        self.assertEqual(rec_queue_add_button_help_kwargs(mock.MagicMock(), session, player_name="Francisco Lindor"), {})

    def test_latch_query_param_no_help(self) -> None:
        st = mock.MagicMock()
        session: dict[str, Any] = {"_solo_component_diag_enabled": True}
        with mock.patch("live_draft_rec_queue_help_ab._qp_get", return_value="no_help"):
            latch_rec_queue_help_variant_from_query(st, session)
        self.assertEqual(session[SESSION_VARIANT_KEY], "no_help")

    def test_latch_defaults_to_with_help_when_diag_on(self) -> None:
        st = mock.MagicMock()
        session: dict[str, Any] = {"_solo_component_diag_enabled": True}
        with mock.patch("live_draft_rec_queue_help_ab._qp_get", return_value=""):
            latch_rec_queue_help_variant_from_query(st, session)
        self.assertEqual(session[SESSION_VARIANT_KEY], "with_help")


class RecQueueHelpAbRenderTraceTests(unittest.TestCase):
    def test_render_trace_carries_help_fields_in_dom(self) -> None:
        st = mock.MagicMock()
        session: dict[str, Any] = {"_solo_stage1_script_run_seq": 3}
        row = register_rec_queue_render_trace(
            session,
            room_id="C9A3CB70",
            pick_index=0,
            player_id="231",
            player_name="Francisco Lindor",
            widget_key="rec_card_queue_C9A3CB70_0_231_rec_card",
            help_variant="no_help",
            help_present=False,
        )
        self.assertEqual(row["help_variant"], "no_help")
        self.assertFalse(row["help_present"])
        with mock.patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            render_per_card_rec_queue_render_trace_marker(st, session, row)
        html = str(st.markdown.call_args[0][0])
        self.assertIn('data-help-variant="no_help"', html)
        self.assertIn('data-help-present="0"', html)
        self.assertIn(REC_QUEUE_RENDER_TRACE_IMPL_REV, html)


class RecQueueHelpAbCardRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.st = mock.MagicMock()
        self.st.container.return_value.__enter__ = mock.Mock(return_value=mock.MagicMock())
        self.st.container.return_value.__exit__ = mock.Mock(return_value=False)
        btn_col = mock.MagicMock()
        queue_col = mock.MagicMock()
        detail_col = mock.MagicMock()
        self.st.columns.return_value = [btn_col, queue_col, detail_col]

    def _queue_button_call(self, st: mock.MagicMock) -> tuple[tuple[Any, ...], dict[str, Any]]:
        for call in st.button.call_args_list:
            if call.args and "Add to Queue" in str(call.args[0]):
                return call.args, call.kwargs
        self.fail("Add to Queue button not rendered")

    @mock.patch("draft_actions.resolve_player_draft_gate", return_value={"allowed": True, "disable_message": ""})
    @mock.patch("draft_actions.resolve_manual_draft_panel_gate")
    @mock.patch("draft_actions.draft_action_context")
    @mock.patch("draft_actions._live_player_available", return_value=(True, ""))
    def test_with_help_renders_help_kwarg(
        self, _avail: object, _ctx: object, gate_fn: mock.MagicMock, _pg: object
    ) -> None:
        gate_fn.return_value = {"draft_enabled": True, "draft_complete": False}
        st = self.st
        session: dict[str, Any] = {"_solo_component_diag_enabled": True, SESSION_VARIANT_KEY: "with_help"}
        render_live_draft_rec_cards(st, session, _room(), _francisco_rec_df(), max_cards=1)
        _args, kwargs = self._queue_button_call(st)
        self.assertEqual(_args[0], "⭐ Add to Queue")
        # Return-value dispatch (Pause contract) — no nested on_click closure.
        self.assertIsNone(kwargs.get("on_click"))
        self.assertEqual(kwargs.get("help"), "Add Francisco Lindor to your draft queue.")
        self.assertEqual(kwargs.get("key"), "rec_card_queue_C9A3CB70_0_231_rec_card")

    @mock.patch("draft_actions.resolve_player_draft_gate", return_value={"allowed": True, "disable_message": ""})
    @mock.patch("draft_actions.resolve_manual_draft_panel_gate")
    @mock.patch("draft_actions.draft_action_context")
    @mock.patch("draft_actions._live_player_available", return_value=(True, ""))
    def test_no_help_omits_help_same_key_and_callback(
        self, _avail: object, _ctx: object, gate_fn: mock.MagicMock, _pg: object
    ) -> None:
        gate_fn.return_value = {"draft_enabled": True, "draft_complete": False}
        st = self.st
        session: dict[str, Any] = {"_solo_component_diag_enabled": True, SESSION_VARIANT_KEY: "no_help"}
        render_live_draft_rec_cards(st, session, _room(), _francisco_rec_df(), max_cards=1)
        _args, kwargs = self._queue_button_call(st)
        self.assertEqual(_args[0], "⭐ Add to Queue")
        self.assertIsNone(kwargs.get("on_click"))
        self.assertNotIn("help", kwargs)
        self.assertEqual(kwargs.get("key"), "rec_card_queue_C9A3CB70_0_231_rec_card")

    @mock.patch("draft_actions.resolve_player_draft_gate", return_value={"allowed": True, "disable_message": ""})
    @mock.patch("draft_actions.resolve_manual_draft_panel_gate")
    @mock.patch("draft_actions.draft_action_context")
    @mock.patch("draft_actions._live_player_available", return_value=(True, ""))
    def test_non_diag_path_unchanged_with_help(
        self, _avail: object, _ctx: object, gate_fn: mock.MagicMock, _pg: object
    ) -> None:
        gate_fn.return_value = {"draft_enabled": True, "draft_complete": False}
        st = self.st
        session: dict[str, Any] = {}
        render_live_draft_rec_cards(st, session, _room(), _francisco_rec_df(), max_cards=1)
        _args, kwargs = self._queue_button_call(st)
        self.assertEqual(kwargs.get("help"), "Add Francisco Lindor to your draft queue.")


if __name__ == "__main__":
    unittest.main()
