"""Smoke test: Live Draft Room -> Analyze Completed Draft -> Draft Lab analysis."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from draft_lab_analysis import (
    analyze_draft_lab_results,
    draft_lab_board_display_columns,
    enrich_lab_draft_metrics,
    format_snake_draft_caption,
)
from draft_lab_handoff import apply_live_draft_handoff_to_session


def _completed_live_room() -> dict:
    return {
        "draft_room_id": "TEST01",
        "status": "complete",
        "teams": ["Ariel", "Daniel"],
        "config": {
            "num_teams": 2,
            "picks_per_team": 4,
            "scoring_type": "Roto (5x5)",
            "fantasy_format": "5x5 Roto",
            "projection_style": "Aggressive",
            "projection_window": 3,
            "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "BN": 5},
        },
        "draft_board": [
            {"Round": 1, "Pick": 1, "Fantasy Team": "Ariel", "fullName": "Nathan Lukes", "Primary Position": "OF", "playerID": "luke01", "Fantasy Edge": 14, "Decision Score": 0.84, "Model Rank": 120, "Market Rank": 240, "Draft Fit Score": 0.72},
            {"Round": 1, "Pick": 2, "Fantasy Team": "Daniel", "fullName": "Julio Rodriguez", "Primary Position": "OF", "playerID": "jrod01", "Fantasy Edge": 10, "Decision Score": 0.79, "Model Rank": 15, "Market Rank": 18, "Draft Fit Score": 0.68},
            {"Round": 2, "Pick": 3, "Fantasy Team": "Daniel", "fullName": "Bobby Witt", "Primary Position": "SS", "playerID": "witt01", "Fantasy Edge": 6, "Decision Score": 0.71, "Model Rank": 8, "Market Rank": 12, "Draft Fit Score": 0.6},
            {"Round": 2, "Pick": 4, "Fantasy Team": "Ariel", "fullName": "Mike Trout", "Primary Position": "OF", "playerID": "trout01", "Fantasy Edge": 5, "Decision Score": 0.66, "Model Rank": 5, "Market Rank": 6, "Draft Fit Score": 0.55},
        ],
        "pool": pd.DataFrame(),
    }


class AnalyzeCompletedDraftSmokeTests(unittest.TestCase):
    def test_handoff_populates_analysis_artifacts(self) -> None:
        session: dict = {"active_shared_draft_room_code": "0LD6RH"}
        room = _completed_live_room()
        handoff = apply_live_draft_handoff_to_session(session, room)
        self.assertEqual(session["draft_lab_picks_per_team"], 4)
        self.assertEqual(handoff["team_count"], 2)

        draft_df = pd.DataFrame(room["draft_board"])
        ctx = {
            "config": room["config"],
            "teams": room["teams"],
            "pool": room["pool"],
            "handoff": handoff,
        }
        draft_df = enrich_lab_draft_metrics(draft_df, room["pool"], room["config"])
        team_summary, _strengths, pick_analysis, gaps, _actual = analyze_draft_lab_results(
            draft_df,
            pd.DataFrame(),
            context=ctx,
        )

        caption = format_snake_draft_caption(room["teams"])
        self.assertIn("Ariel → Daniel", caption)
        self.assertNotIn("Team A", caption)

        cols = draft_lab_board_display_columns()
        self.assertIn("Fantasy Edge", cols)
        self.assertNotIn("Sleeper Score", cols)
        self.assertNotIn("Best Value Sleeper Score", cols)

        for team in room["teams"]:
            best = pick_analysis[(pick_analysis["Fantasy Team"] == team) & (pick_analysis["Pick Type"] == "Best Pick")]
            self.assertEqual(len(best), 1, msg=f"{team} should have exactly one Best Pick")

        gap_positions = set(gaps["Position"].astype(str))
        for pos in ("C", "1B", "2B", "3B", "SS", "OF", "UTIL", "Bench"):
            self.assertIn(pos, gap_positions)
        self.assertFalse(team_summary.empty)


class AnalyzeHandoffActivityTests(unittest.TestCase):
    def test_minimal_live_draft_handoff_without_proj_ab(self) -> None:
        room = _completed_live_room()
        draft_df = pd.DataFrame(room["draft_board"])
        draft_df["proj_BA"] = [0.270, 0.290, 0.285, 0.280]
        draft_df["proj_OPS"] = [0.800, 0.900, 0.880, 0.850]
        ctx = {
            "config": room["config"],
            "teams": room["teams"],
            "pool": room["pool"],
            "handoff": {"team_names": room["teams"], "picks_per_team": 4},
        }
        team_summary, strengths, pick_analysis, gaps, _actual = analyze_draft_lab_results(
            draft_df,
            pd.DataFrame(),
            context=ctx,
        )
        self.assertFalse(team_summary.empty)
        self.assertFalse(pick_analysis.empty)

    @patch("suite_activity_client.record_activity")
    def test_draft_analysis_created_after_successful_handoff(self, record_mock) -> None:
        from baseball_draft_activity import log_draft_analysis_created

        room = _completed_live_room()
        session: dict = {}
        log_draft_analysis_created(room, session=session)
        events = [call[0][1] for call in record_mock.call_args_list]
        self.assertIn("draft_analysis_created", events)

    @patch("suite_activity_client.record_activity")
    def test_missing_proj_columns_still_emits_draft_activity(self, record_mock) -> None:
        from baseball_draft_activity import log_draft_analysis_created

        room = _completed_live_room()
        draft_df = pd.DataFrame(room["draft_board"])
        ctx = {
            "config": room["config"],
            "teams": room["teams"],
            "pool": room["pool"],
        }
        analyze_draft_lab_results(draft_df, pd.DataFrame(), context=ctx)
        session: dict = {}
        log_draft_analysis_created(room, session=session)
        self.assertTrue(any(call[0][1] == "draft_analysis_created" for call in record_mock.call_args_list))
        kwargs = record_mock.call_args[1]
        self.assertEqual(kwargs["metrics"]["team_matchup"], "Ariel vs Daniel")


if __name__ == "__main__":
    unittest.main()
