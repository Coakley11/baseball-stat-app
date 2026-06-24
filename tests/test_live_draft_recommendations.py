"""Tests for team-scoped live draft recommendations (PR 3)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd


def _import_live_draft_recommendations():
    try:
        from streamlit_app import live_draft_recommendations, live_draft_current_slot
    except ImportError:
        from Streamlit_app import live_draft_recommendations, live_draft_current_slot  # type: ignore[no-redef]
    return live_draft_recommendations, live_draft_current_slot


def _sample_room() -> dict:
    pool = pd.DataFrame(
        [
            {
                "playerID": "of1",
                "fullName": "Outfield Star",
                "Primary Position": "OF",
                "Expected Fantasy Value": 90.0,
                "Model Rank": 5,
                "Market Rank": 5,
            },
            {
                "playerID": "sp1",
                "fullName": "Ace Starter",
                "Primary Position": "SP",
                "Expected Fantasy Value": 88.0,
                "Model Rank": 8,
                "Market Rank": 8,
            },
        ]
    )
    return {
        "status": "in_progress",
        "current_pick_index": 0,
        "config": {
            "num_teams": 2,
            "picks_per_team": 5,
            "scoring_type": "Roto (5x5)",
            "fantasy_format": "5x5 Roto",
            "slot_c": 1,
            "slot_1b": 1,
            "slot_2b": 1,
            "slot_3b": 1,
            "slot_ss": 1,
            "slot_of": 3,
            "slot_dh": 1,
            "slot_p": 5,
            "slot_bench": 3,
        },
        "teams": ["Team 1", "Team 2"],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team 1"},
            {"Pick": 2, "Round": 1, "Team": "Team 2"},
        ],
        "draft_board": [],
        "rosters": {
            "Team 1": [
                {"playerID": "p1", "fullName": "Existing SP", "Primary Position": "SP"},
            ],
            "Team 2": [
                {"playerID": "p2", "fullName": "Existing OF", "Primary Position": "OF"},
            ],
        },
        "drafted_player_ids": [],
        "pool": pool,
    }


class LiveDraftRecommendationsTeamScopeTests(unittest.TestCase):
    def test_default_uses_on_clock_team_roster(self) -> None:
        live_draft_recommendations, live_draft_current_slot = _import_live_draft_recommendations()
        room = _sample_room()
        slot = live_draft_current_slot(room)
        self.assertEqual(str(slot.get("Team")), "Team 1")
        captured: list[list[str]] = []

        def _scored_df(available: pd.DataFrame, gaps: list[str]) -> pd.DataFrame:
            out = available.copy()
            for col in (
                "Decision Score",
                "Positional Fit",
                "Draft Fit Score",
                "Sleeper Score",
                "Expected Fantasy Value",
            ):
                if col not in out.columns:
                    out[col] = 0.5
            return out

        def _fake_score(available, roster_df, rule, target_counts, config=None):
            if not roster_df.empty and "Primary Position" in roster_df.columns:
                captured.append(roster_df["Primary Position"].astype(str).tolist())
            else:
                captured.append([])
            return _scored_df(available, ["OF"]), ["OF"]

        module = live_draft_recommendations.__module__
        with patch(f"{module}._live_draft_score_available", side_effect=_fake_score):
            live_draft_recommendations(room, top_n=2)
        self.assertEqual(captured[0], ["SP"])

    def test_team_override_uses_participant_roster(self) -> None:
        live_draft_recommendations, _ = _import_live_draft_recommendations()
        room = _sample_room()
        captured: list[list[str]] = []

        def _scored_df(available: pd.DataFrame) -> pd.DataFrame:
            out = available.copy()
            for col in (
                "Decision Score",
                "Positional Fit",
                "Draft Fit Score",
                "Sleeper Score",
                "Expected Fantasy Value",
            ):
                if col not in out.columns:
                    out[col] = 0.5
            return out

        def _fake_score(available, roster_df, rule, target_counts, config=None):
            captured.append(
                roster_df["Primary Position"].astype(str).tolist()
                if not roster_df.empty and "Primary Position" in roster_df.columns
                else []
            )
            gaps = ["SP"] if captured[-1] == ["OF"] else ["OF"]
            return _scored_df(available), gaps

        module = live_draft_recommendations.__module__
        with patch(f"{module}._live_draft_score_available", side_effect=_fake_score):
            live_draft_recommendations(room, top_n=2, team="Team 2")
        self.assertEqual(captured[0], ["OF"])

    def test_different_teams_produce_different_positional_gaps(self) -> None:
        live_draft_recommendations, _ = _import_live_draft_recommendations()
        room = _sample_room()
        module = live_draft_recommendations.__module__

        def _scored_df(available: pd.DataFrame) -> pd.DataFrame:
            out = available.copy()
            for col in (
                "Decision Score",
                "Positional Fit",
                "Draft Fit Score",
                "Sleeper Score",
                "Expected Fantasy Value",
            ):
                if col not in out.columns:
                    out[col] = 0.5
            return out

        def _gaps_for_team(team: str):
            captured: list[str] = []

            def _fake_score(available, roster_df, rule, target_counts, config=None):
                pos = (
                    roster_df["Primary Position"].astype(str).tolist()[0]
                    if not roster_df.empty and "Primary Position" in roster_df.columns
                    else ""
                )
                captured.append(pos)
                return _scored_df(available), (["OF"] if pos == "SP" else ["SP"])

            with patch(f"{module}._live_draft_score_available", side_effect=_fake_score):
                _top, _best, pos_fit, _sleep = live_draft_recommendations(room, top_n=2, team=team)
            return captured[0], pos_fit

        pos1, fit1 = _gaps_for_team("Team 1")
        pos2, fit2 = _gaps_for_team("Team 2")
        self.assertEqual(pos1, "SP")
        self.assertEqual(pos2, "OF")
        if not fit1.empty and not fit2.empty:
            self.assertNotEqual(
                fit1["Primary Position"].astype(str).tolist(),
                fit2["Primary Position"].astype(str).tolist(),
            )

    def test_compact_pool_runs_recommendations_without_keyerror(self) -> None:
        """Regression: compact shared-room pool missing Fantasy Edge must not crash scoring."""
        live_draft_recommendations, _ = _import_live_draft_recommendations()
        room = _sample_room()
        room["pool"] = pd.DataFrame(
            [
                {
                    "playerID": "p1",
                    "fullName": "Compact Star",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 92.0,
                },
                {
                    "playerID": "p2",
                    "fullName": "Compact Ace",
                    "Primary Position": "SP",
                    "Expected Fantasy Value": 88.0,
                },
            ]
        )
        top, best, positional, sleepers = live_draft_recommendations(room, top_n=2)
        self.assertFalse(top.empty)
        self.assertFalse(best.empty)
        self.assertIn("Decision Score", top.columns)
        self.assertIn("Fantasy Edge", top.columns)


if __name__ == "__main__":
    unittest.main()
