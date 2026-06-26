"""Tests for draft AMI helper utilities."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_ami_helpers import (
    build_player_position_index_from_session,
    compact_fantasy_market_rows,
    compact_recommendation_rows,
    detect_positions_from_question,
    draft_ami_guidance,
    roster_for_team_from_board,
)
from draft_score_display import DISPLAY_PLAYER_GRADE, DISPLAY_PICK_SCORE, DISPLAY_ROSTER_FIT


class TestDraftAmiHelpers(unittest.TestCase):
    def test_compact_recommendation_rows(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "fullName": "Corbin Carroll",
                    "Primary Position": "OF",
                    "Model Rank": 10,
                    "Expected Fantasy Value": 0.91,
                    "Decision Score": 0.87,
                    "Draft Fit Score": 1.35,
                    "Reason": "Strong fit",
                }
            ]
        )
        rows = compact_recommendation_rows(df)
        self.assertEqual(rows[0]["player"], "Corbin Carroll")
        self.assertEqual(rows[0]["Primary Position"], "OF")
        self.assertEqual(rows[0]["reason"], "Strong fit")
        self.assertIn(DISPLAY_PLAYER_GRADE, rows[0])
        self.assertIn(DISPLAY_PICK_SCORE, rows[0])
        self.assertIn(DISPLAY_ROSTER_FIT, rows[0])
        self.assertNotIn("Expected Fantasy Value", rows[0])

    def test_compact_fantasy_market_rows(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "fullName": "Junior Caminero",
                    "Fantasy Edge": 40,
                    "Expected Fantasy Value": 0.82,
                    "Reason": "Undervalued",
                }
            ]
        )
        rows = compact_fantasy_market_rows(df)
        self.assertEqual(rows[0]["player"], "Junior Caminero")
        self.assertEqual(rows[0]["Fantasy Edge"], 40)
        self.assertIn(DISPLAY_PLAYER_GRADE, rows[0])

    def test_draft_ami_guidance_uses_display_score_names(self) -> None:
        for page in (
            "Fantasy Sleepers & Busts",
            "Live Draft Room",
            "Draft Assistant Simulator",
            "Trend Value",
            "Valuation",
            "Other",
        ):
            text = draft_ami_guidance(page)
            self.assertIn("Player Grade", text)
            self.assertIn("never EFV", text)
            self.assertIn("never Decision Score", text)
            self.assertIn("never Draft Fit Score", text)

    def test_draft_ami_guidance_per_page(self) -> None:
        self.assertIn("sleeper", draft_ami_guidance("Fantasy Sleepers & Busts").lower())
        self.assertIn("my_next_pick", draft_ami_guidance("Live Draft Room"))
        self.assertIn("canonical", draft_ami_guidance("Draft Assistant Simulator").lower())
        self.assertIn("valuation", draft_ami_guidance("Valuation").lower())

    def test_detect_positions_from_question_aliases(self) -> None:
        self.assertEqual(detect_positions_from_question("next catcher drafted"), ["C"])
        self.assertIn("SS", detect_positions_from_question("wait on shortstop"))
        self.assertIn("RP", detect_positions_from_question("relief pitcher run"))

    def test_build_player_position_index_from_session(self) -> None:
        session = {
            "_ami_draft_snapshot": {
                "draft_room_board": [
                    {"player": "Cal Raleigh", "Primary Position": "C"},
                ],
                "available_players": [
                    {"player": "William Contreras", "Primary Position": "C"},
                    {"player": "Shea Langeliers", "Primary Position": "C"},
                ],
            },
        }
        index = build_player_position_index_from_session(session)
        self.assertEqual(index.get("cal raleigh"), "C")
        self.assertEqual(index.get("william contreras"), "C")
        self.assertEqual(index.get("shea langeliers"), "C")

    def test_build_player_position_index_from_user_roster_detail(self) -> None:
        session = {
            "_ami_draft_snapshot": {
                "user_roster_detail": [
                    {"player": "Aaron Judge", "Primary Position": "OF"},
                    {"player": "Anthony Volpe", "Primary Position": "SS"},
                    {"player": "Cal Raleigh", "Primary Position": "C"},
                ],
            },
        }
        index = build_player_position_index_from_session(session)
        self.assertEqual(index.get("aaron judge"), "OF")
        self.assertEqual(index.get("anthony volpe"), "SS")
        self.assertEqual(index.get("cal raleigh"), "C")

    def test_roster_for_team_from_board_uses_primary_position_column(self) -> None:
        from unittest.mock import patch

        board = pd.DataFrame(
            {
                "Round": [1, 1, 1, 1],
                "Pick": [1, 2, 3, 4],
                "Team": ["Mike", "Mike", "Mike", "Mike"],
                "Player": ["Francisco Lindor", "Juan Soto", "Pete Alonso", "Julio Rodriguez"],
                "Primary Position": ["SS", "OF", "1B", "OF"],
            }
        )
        session: dict = {}
        with patch("draft_room_state.get_canonical_draft_board", return_value=board):
            names, detail, index = roster_for_team_from_board(session, "Mike")
        self.assertIn("Francisco Lindor", names)
        by_name = {row["player"]: row["Primary Position"] for row in detail}
        self.assertEqual(by_name["Francisco Lindor"], "SS")
        self.assertEqual(by_name["Pete Alonso"], "1B")
        self.assertEqual(index.get("juan soto"), "OF")

    def test_refresh_draft_ami_metadata_updates_round(self) -> None:
        from unittest.mock import patch

        from draft_ami_helpers import refresh_draft_ami_metadata_from_board

        board = pd.DataFrame(
            {
                "Round": [1, 1, 1, 1, 1, 1, 1],
                "Pick": [1, 2, 3, 4, 5, 6, 7],
                "Team": ["A", "B", "A", "B", "A", "B", "A"],
                "Player": ["P1", "P2", "P3", "P4", "P5", "P6", "P7"],
            }
        )
        session = {
            "room_team_count": 2,
            "room_your_team": "A",
            "draft_assistant_synced_team": "A",
            "_ami_draft_snapshot": {
                "current_pick": 1,
                "draft_round": 1,
                "available_players": [{"player": "x"}] * 25,
            },
            "_ami_draft_projection": {"available_players": [{"player": "x"}] * 25},
            "session_has_draft_board": True,
        }
        with patch("draft_room_state.get_canonical_draft_board", return_value=board):
            meta = refresh_draft_ami_metadata_from_board(session, source_page="Draft Room Simulator")
        self.assertTrue(meta.get("refreshed"))
        self.assertEqual(meta.get("current_pick"), 8)
        self.assertEqual(meta.get("draft_round"), 4)
        self.assertEqual(session["_ami_draft_snapshot"]["draft_round"], 4)

    def test_roster_position_detail_uses_global_lookup(self) -> None:
        from draft_ami_helpers import _roster_position_detail_for_names

        session = {
            "_ami_player_position_lookup": {
                "aaron judge": "OF",
                "anthony volpe": "SS",
                "cal raleigh": "C",
            },
        }
        detail, index = _roster_position_detail_for_names(
            session,
            ["Aaron Judge", "Anthony Volpe", "Cal Raleigh"],
        )
        self.assertEqual(index.get("aaron judge"), "OF")
        self.assertEqual(index.get("anthony volpe"), "SS")
        self.assertEqual(index.get("cal raleigh"), "C")
        self.assertEqual(detail[0]["Primary Position"], "OF")

    def test_resolve_board_team_name_by_draft_order_index(self) -> None:
        from draft_ami_helpers import resolve_board_team_name

        order = ["Daniel", "Mike", "Chris", "Alex"]
        self.assertEqual(resolve_board_team_name(order, "Team 2", draft_order=order), "Mike")
        self.assertEqual(resolve_board_team_name(order, "team 1", draft_order=order), "Daniel")

    def test_team_names_in_draft_order_from_round_one(self) -> None:
        from draft_ami_helpers import team_names_in_draft_order

        board = pd.DataFrame(
            {
                "Round": [1, 1, 1, 1, 2, 2],
                "Pick": [1, 2, 3, 4, 5, 6],
                "Team": ["Daniel", "Mike", "Chris", "Alex", "Alex", "Daniel"],
                "Player": ["P1", "P2", "P3", "P4", "P5", "P6"],
            }
        )
        self.assertEqual(team_names_in_draft_order(board), ["Daniel", "Mike", "Chris", "Alex"])


if __name__ == "__main__":
    unittest.main()
