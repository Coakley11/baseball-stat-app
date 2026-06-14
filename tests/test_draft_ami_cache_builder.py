"""Tests for pure draft AMI cache builder (no Streamlit_app import)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from draft_ami_cache_builder import (
    build_draft_assistant_ami_cache_from_board_state,
    extract_board_draft_context,
)
from draft_room_state import build_snake_board


def _board_with_picks(picks: int) -> pd.DataFrame:
    board = build_snake_board(["Team A", "Team B", "Team C", "Team D"], rounds=3)
    board = board.sort_values("Pick", kind="stable").reset_index(drop=True)
    for idx, row in board.iterrows():
        if int(row["Pick"]) <= picks:
            board.at[idx, "Player"] = f"Player {row['Pick']}"
    return board


class TestDraftAmiCacheBuilder(unittest.TestCase):
    def test_extract_board_context_current_pick_after_seven_picks(self) -> None:
        board = _board_with_picks(7)
        ctx = extract_board_draft_context(
            board,
            {"room_your_team": "Team A", "room_team_count": 4},
        )
        self.assertEqual(ctx["current_pick"], 8)

    @patch("draft_pool_engine.apply_draft_pick_scoring")
    @patch("draft_pool_engine.build_unified_draft_player_pool")
    @patch("draft_pool_engine.load_yearly_stat_data")
    @patch("draft_pool_engine.load_draft_market_data")
    def test_build_from_board_state_without_streamlit_app(
        self,
        mock_market,
        mock_yearly,
        mock_pool,
        mock_score,
    ) -> None:
        pool_df = pd.DataFrame(
            {
                "fullName": ["Kyle Tucker", "Mike Trout", "Player 1"],
                "Primary Position": ["OF", "OF", "SS"],
                "Expected Fantasy Value": [0.9, 0.88, 0.5],
                "Draft Fit Score": [0.91, 0.87, 0.4],
            }
        )
        mock_market.return_value = pd.DataFrame({"Player Key": ["x"], "Market Rank": [1]})
        mock_yearly.return_value = pd.DataFrame({"yearID": [2024], "playerID": ["a"]})
        mock_pool.return_value = pool_df
        scored = pool_df.copy()
        mock_score.return_value = (scored, [], [])

        board = _board_with_picks(7)
        settings = {
            "room_your_team": "Team A",
            "room_team_count": 4,
            "draft_format": "5x5 Roto",
        }
        built = build_draft_assistant_ami_cache_from_board_state(board, settings)
        self.assertTrue(built.get("ok"), built.get("reason"))
        self.assertEqual(built["cache_inputs"]["current_pick"], 8)
        self.assertIn("available_df", built["cache_inputs"])


class TestNoStreamlitAppImportOnDemandBuild(unittest.TestCase):
    @patch("draft_ami_cache_builder.build_draft_assistant_ami_cache_from_board_state")
    def test_on_demand_cache_does_not_import_streamlit_app(self, mock_build: MagicMock) -> None:
        import sys

        from draft_ami_helpers import build_draft_assistant_ami_cache_from_board

        mock_build.return_value = {
            "ok": True,
            "trace": {"current_pick": 8},
            "cache_inputs": {"current_pick": 8},
        }

        real_import = __import__

        def _guarded_import(name, *args, **kwargs):
            if name in ("streamlit_app", "Streamlit_app"):
                raise AssertionError(f"unexpected import of {name} during on-demand cache build")
            return real_import(name, *args, **kwargs)

        board = _board_with_picks(7)
        session = {
            "room_your_team": "Team A",
            "room_team_count": 4,
            "draft_room_table": board.copy(),
            "draft_room_board_editor_cache": board.copy(),
        }
        with patch("draft_ami_cache_builder.apply_draft_assistant_cache_to_session") as mock_apply:
            mock_apply.return_value = {
                "available_players_count": 51,
                "player_pool_source": "position_representative_v1",
                "current_pick": 8,
            }
            with patch.dict(sys.modules, {}):
                with patch("builtins.__import__", side_effect=_guarded_import):
                    trace = build_draft_assistant_ami_cache_from_board(session, page="Draft Room Simulator")

        self.assertEqual(trace.get("cache_action"), "built_from_board")
        self.assertEqual(trace.get("skip_reason"), "none")


if __name__ == "__main__":
    unittest.main()
