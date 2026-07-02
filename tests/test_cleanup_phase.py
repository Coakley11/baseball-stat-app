"""Regression tests for cleanup phase: Sleepers unified pool, cards, live draft UX."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import pandas as pd

from canonical_projections import merge_canonical_draft_metrics
from draft_score_display import fmt_ml_projection_score, fmt_pick_score, fmt_player_grade
from live_draft_navigation import LIVE_DRAFT_QUICK_NAV_PAGES, render_live_draft_quick_nav
from player_photos import (
    build_draft_score_metrics_html,
    build_trend_card_takeaway,
    build_valuation_card_takeaway,
)

_REPO = Path(__file__).resolve().parents[1]


class SleepersUnifiedPoolTests(unittest.TestCase):
    def test_merge_canonical_draft_metrics_overwrites_model_rank(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "playerID": "j1",
                    "fullName": "Aaron Judge",
                    "Model Rank": 5,
                    "Market Rank": 12,
                    "Fantasy Edge": 7,
                    "Expected Fantasy Value": 0.92,
                }
            ]
        )
        page = pd.DataFrame(
            [
                {
                    "playerID": "j1",
                    "fullName": "Aaron Judge",
                    "Model Rank": 99,
                    "Market Rank": 99,
                    "Fantasy Edge": -50,
                    "Expected Fantasy Value": 0.4,
                }
            ]
        )
        merged = merge_canonical_draft_metrics(page, pool)
        self.assertEqual(int(merged.iloc[0]["Model Rank"]), 5)
        self.assertEqual(int(merged.iloc[0]["Market Rank"]), 12)
        self.assertEqual(int(merged.iloc[0]["Fantasy Edge"]), 7)

    def test_sleepers_page_uses_merge_canonical_draft_metrics(self) -> None:
        text = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("merge_canonical_draft_metrics(fantasy_df", text)
        self.assertNotIn('fantasy_df["Model Rank"] = fantasy_df["Projected Production Score"].rank', text)


class InsightCardDedupTests(unittest.TestCase):
    def test_trend_card_takeaway_excludes_projection_prose(self) -> None:
        row = {
            "OPS_trend": 0.05,
            "HR_trend": 4,
            "proj_HR": 40,
            "proj_OPS": 0.95,
        }
        takeaway = build_trend_card_takeaway(row)
        self.assertIn("Breakout", takeaway)
        self.assertNotIn("Next year projection", takeaway)

    def test_valuation_card_takeaway_excludes_projection_prose(self) -> None:
        row = {"Valuation_Score": 0.88, "Trend_Score": 12.0, "Perf_Score": 15.0, "proj_HR": 35}
        takeaway = build_valuation_card_takeaway(row)
        self.assertIn("Valuation takeaway", takeaway)
        self.assertNotIn("proj", takeaway.lower())

    def test_streamlit_trend_insight_no_duplicate_summary_block(self) -> None:
        text = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        marker = 'st.subheader("Insight Summary")'
        start = text.find(marker)
        self.assertNotEqual(start, -1)
        chunk = text[start : start + 2500]
        self.assertNotIn("st.success(make_trend_insight_summary", chunk)
        self.assertNotIn("st.error(make_trend_insight_summary", chunk)
        self.assertNotIn("extra_summary=make_trend_insight_summary", chunk)

    def test_streamlit_valuation_no_duplicate_info_summary(self) -> None:
        text = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        marker = "build_valuation_card_takeaway"
        self.assertIn(marker, text)
        val_pos = text.find(marker)
        chunk = text[val_pos : val_pos + 800]
        self.assertNotIn("st.info(make_valuation_summary", chunk)


class ScoreFormattingTests(unittest.TestCase):
    def test_pick_and_ml_scores_trim_trailing_zeros(self) -> None:
        self.assertEqual(fmt_pick_score(0.92), "92")
        self.assertEqual(fmt_pick_score(0.885), "88.5")
        self.assertEqual(fmt_ml_projection_score(0.94756234), "94.76")
        self.assertEqual(fmt_player_grade(0.92), "92")


class LiveDraftUxTests(unittest.TestCase):
    def test_quick_nav_pages_defined(self) -> None:
        pages = [p for p, _ in LIVE_DRAFT_QUICK_NAV_PAGES]
        self.assertIn("Draft Assistant Simulator", pages)
        self.assertIn("Fantasy Sleepers & Busts", pages)
        self.assertIn("Trend Value", pages)

    def test_quick_nav_renders_buttons(self) -> None:
        class _Col:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def __enter__(self) -> "_Col":
                return self

            def __exit__(self, *_a) -> None:
                return None

            def button(self, label: str, **kwargs) -> bool:
                self.calls.append({"label": label, **kwargs})
                return False

        class _St:
            def __init__(self) -> None:
                self.cols: list[_Col] = []

            def markdown(self, *_a, **_k) -> None:
                pass

            def columns(self, n: int) -> list[_Col]:
                self.cols = [_Col() for _ in range(n)]
                return self.cols

        st = _St()
        session: dict = {}
        render_live_draft_quick_nav(st, session)
        total_calls = sum(len(c.calls) for c in st.cols)
        self.assertEqual(total_calls, len(LIVE_DRAFT_QUICK_NAV_PAGES))

    def test_rec_card_metrics_include_core_fields(self) -> None:
        row = {
            "Expected Fantasy Value": 0.91,
            "Decision Score": 0.88,
            "Draft Fit Score": 1.42,
            "Model Rank": 8,
            "Market Rank": 15,
            "Fantasy Edge": 7,
            "proj_HR": 35,
            "proj_RBI": 90,
        }
        html = build_draft_score_metrics_html(
            row,
            show_decision_score=True,
            show_player_grade=True,
            show_roster_fit=True,
            show_market_rank=True,
            show_model_rank=True,
            show_fantasy_edge=True,
        )
        for token in ("Decision Score", "Player Grade", "Roster Fit Score", "Model Rank", "Market Rank", "Fantasy Edge"):
            self.assertIn(token, html)

    def test_live_draft_room_wires_panels(self) -> None:
        text = (_REPO / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("render_live_draft_quick_nav", text)
        self.assertIn("render_roster_tracker_panel", text)
        self.assertIn("render_category_outlook_panel", text)
        self.assertIn("render_position_scarcity_panel", text)

    def test_roster_tracker_updates_after_pick(self) -> None:
        from live_draft_roster_tracker import build_team_roster_tracker

        room = {
            "config": {"slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1}},
            "rosters": {
                "Team A": [
                    {"fullName": "P1", "Primary Position": "C"},
                    {"fullName": "P2", "Primary Position": "1B"},
                ]
            },
        }
        before = build_team_roster_tracker(room, "Team A")
        room["rosters"]["Team A"].append({"fullName": "P3", "Primary Position": "SS"})
        after = build_team_roster_tracker(room, "Team A")
        self.assertEqual(after["filled"], before["filled"] + 1)


if __name__ == "__main__":
    unittest.main()
