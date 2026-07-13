"""Regression tests for Draft Assistant board resolution and progress."""

from __future__ import annotations

import unittest

import pandas as pd

from draft_assistant_board import normalize_draft_board_df, resolve_draft_assistant_board
from draft_room_state import derive_draft_progress, draft_board_summary_for_team
from fantasy_league_context import (
    FANTASY_LEAGUE_CONTEXT_STATE_KEY,
    context_id_for_archive,
    upsert_league_context,
)


def _robins_league_rosters() -> dict:
    rosters: dict = {}
    for pick in range(1, 21):
        team = "Donny" if pick % 2 == 1 else "Team B"
        player_name = f"Player {pick}"
        rosters.setdefault(team, {"team_name": team, "players": []})
        rosters[team]["players"].append(
            {
                "player_name": player_name,
                "source_row": {
                    "Pick": pick,
                    "Round": ((pick - 1) // 2) + 1,
                    "Team": team,
                    "Player": player_name,
                },
            }
        )
    return rosters


def _robins_context(*, my_team: str = "Donny") -> dict:
    draft_id = "c6810611c73e"
    return {
        "league_context_id": context_id_for_archive(draft_id),
        "context_type": "live_draft_result",
        "display_name": "Robins Fantasy",
        "my_team_name": my_team,
        "source": "live_draft_room",
        "metadata": {
            "source_draft_id": draft_id,
            "creation_origin": "live_draft_room",
            "source_draft_type": "live_draft_room",
            "created_from": "live_draft",
        },
        "league_rosters": _robins_league_rosters(),
    }


class DraftAssistantBoardResolutionTests(unittest.TestCase):
    def test_reconstructs_twenty_picks_from_league_rosters_only(self) -> None:
        session: dict = {
            FANTASY_LEAGUE_CONTEXT_STATE_KEY: {"contexts": {}, "active_league_context_id": ""},
        }
        ctx = _robins_context(my_team="Donny")
        upsert_league_context(session, ctx)
        session["room_team_count"] = 12
        session["room_rounds"] = 20

        resolution = resolve_draft_assistant_board(
            session,
            effective_context=ctx,
            active_archive={"draft_id": "c6810611c73e", "draft_type": "live_draft_room"},
            live_room={"status": "complete", "draft_board": []},
            context_mode="live_board",
        )
        board = resolution["board"]
        diag = resolution["diagnostics"]
        self.assertEqual(len(board), 20)
        self.assertEqual(diag["board_row_count_normalized"], 20)
        self.assertEqual(diag["unique_valid_pick_count"], 20)
        self.assertEqual(diag["min_pick"], 1)
        self.assertEqual(diag["max_pick"], 20)
        self.assertEqual(diag["missing_pick_numbers"], [])
        self.assertIn(diag["board_source_used"], ("effective_league_context", "active_archive"))

    def test_donny_and_team_b_pick_counts(self) -> None:
        ctx = _robins_context(my_team="Donny")
        resolution = resolve_draft_assistant_board(
            {},
            effective_context=ctx,
            context_mode="live_board",
        )
        board = resolution["board"]
        for my_team, other in (("Donny", "Team B"), ("Team B", "Donny")):
            summary = draft_board_summary_for_team(
                board,
                your_team=my_team,
                team_names=["Donny", "Team B"],
                num_teams=2,
                total_picks=20,
                room_status="complete",
            )
            self.assertEqual(summary["players_you_drafted"], 10)
            self.assertEqual(summary["players_league_drafted"], 10)
            self.assertTrue(summary["draft_complete"])
            self.assertEqual(summary["filled_picks"], 20)
            self.assertEqual(summary["rounds_complete"], 10)

    def test_empty_board_complete_status_is_data_incomplete(self) -> None:
        progress = derive_draft_progress(
            pd.DataFrame(),
            draft_order=["Donny", "Team B"],
            num_teams=2,
            total_picks=20,
            owned_team="Donny",
            room_status="complete",
        )
        self.assertTrue(progress["data_incomplete"])
        self.assertFalse(progress["draft_complete"])
        self.assertEqual(progress["display_status"], "Draft data unavailable")
        self.assertEqual(progress["filled_picks"], 0)
        self.assertEqual(progress["rounds_complete"], 0)

    def test_canonical_progress_vars_available_for_completed_draft(self) -> None:
        ctx = _robins_context()
        resolution = resolve_draft_assistant_board({}, effective_context=ctx, context_mode="live_board")
        board = resolution["board"]
        progress = derive_draft_progress(
            board,
            draft_order=["Donny", "Team B"],
            num_teams=2,
            total_picks=20,
            owned_team="Donny",
            room_status="complete",
        )
        current_pick = int(progress.get("current_pick") or 1)
        current_round = int(progress.get("current_round") or 1)
        draft_complete = bool(progress.get("draft_complete"))
        self.assertTrue(draft_complete)
        self.assertEqual(current_pick, 20)
        self.assertEqual(current_round, 10)
        self.assertIsInstance(current_pick, int)

    def test_partial_board_next_pick(self) -> None:
        rows = [
            {"Pick": 1, "Round": 1, "Team": "Donny", "Player": "A"},
            {"Pick": 2, "Round": 1, "Team": "Team B", "Player": "B"},
            {"Pick": 3, "Round": 2, "Team": "Donny", "Player": ""},
        ]
        table = pd.DataFrame(rows)
        progress = derive_draft_progress(
            table,
            draft_order=["Donny", "Team B"],
            num_teams=2,
            total_picks=20,
            owned_team="Donny",
        )
        self.assertEqual(progress["current_pick"], 3)
        self.assertEqual(progress["current_round"], 2)
        self.assertFalse(progress["draft_complete"])

    def test_normalize_deduplicates_by_pick(self) -> None:
        df = pd.DataFrame(
            [
                {"Pick": 1, "Team": "Donny", "Player": "A"},
                {"Pick": 1, "Team": "Donny", "Player": "Dup"},
                {"Pick": 2, "Team": "Team B", "Player": "B"},
            ]
        )
        normalized, diag = normalize_draft_board_df(df)
        self.assertEqual(len(normalized), 2)
        self.assertEqual(str(normalized.iloc[0]["Player"]), "A")
        self.assertEqual(diag["unique_valid_pick_count"], 2)


if __name__ == "__main__":
    unittest.main()
