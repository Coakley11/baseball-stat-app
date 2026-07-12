"""Tests for authoritative Live Draft recommendation context (team on clock)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from live_draft_recommendation_context import (
    RECOMMENDATION_CONTEXT_KEY,
    build_live_draft_recommendation_context,
    resolve_team_on_clock,
)
from live_draft_recommendations import live_draft_recommendations
from live_draft_state import live_draft_get_available, reconcile_drafted_player_ids


def _two_team_pool() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF", "Expected Fantasy Value": 95.0},
            {"playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF", "Expected Fantasy Value": 92.0},
            {"playerID": "p3", "fullName": "Gunnar Henderson", "Primary Position": "SS", "Expected Fantasy Value": 88.0},
            {"playerID": "p4", "fullName": "Mookie Betts", "Primary Position": "OF", "Expected Fantasy Value": 90.0},
            {"playerID": "p5", "fullName": "Freddie Freeman", "Primary Position": "1B", "Expected Fantasy Value": 86.0},
            {"playerID": "p6", "fullName": "José Ramírez", "Primary Position": "3B", "Expected Fantasy Value": 89.0},
        ]
    )


def _snake_pick_order() -> list[dict]:
    return [
        {"Pick": 1, "Round": 1, "Team": "Daniel"},
        {"Pick": 2, "Round": 1, "Team": "Team 2"},
        {"Pick": 3, "Round": 2, "Team": "Team 2"},
        {"Pick": 4, "Round": 2, "Team": "Daniel"},
        {"Pick": 5, "Round": 3, "Team": "Daniel"},
        {"Pick": 6, "Round": 3, "Team": "Team 2"},
        {"Pick": 7, "Round": 4, "Team": "Team 2"},
        {"Pick": 8, "Round": 4, "Team": "Daniel"},
    ]


def _base_room(*, pick_index: int = 0, board: list | None = None, rosters: dict | None = None) -> dict:
    teams = ["Daniel", "Team 2"]
    return {
        "draft_room_id": "live-test-abc",
        "status": "in_progress",
        "current_pick_index": pick_index,
        "config": {
            "num_teams": 2,
            "picks_per_team": 4,
            "teams": teams,
            "fantasy_format": "5x5 Roto",
            "scoring_type": "Roto (5x5)",
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
        "teams": teams,
        "pick_order": _snake_pick_order(),
        "draft_board": list(board or []),
        "rosters": rosters or {t: [] for t in teams},
        "drafted_player_ids": [str(r.get("playerID") or "") for r in (board or []) if r.get("playerID")],
        "pool": _two_team_pool(),
    }


class LiveDraftOnClockContextTests(unittest.TestCase):
    def test_pick_sequence_resolves_alternating_teams(self) -> None:
        expectations = [
            (0, "Daniel", 1),
            (1, "Team 2", 2),
            (2, "Team 2", 3),
            (3, "Daniel", 4),
        ]
        for idx, team, pick_no in expectations:
            room = _base_room(pick_index=idx)
            slot, on_clock = resolve_team_on_clock(room)
            self.assertIsNotNone(slot)
            assert slot is not None
            self.assertEqual(on_clock, team)
            self.assertEqual(int(slot["Pick"]), pick_no)

    def test_context_uses_on_clock_roster_not_user_team(self) -> None:
        room = _base_room(
            pick_index=1,
            rosters={
                "Daniel": [{"playerID": "x1", "fullName": "Daniel Player", "Primary Position": "SP"}],
                "Team 2": [{"playerID": "x2", "fullName": "Team 2 Player", "Primary Position": "OF"}],
            },
        )
        session: dict = {"room_your_team": "Daniel", "my_team_name": "Daniel"}
        ctx = build_live_draft_recommendation_context(room, session)
        self.assertEqual(ctx["team_on_clock"], "Team 2")
        self.assertEqual(ctx["resolved_recommendation_team"], "Team 2")
        self.assertEqual(ctx["team_roster_players"], ["Team 2 Player"])

    def test_drafted_players_excluded_from_available_pool(self) -> None:
        board = [
            {"Pick": 1, "Round": 1, "Team": "Daniel", "playerID": "p1", "fullName": "Juan Soto"},
        ]
        room = _base_room(pick_index=1, board=board)
        room["drafted_player_ids"] = []
        reconcile_drafted_player_ids(room)
        available = live_draft_get_available(room)
        names = set(available["fullName"].astype(str).tolist())
        self.assertNotIn("Juan Soto", names)
        self.assertIn("Aaron Judge", names)

    def test_team_override_is_ignored_by_recommendation_engine(self) -> None:
        room = _base_room(
            pick_index=1,
            rosters={
                "Daniel": [{"playerID": "x1", "fullName": "Daniel Player", "Primary Position": "SP"}],
                "Team 2": [{"playerID": "x2", "fullName": "Team 2 Player", "Primary Position": "OF"}],
            },
        )
        captured: list[list[str]] = []

        def _fake_score(available, roster_df, rule, target_counts, config=None, room=None):
            if not roster_df.empty and "fullName" in roster_df.columns:
                captured.append(roster_df["fullName"].astype(str).tolist())
            else:
                captured.append([])
            out = available.copy()
            for col in ("Decision Score", "Positional Fit", "Draft Fit Score", "Sleeper Score"):
                out[col] = 1.0
            return out, ["OF"]

        with patch("live_draft_recommendations._score_available", side_effect=_fake_score):
            live_draft_recommendations(room, top_n=2, team="Daniel")
        self.assertEqual(captured[0], ["Team 2 Player"])

    def test_research_mode_does_not_change_on_clock_team(self) -> None:
        room = _base_room(pick_index=0)
        session_off: dict = {"use_active_league_context_waiver_filter": False}
        session_on: dict = {"use_active_league_context_waiver_filter": True}
        ctx_off = build_live_draft_recommendation_context(room, session_off)
        ctx_on = build_live_draft_recommendation_context(room, session_on)
        self.assertEqual(ctx_off["team_on_clock"], "Daniel")
        self.assertEqual(ctx_on["team_on_clock"], "Daniel")
        self.assertFalse(ctx_off["research_mode"])
        self.assertTrue(ctx_on["research_mode"])

    def test_needs_change_after_team_drafts(self) -> None:
        room_before = _base_room(
            pick_index=2,
            board=[
                {"Pick": 1, "Round": 1, "Team": "Daniel", "playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF"},
                {"Pick": 2, "Round": 1, "Team": "Team 2", "playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF"},
            ],
            rosters={
                "Daniel": [{"playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF"}],
                "Team 2": [{"playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF"}],
            },
        )
        ctx_before = build_live_draft_recommendation_context(room_before, {})
        room_after = _base_room(
            pick_index=2,
            board=[
                {"Pick": 1, "Round": 1, "Team": "Daniel", "playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF"},
                {"Pick": 2, "Round": 1, "Team": "Team 2", "playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF"},
            ],
            rosters={
                "Daniel": [{"playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF"}],
                "Team 2": [
                    {"playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF"},
                    {"playerID": "p3", "fullName": "Gunnar Henderson", "Primary Position": "SS"},
                ],
            },
        )
        ctx_after = build_live_draft_recommendation_context(room_after, {})
        self.assertEqual(ctx_before["team_on_clock"], "Team 2")
        self.assertEqual(ctx_after["team_on_clock"], "Team 2")
        self.assertEqual(ctx_before["team_roster_players"], ["Aaron Judge"])
        self.assertEqual(
            ctx_after["team_roster_players"],
            ["Aaron Judge", "Gunnar Henderson"],
        )
        self.assertNotEqual(ctx_before["open_roster_slots"], ctx_after["open_roster_slots"])

    def test_scarcity_guardrail_preserves_large_value_gap(self) -> None:
        from live_draft_pick_scoring import _apply_scarcity_value_guardrails, normalize_series

        scored = pd.DataFrame(
            [
                {
                    "fullName": "Star",
                    "Expected Fantasy Value": 92.0,
                    "Decision Value Component": 0.55,
                    "Decision Rank Component": 0.10,
                    "Decision Roster Component": 0.05,
                    "Decision Scarcity Component": 0.02,
                    "Decision Trend Component": 0.0,
                    "Decision Sleeper Component": 0.0,
                    "Decision Market Component": 0.0,
                    "Decision Score": 0.72,
                },
                {
                    "fullName": "Scarce",
                    "Expected Fantasy Value": 76.0,
                    "Decision Value Component": 0.40,
                    "Decision Rank Component": 0.08,
                    "Decision Roster Component": 0.20,
                    "Decision Scarcity Component": 0.25,
                    "Decision Trend Component": 0.0,
                    "Decision Sleeper Component": 0.0,
                    "Decision Market Component": 0.0,
                    "Decision Score": 0.93,
                },
            ]
        )
        guarded = _apply_scarcity_value_guardrails(scored)
        star_score = float(guarded.loc[0, "Decision Score"])
        scarce_score = float(guarded.loc[1, "Decision Score"])
        self.assertGreater(star_score, scarce_score)

    def test_diagnostics_recorded_in_session(self) -> None:
        room = _base_room(pick_index=0)
        session: dict = {}
        build_live_draft_recommendation_context(room, session)
        diag = session.get(RECOMMENDATION_CONTEXT_KEY) or {}
        self.assertEqual(diag.get("team_on_clock"), "Daniel")
        self.assertEqual(diag.get("resolved_recommendation_team"), "Daniel")
        self.assertIn("candidate_pool_count", diag)

    def test_alternating_pick_sequence_uses_correct_roster_and_exclusions(self) -> None:
        expectations = [
            (0, "Daniel", [], {"Juan Soto", "Aaron Judge", "Gunnar Henderson", "Mookie Betts"}),
            (
                1,
                "Team 2",
                [{"playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF"}],
                {"Aaron Judge", "Gunnar Henderson", "Mookie Betts"},
            ),
            (
                2,
                "Team 2",
                [{"playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF"}],
                {"Gunnar Henderson", "Mookie Betts"},
            ),
            (
                3,
                "Daniel",
                [{"playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF"}],
                {"Mookie Betts"},
            ),
        ]
        for pick_index, team, daniel_roster, available_names in expectations:
            board = []
            if pick_index >= 1:
                board.append(
                    {"Pick": 1, "Round": 1, "Team": "Daniel", "playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF"}
                )
            if pick_index >= 2:
                board.append(
                    {"Pick": 2, "Round": 1, "Team": "Team 2", "playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF"}
                )
            if pick_index >= 3:
                board.append(
                    {"Pick": 3, "Round": 2, "Team": "Team 2", "playerID": "p3", "fullName": "Gunnar Henderson", "Primary Position": "SS"}
                )
            rosters = {
                "Daniel": daniel_roster,
                "Team 2": [
                    row
                    for row in (
                        [
                            {"playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF"},
                            {"playerID": "p3", "fullName": "Gunnar Henderson", "Primary Position": "SS"},
                        ]
                        if pick_index >= 3
                        else (
                            [{"playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF"}]
                            if pick_index >= 2
                            else []
                        )
                    )
                ],
            }
            if pick_index >= 1 and not daniel_roster:
                daniel_roster = [{"playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF"}]
                rosters["Daniel"] = daniel_roster
            room = _base_room(pick_index=pick_index, board=board, rosters=rosters)
            ctx = build_live_draft_recommendation_context(room, {})
            self.assertEqual(ctx["team_on_clock"], team)
            self.assertEqual(ctx["resolved_recommendation_team"], team)
            if team == "Daniel":
                self.assertEqual(ctx["team_roster_players"], [r["fullName"] for r in daniel_roster])
            else:
                self.assertEqual(
                    ctx["team_roster_players"],
                    [r["fullName"] for r in rosters["Team 2"]],
                )
            from live_draft_state import live_draft_get_available

            available = live_draft_get_available(room)
            names = set(available["fullName"].astype(str).tolist())
            drafted = {str(r.get("fullName") or "") for r in board}
            for name in drafted:
                if name:
                    self.assertNotIn(name, names)
            for expected in available_names:
                self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()
