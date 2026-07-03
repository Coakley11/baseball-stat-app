"""Regression tests for Draft Assistant unified Why this pick column."""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from live_draft_room_ui import build_draft_assistant_why_this_pick

_REPO = Path(__file__).resolve().parents[1]


class DraftAssistantWhyColumnTests(unittest.TestCase):
    def test_why_includes_main_drivers(self) -> None:
        row = pd.Series(
            {
                "Primary Position": "2B",
                "Decision Score": 0.91,
                "Draft Fit Score": 8.5,
                "Positional Fit": 0.82,
                "Category Need Bonus": 0.05,
                "Fantasy Edge": 12,
                "Market Rank": 40,
                "Model Rank": 28,
                "proj_HR": 25,
                "proj_RBI": 85,
                "proj_SB": 8,
                "proj_BA": 0.275,
                "proj_OPS": 0.820,
            }
        )
        pool = pd.DataFrame([row.to_dict()] * 10)
        why = build_draft_assistant_why_this_pick(
            row,
            needed_positions=["2B"],
            category_needs=["HR"],
            pool_df=pool,
            draft_format="5x5 Roto",
        )
        self.assertIn("2B", why)
        self.assertTrue(
            any(token in why for token in ("Decision Score", "Roster Fit", "Fantasy Edge", "HR")),
            why,
        )
        self.assertNotIn("Proj:", why)
        self.assertNotIn("25 HR", why)

    def test_streamlit_recommendations_table_uses_single_why_column(self) -> None:
        text = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        marker = 'key="draft_assistant_recommendations"'
        idx = text.find(marker)
        self.assertNotEqual(idx, -1)
        chunk = text[max(0, idx - 2500) : idx + 200]
        self.assertIn('"Why this pick"', chunk)
        self.assertNotIn('"Team fit"', chunk)
        self.assertNotIn('"Strategy"', chunk)
        self.assertNotIn('"Reason"', chunk)
        self.assertIn("build_draft_assistant_why_this_pick", text)

    def test_live_draft_why_helper_still_present(self) -> None:
        ui_text = (_REPO / "live_draft_room_ui.py").read_text(encoding="utf-8")
        app_text = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("build_why_this_pick_summary", ui_text)
        self.assertIn("add_why_this_pick_column", ui_text)
        self.assertIn("add_why_this_pick_column", app_text)


if __name__ == "__main__":
    unittest.main()
