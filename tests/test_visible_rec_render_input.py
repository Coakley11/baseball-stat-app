"""Visible recommendation-card render input diagnostic."""

from __future__ import annotations

import unittest
import unittest.mock

import pandas as pd

from live_draft_room_ui import (
    VISIBLE_REC_RENDER_INPUT_KEY,
    build_visible_rec_render_input,
    render_visible_rec_render_input_diagnostic,
)


class _St:
    def __init__(self) -> None:
        self.markdowns: list[str] = []
        self.captions: list[str] = []

    def markdown(self, text: str, **_kwargs) -> None:
        self.markdowns.append(str(text))

    def caption(self, text: str) -> None:
        self.captions.append(str(text))


class VisibleRecRenderInputTests(unittest.TestCase):
    def test_build_lists_final_card_names(self) -> None:
        rec = pd.DataFrame(
            {
                "fullName": ["Judge", "Soto", "Ohtani"],
                "Decision Score": [90.0, 88.0, 87.0],
            }
        )
        avail = pd.DataFrame({"fullName": [f"P{i}" for i in range(12)]})
        payload = build_visible_rec_render_input(
            rec_df=rec,
            available_df=avail,
            on_clock_team="Daniel",
            max_cards=2,
            defer_recs=False,
            expensive_ok=True,
            cache_key=("k", 1),
            rec_cache_entry={"key": ("k", 1), "top_rec": rec},
            room_status="in_progress",
        )
        self.assertEqual(payload["available_player_count"], 12)
        self.assertEqual(payload["recommendation_count"], 3)
        self.assertEqual(payload["card_render_input"], ["Judge", "Soto"])
        self.assertEqual(payload["on_clock_team"], "Daniel")
        self.assertEqual(payload["scoring_cache_state"], "hit(3)")

    def test_empty_paint_flags_caption(self) -> None:
        st = _St()
        session: dict = {"app_developer_mode": True, "_suite_developer_mode_user": True}
        payload = build_visible_rec_render_input(
            rec_df=pd.DataFrame(),
            available_df=pd.DataFrame({"fullName": ["A"]}),
            on_clock_team="",
            defer_recs=True,
            skip_for_setup=True,
            expensive_ok=False,
            room_status="in_progress",
        )
        with unittest.mock.patch(
            "suite_workspace.developer_mode_checkbox_enabled",
            return_value=True,
        ):
            render_visible_rec_render_input_diagnostic(st, session, payload)
        self.assertIn(VISIBLE_REC_RENDER_INPUT_KEY, session)
        self.assertTrue(any("VISIBLE REC RENDER INPUT" in m for m in st.markdowns))
        self.assertTrue(any("empty" in c.lower() for c in st.captions))
        self.assertEqual(payload["available_player_count"], 1)
        self.assertEqual(payload["recommendation_count"], 0)

    def test_hidden_when_developer_mode_off(self) -> None:
        st = _St()
        session: dict = {}
        payload = build_visible_rec_render_input(
            rec_df=pd.DataFrame({"fullName": ["Judge"]}),
            available_df=pd.DataFrame({"fullName": ["Judge"]}),
            on_clock_team="Daniel",
        )
        with unittest.mock.patch(
            "suite_workspace.developer_mode_checkbox_enabled",
            return_value=False,
        ):
            render_visible_rec_render_input_diagnostic(st, session, payload)
        self.assertIn(VISIBLE_REC_RENDER_INPUT_KEY, session)
        self.assertFalse(st.markdowns)


if __name__ == "__main__":
    unittest.main()
