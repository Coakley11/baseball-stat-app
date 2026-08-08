"""Callback execution when recommendation widgets render via live interactive path."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd

from live_draft_rec_fragment_exec_diag import (
    FRAGMENT_CALLBACK_LEDGER_KEY,
    FRAGMENT_PROBE_COUNTER_KEY,
    on_recommendation_fragment_probe_click,
)
from live_draft_rec_live_paint import store_prepared_rec_interactive


class RecLiveInteractiveCallbackTests(unittest.TestCase):
    def _francisco_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "fullName": "Francisco Lindor",
                    "Primary Position": "SS",
                    "playerID": "592789",
                    "Fantasy Edge": 1.0,
                    "Survival Probability": 0.5,
                },
            ]
        )

    def test_fragment_probe_callback_one_event(self) -> None:
        session: dict[str, Any] = {}
        on_recommendation_fragment_probe_click(session, "ROOM1", 0, "rec_fragment_widget_probe_ROOM1_0_diag")
        self.assertEqual(session[FRAGMENT_PROBE_COUNTER_KEY], 1)
        self.assertEqual(len(session[FRAGMENT_CALLBACK_LEDGER_KEY]), 1)

    def test_live_render_path_invokes_room_ui_cards(self) -> None:
        st = MagicMock()
        session: dict[str, Any] = {
            "_live_draft_rec_cache": {"top_rec": self._francisco_df()},
            "live_draft_room": {"draft_room_id": "ROOM1", "current_pick_index": 0, "status": "paused"},
            "draft_queue": [],
        }
        store_prepared_rec_interactive(session, room_id="ROOM1", gaps=[], category_needs=[], max_cards=1)
        room = session["live_draft_room"]
        with patch(
            "live_draft_solo_component_diagnostics.solo_component_diag_enabled",
            return_value=True,
        ):
            with patch("live_draft_room_ui.render_live_draft_rec_summary_banner"):
                with patch("live_draft_room_ui.render_live_draft_rec_cards") as cards:
                    from live_draft_rec_live_paint import render_rec_interactive_widgets

                    self.assertTrue(render_rec_interactive_widgets(st, session, room))
                    cards.assert_called_once()


if __name__ == "__main__":
    unittest.main()
