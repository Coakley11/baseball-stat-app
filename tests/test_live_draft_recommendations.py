"""Tests for team-scoped live draft recommendations (PR 3)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd


def _import_live_draft_recommendations():
    from live_draft_recommendations import live_draft_recommendations
    from live_draft_timer_logic import live_draft_current_slot

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
            "slots": {
                "C": 1,
                "1B": 1,
                "2B": 1,
                "3B": 1,
                "SS": 1,
                "OF": 3,
                "DH": 1,
                "P": 5,
                "BN": 3,
            },
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

        def _fake_score(available, roster_df, rule, target_counts, config=None, room=None):
            if not roster_df.empty and "Primary Position" in roster_df.columns:
                captured.append(roster_df["Primary Position"].astype(str).tolist())
            else:
                captured.append([])
            return _scored_df(available, ["OF"]), ["OF"]

        with patch("live_draft_recommendations._score_available", side_effect=_fake_score):
            live_draft_recommendations(room, top_n=2)
        self.assertEqual(captured[0], ["SP"])

    def test_team_override_uses_on_clock_not_participant_roster(self) -> None:
        live_draft_recommendations_fn, _ = _import_live_draft_recommendations()
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

        def _fake_score(available, roster_df, rule, target_counts, config=None, room=None):
            captured.append(
                roster_df["Primary Position"].astype(str).tolist()
                if not roster_df.empty and "Primary Position" in roster_df.columns
                else []
            )
            return _scored_df(available), ["OF"]

        with patch("live_draft_recommendations._score_available", side_effect=_fake_score):
            live_draft_recommendations_fn(room, top_n=2, team="Team 2")
        self.assertEqual(captured[0], ["SP"])

    def test_different_on_clock_teams_produce_different_positional_gaps(self) -> None:
        live_draft_recommendations_fn, _ = _import_live_draft_recommendations()
        room_team1 = _sample_room()
        room_team2 = _sample_room()
        room_team2["current_pick_index"] = 1

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

        def _gaps_for_room(room: dict) -> str:
            captured: list[str] = []

            def _fake_score(available, roster_df, rule, target_counts, config=None, room=None):
                pos = (
                    roster_df["Primary Position"].astype(str).tolist()[0]
                    if not roster_df.empty and "Primary Position" in roster_df.columns
                    else ""
                )
                captured.append(pos)
                return _scored_df(available), (["OF"] if pos == "SP" else ["SP"])

            with patch("live_draft_recommendations._score_available", side_effect=_fake_score):
                live_draft_recommendations_fn(room, top_n=2)
            return captured[0]

        pos1 = _gaps_for_room(room_team1)
        pos2 = _gaps_for_room(room_team2)
        self.assertEqual(pos1, "SP")
        self.assertEqual(pos2, "OF")

    def test_compact_pool_runs_recommendations_with_real_rank_values(self) -> None:
        """Compact round-trip pool must produce real Model/Market/Edge in recommendations."""
        live_draft_recommendations, _ = _import_live_draft_recommendations()
        from live_draft_state import room_from_persist_dict, room_to_persist_dict

        pool = pd.DataFrame(
            [
                {
                    "playerID": "pool_p1",
                    "fullName": "Compact Star",
                    "Primary Position": "OF",
                    "Expected Fantasy Value": 0.92,
                    "Model Rank": 5,
                    "Market Rank": 18,
                    "Fantasy Edge": 13,
                    "Sleeper Score": 0.55,
                    "Expert Std Dev": 3.0,
                    "Scarcity Score": 0.4,
                    "Trend Signal": 0.1,
                    "proj_HR": 35,
                    "proj_RBI": 90,
                    "proj_R": 80,
                    "proj_SB": 10,
                    "proj_BA": 0.280,
                    "proj_OPS": 0.900,
                },
                {
                    "playerID": "pool_p2",
                    "fullName": "Compact Ace",
                    "Primary Position": "SP",
                    "Expected Fantasy Value": 0.88,
                    "Model Rank": 12,
                    "Market Rank": 20,
                    "Fantasy Edge": 8,
                    "Sleeper Score": 0.48,
                    "Expert Std Dev": 4.0,
                    "Scarcity Score": 0.35,
                    "Trend Signal": 0.05,
                    "proj_HR": 0,
                    "proj_RBI": 0,
                    "proj_R": 0,
                    "proj_SB": 0,
                    "proj_BA": 0.0,
                    "proj_OPS": 0.0,
                },
            ]
        )
        room = _sample_room()
        blob = room_to_persist_dict({**room, "pool": pool}, compact_pool=True)
        restored = room_from_persist_dict(blob)
        assert isinstance(restored, dict)
        room["pool"] = restored["pool"]

        top, best, _positional, _sleepers = live_draft_recommendations(room, top_n=2)
        self.assertFalse(top.empty)
        row = top.iloc[0]
        self.assertLess(float(row["Model Rank"]), 9000)
        self.assertLess(float(row["Market Rank"]), 9000)
        self.assertNotEqual(float(row["Fantasy Edge"]), 0.0)
        self.assertIn("Decision Score", top.columns)


if __name__ == "__main__":
    unittest.main()
