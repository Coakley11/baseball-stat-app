"""Team identity + stale board label recovery for shared league transfer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE
from live_draft_completion import apply_live_draft_completion
from live_draft_roster_transfer import (
    build_authoritative_live_draft_rosters,
    extract_draft_results_from_room,
    get_roster_transfer_diagnostics,
    validate_roster_transfer,
)
from live_draft_shared_league import preview_shared_league_creation, save_live_draft_shared_league_context
from live_draft_team_identity import build_board_team_resolution, sync_room_team_display_names
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store


def _live_robins_fantasy_room() -> dict:
    """Live-style completed room: board Team 1/Team 2, room rosters Donny/Team B."""
    donny_players = [
        ("p_judge", "Aaron Judge", "OF"),
        ("p_ohtani", "Shohei Ohtani", "DH"),
        ("p_betts", "Mookie Betts", "OF"),
        ("p_soto", "Juan Soto", "OF"),
        ("p_acuna", "Ronald Acuna Jr.", "OF"),
        ("p_trout", "Mike Trout", "OF"),
        ("p_tatis", "Fernando Tatis Jr.", "OF"),
        ("p_harper", "Bryce Harper", "OF"),
        ("p_alonso", "Pete Alonso", "1B"),
        ("p_freeman", "Freddie Freeman", "1B"),
    ]
    team_b_players = [
        ("p_ramirez", "Jose Ramirez", "3B"),
        ("p_lindor", "Francisco Lindor", "SS"),
        ("p_seager", "Corey Seager", "SS"),
        ("p_turner", "Trea Turner", "SS"),
        ("p_bogaerts", "Xander Bogaerts", "SS"),
        ("p_arenado", "Nolan Arenado", "3B"),
        ("p_riley", "Austin Riley", "3B"),
        ("p_devers", "Rafael Devers", "3B"),
        ("p_yordan", "Yordan Alvarez", "OF"),
        ("p_kyle", "Kyle Tucker", "OF"),
    ]
    teams_legacy = ["Team 1", "Team 2"]
    teams_current = ["Donny", "Team B"]
    pick_order = []
    board = []
    rosters = {teams_current[0]: [], teams_current[1]: []}
    pick_no = 1
    for rnd in range(1, 11):
        round_teams = teams_legacy if rnd % 2 == 1 else list(reversed(teams_legacy))
        for legacy_team in round_teams:
            pool = donny_players if legacy_team == "Team 1" else team_b_players
            idx = (pick_no - 1) // 2
            pid, name, pos = pool[idx]
            current_team = teams_current[0 if legacy_team == "Team 1" else 1]
            row = {
                "Pick": pick_no,
                "Round": rnd,
                "Team": legacy_team,
                "Fantasy Team": legacy_team,
                "playerID": pid,
                "fullName": name,
                "Primary Position": pos,
            }
            board.append(row)
            rosters[current_team].append(dict(row))
            pick_order.append({"Pick": pick_no, "Round": rnd, "Team": legacy_team})
            pick_no += 1
    return {
        "draft_room_id": "ROBINS-LIVE",
        "status": "complete",
        "current_pick_index": 20,
        "teams": teams_current,
        "config": {
            "league_name": "Robins Fantasy",
            "num_teams": 2,
            "picks_per_team": 10,
            "teams": teams_current,
            "fantasy_format": "5x5 Roto",
            "scoring_type": "Roto (5x5)",
        },
        "pick_order": pick_order,
        "draft_board": board,
        "rosters": rosters,
        "drafted_player_ids": [p[0] for p in donny_players + team_b_players],
        "pool": [],
    }


class LiveDraftTeamIdentityTests(unittest.TestCase):
    def test_rename_map_resolves_team_1_and_team_2_to_current_names(self) -> None:
        room = _live_robins_fantasy_room()
        diag = build_board_team_resolution(room)
        self.assertEqual(diag["room_teams"], ["Donny", "Team B"])
        self.assertEqual(set(diag["draft_board_distinct_team_values"]), {"Team 1", "Team 2"})
        self.assertEqual(diag["team_rename_map"]["Team 1"], "Donny")
        self.assertEqual(diag["team_rename_map"]["Team 2"], "Team B")
        self.assertEqual(diag["unmapped_board_teams"], [])

    def test_extract_maps_all_twenty_picks_to_donny_and_team_b(self) -> None:
        room = _live_robins_fantasy_room()
        results = extract_draft_results_from_room(room)
        self.assertEqual(len(results), 20)
        teams = {str(r["team"]) for r in results}
        self.assertEqual(teams, {"Donny", "Team B"})
        donny = [r for r in results if r["team"] == "Donny"]
        team_b = [r for r in results if r["team"] == "Team B"]
        self.assertEqual(len(donny), 10)
        self.assertEqual(len(team_b), 10)
        donny_names = {r["player_name"] for r in donny}
        self.assertIn("Aaron Judge", donny_names)
        self.assertIn("Shohei Ohtani", donny_names)
        self.assertIn("Mookie Betts", donny_names)
        team_b_names = {r["player_name"] for r in team_b}
        self.assertIn("Jose Ramirez", team_b_names)
        self.assertNotIn("Mookie Betts", team_b_names)

    def test_pick_order_and_rounds_unchanged_after_normalization(self) -> None:
        room = _live_robins_fantasy_room()
        before = [(int(r["Pick"]), int(r["Round"])) for r in room["draft_board"]]
        results = extract_draft_results_from_room(room)
        after = [(int(r["pick_number"]), int(r["round"])) for r in results]
        self.assertEqual(before, after)

    def test_authoritative_rosters_validate_with_zero_errors(self) -> None:
        room = _live_robins_fantasy_room()
        apply_live_draft_completion(room, {})
        results, league_rosters, errors = build_authoritative_live_draft_rosters(room, my_team_name="Donny")
        self.assertEqual(errors, [], errors)
        self.assertEqual(len(results), 20)
        self.assertEqual(len(league_rosters["Donny"]["players"]), 10)
        self.assertEqual(len(league_rosters["Team B"]["players"]), 10)

    def test_shared_league_preview_ready_for_live_room(self) -> None:
        room = _live_robins_fantasy_room()
        apply_live_draft_completion(room, {})
        preview = preview_shared_league_creation(room, my_team_name="Donny", league_name="Robins Fantasy")
        self.assertTrue(preview.get("ready"), preview.get("validation_errors"))
        self.assertEqual(preview.get("validation_errors"), [])
        self.assertEqual(preview["roster_count_by_team"]["Donny"], 10)
        self.assertEqual(preview["roster_count_by_team"]["Team B"], 10)
        diag = preview.get("roster_transfer_diagnostics") or {}
        self.assertEqual(set(diag.get("draft_board_distinct_team_values") or []), {"Team 1", "Team 2"})
        notes = " ".join(diag.get("resolution_notes") or [])
        self.assertIn("Team 1", notes)
        self.assertIn("team_1", notes)
        notes = " ".join(diag.get("resolution_notes") or [])
        self.assertIn("Team 1", notes)
        self.assertIn("team_1", notes)

    def test_sync_room_team_display_names_updates_pick_order_before_draft(self) -> None:
        room = {
            "teams": ["Team 1", "Team 2"],
            "config": {"teams": ["Team 1", "Team 2"]},
            "pick_order": [
                {"Pick": 1, "Round": 1, "Team": "Team 1"},
                {"Pick": 2, "Round": 1, "Team": "Team 2"},
            ],
            "rosters": {"Team 1": [], "Team 2": []},
            "draft_board": [],
        }
        sync_room_team_display_names(room, ["Donny", "Team B"])
        self.assertEqual(room["teams"], ["Donny", "Team B"])
        self.assertEqual(room["pick_order"][0]["Team"], "Donny")
        self.assertEqual(room["pick_order"][1]["Team"], "Team B")

    def test_ambiguous_mapping_is_blocked(self) -> None:
        room = _live_robins_fantasy_room()
        dup = dict(room["rosters"]["Donny"][0])
        room["rosters"]["Team B"].append(dup)
        for row in room["draft_board"]:
            if row.get("playerID") == dup.get("playerID"):
                row["Team"] = row["Fantasy Team"] = "Mystery Squad"
        extract_draft_results_from_room(room)
        self.assertTrue(room.get("_live_draft_roster_transfer_errors"))
        _, _, errors = build_authoritative_live_draft_rosters(room, my_team_name="Donny")
        self.assertTrue(errors)
        self.assertTrue(any("unresolved" in e.lower() or "Mystery" in e for e in errors))

    def test_non_renamed_teams_unchanged(self) -> None:
        room = _live_robins_fantasy_room()
        for row in room["draft_board"]:
            legacy = str(row.get("Team") or "")
            row["Team"] = row["Fantasy Team"] = "Donny" if legacy == "Team 1" else "Team B"
        for slot in room["pick_order"]:
            legacy = str(slot.get("Team") or "")
            slot["Team"] = "Donny" if legacy == "Team 1" else "Team B"
        results = extract_draft_results_from_room(room)
        self.assertEqual(len(results), 20)
        _, _, errors = build_authoritative_live_draft_rosters(room, my_team_name="Donny")
        self.assertEqual(errors, [])


class LiveDraftTeamIdentityRecoveryIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmpdir.name)))
        self.session: dict = {}

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmpdir.cleanup()

    def test_existing_completed_room_creates_shared_league_once(self) -> None:
        room = _live_robins_fantasy_room()
        apply_live_draft_completion(room, self.session)
        entry, context = save_live_draft_shared_league_context(
            self.session,
            room,
            my_team_name="Donny",
            league_name="Robins Fantasy",
            draft_name="Robins Fantasy Completed Draft",
            assign_team=True,
            preassign_owners={
                "Donny": {"user_id": "user:donny", "email": "donny@test", "display_name": "Donny"},
            },
        )
        self.assertEqual(context.get("context_type"), CONTEXT_TYPE_REAL_LEAGUE)
        self.assertEqual(len(entry.get("league_rosters") or context.get("league_rosters") or {}), 2)


if __name__ == "__main__":
    unittest.main()
