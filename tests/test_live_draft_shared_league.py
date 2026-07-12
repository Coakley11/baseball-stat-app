"""Tests for Live Draft → shared league workflow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE, get_league_context
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_league_team_ownership import (
    TRADES_AWAITING_CLAIMS_MESSAGE,
    assign_team_owner_to_context,
    get_team_ownership,
    owned_team_for_user,
    trades_enabled,
    upsert_league_context,
)
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from live_draft_completion import COMPLETION_RECORD_KEY, apply_live_draft_completion, is_live_draft_explicitly_complete
from live_draft_completion import DRAFT_COMPLETE_HUB_ACTIONS
from live_draft_roster_transfer import (
    build_authoritative_live_draft_rosters,
    extract_draft_results_from_room,
    validate_roster_transfer,
)
from live_draft_shared_league import preview_shared_league_creation, save_live_draft_shared_league_context
from tests.test_imported_shared_league import _as_user


def _completed_two_team_room() -> dict:
    board = [
        {"Pick": 1, "Round": 1, "Team": "Daniel", "playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF"},
        {"Pick": 2, "Round": 1, "Team": "Team 2", "playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF"},
        {"Pick": 3, "Round": 2, "Team": "Team 2", "playerID": "p3", "fullName": "Gunnar Henderson", "Primary Position": "SS"},
        {"Pick": 4, "Round": 2, "Team": "Daniel", "playerID": "p4", "fullName": "Mookie Betts", "Primary Position": "OF"},
    ]
    rosters = {
        "Daniel": [
            {"playerID": "p1", "fullName": "Juan Soto", "Primary Position": "OF"},
            {"playerID": "p4", "fullName": "Mookie Betts", "Primary Position": "OF"},
        ],
        "Team 2": [
            {"playerID": "p2", "fullName": "Aaron Judge", "Primary Position": "OF"},
            {"playerID": "p3", "fullName": "Gunnar Henderson", "Primary Position": "SS"},
        ],
    }
    return {
        "draft_room_id": "live-two-team-test",
        "status": "complete",
        "current_pick_index": 4,
        "teams": ["Daniel", "Team 2"],
        "config": {
            "league_name": "Two Team Live Draft",
            "num_teams": 2,
            "picks_per_team": 2,
            "fantasy_format": "5x5 Roto",
            "scoring_type": "Roto (5x5)",
            "slots": {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "DH": 1, "P": 5, "BN": 3},
        },
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Daniel"},
            {"Pick": 2, "Round": 1, "Team": "Team 2"},
            {"Pick": 3, "Round": 2, "Team": "Team 2"},
            {"Pick": 4, "Round": 2, "Team": "Daniel"},
        ],
        "draft_board": board,
        "rosters": rosters,
        "drafted_player_ids": ["p1", "p2", "p3", "p4"],
        "pool": [],
    }


class LiveDraftRosterTransferTests(unittest.TestCase):
    def test_extract_draft_results_preserves_every_pick(self) -> None:
        room = _completed_two_team_room()
        results = extract_draft_results_from_room(room)
        self.assertEqual(len(results), 4)
        self.assertEqual(results[0]["team"], "Daniel")
        self.assertEqual(results[0]["player_name"], "Juan Soto")
        self.assertEqual(results[1]["team"], "Team 2")

    def test_validate_roster_transfer_passes_for_completed_board(self) -> None:
        room = _completed_two_team_room()
        results = extract_draft_results_from_room(room)
        _, league_rosters, errors = build_authoritative_live_draft_rosters(room, my_team_name="Daniel")
        self.assertEqual(errors, [])
        ok, validation_errors = validate_roster_transfer(room, results, league_rosters)
        self.assertTrue(ok)
        self.assertEqual(validation_errors, [])

    def test_validate_roster_transfer_blocks_mismatch(self) -> None:
        room = _completed_two_team_room()
        results = extract_draft_results_from_room(room)
        _, league_rosters, _ = build_authoritative_live_draft_rosters(room, my_team_name="Daniel")
        league_rosters["Daniel"]["players"] = []
        ok, errors = validate_roster_transfer(room, results, league_rosters)
        self.assertFalse(ok)
        self.assertTrue(any("missing drafted players" in e for e in errors))


class LiveDraftCompletionTests(unittest.TestCase):
    def test_apply_completion_sets_locked_record(self) -> None:
        room = _completed_two_team_room()
        session: dict = {}
        apply_live_draft_completion(room, session)
        self.assertTrue(is_live_draft_explicitly_complete(room))
        record = room.get(COMPLETION_RECORD_KEY) or {}
        self.assertEqual(record.get("draft_status"), "complete")
        self.assertTrue(record.get("final_board_locked"))
        self.assertIsNone(room.get("timer_started_at"))

    def test_draft_complete_hub_actions(self) -> None:
        self.assertIn("Create Shared League", DRAFT_COMPLETE_HUB_ACTIONS)
        self.assertIn("Review Draft Results", DRAFT_COMPLETE_HUB_ACTIONS)
        self.assertNotIn("Set Active Draft", DRAFT_COMPLETE_HUB_ACTIONS)


class LiveDraftSharedLeagueTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmpdir.name)))
        self.session: dict = {}

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmpdir.cleanup()

    def test_preview_includes_exact_rosters(self) -> None:
        room = _completed_two_team_room()
        apply_live_draft_completion(room, {})
        preview = preview_shared_league_creation(room, my_team_name="Daniel", league_name="Daniel vs Team 2")
        self.assertTrue(preview.get("ready"))
        self.assertEqual(set((preview.get("roster_count_by_team") or {}).keys()), {"Daniel", "Team 2"})
        daniel_players = [
            str(p.get("player_name") or "")
            for p in (preview.get("final_rosters") or {}).get("Daniel", {}).get("players") or []
        ]
        self.assertIn("Juan Soto", daniel_players)
        self.assertIn("Mookie Betts", daniel_players)

    def test_save_creates_real_league_with_canonical_id(self) -> None:
        room = _completed_two_team_room()
        apply_live_draft_completion(room, self.session)
        entry, context = save_live_draft_shared_league_context(
            self.session,
            room,
            my_team_name="Daniel",
            league_name="Daniel vs Team 2",
            draft_name="Completed Live Draft",
            assign_team=True,
            preassign_owners={
                "Daniel": {"user_id": "user:daniel", "email": "daniel@test", "display_name": "Daniel"},
            },
        )
        self.assertEqual(context.get("context_type"), CONTEXT_TYPE_REAL_LEAGUE)
        self.assertTrue(resolve_canonical_league_id(context))
        self.assertEqual(entry.get("context_type"), CONTEXT_TYPE_REAL_LEAGUE)
        meta = context.get("metadata") or {}
        self.assertEqual(meta.get("created_from"), "live_draft")
        self.assertEqual(len(meta.get("draft_results") or context.get("draft_results") or []), 4)

    def test_one_owner_blocks_trades_second_owner_enables(self) -> None:
        room = _completed_two_team_room()
        apply_live_draft_completion(room, self.session)
        _entry, context = save_live_draft_shared_league_context(
            self.session,
            room,
            my_team_name="Daniel",
            league_name="Trade Gate League",
            assign_team=True,
            preassign_owners={
                "Daniel": {"user_id": "user:daniel", "email": "daniel@test", "display_name": "Daniel"},
            },
        )
        league_context_id = str(context.get("league_context_id") or "")
        loaded = get_league_context(self.session, league_context_id) or context
        with _as_user("user:daniel"):
            enabled, msg = trades_enabled(loaded, self.session)
        self.assertFalse(enabled)
        self.assertEqual(msg, TRADES_AWAITING_CLAIMS_MESSAGE)

        loaded = assign_team_owner_to_context(
            loaded,
            "Team 2",
            user_id="user:coakley11",
            email="coakley11@test",
            display_name="Team 2 Owner",
        )
        upsert_league_context(self.session, loaded)
        with _as_user("user:daniel"):
            enabled, _msg = trades_enabled(loaded, self.session)
        self.assertTrue(enabled)
        ownership = get_team_ownership(loaded)
        self.assertIn("Daniel", ownership)
        self.assertIn("Team 2", ownership)
        with _as_user("user:daniel"):
            self.assertEqual(owned_team_for_user(loaded), "Daniel")
        with _as_user("user:coakley11"):
            self.assertEqual(owned_team_for_user(loaded), "Team 2")

    def test_exact_roster_transfer_chain_matches_board(self) -> None:
        room = _completed_two_team_room()
        results = extract_draft_results_from_room(room)
        _, league_rosters, errors = build_authoritative_live_draft_rosters(room, my_team_name="Daniel")
        self.assertEqual(errors, [])
        board_names = {str(r["player_name"]) for r in results}
        roster_names = {
            str(p.get("player_name") or "")
            for entry in league_rosters.values()
            for p in (entry.get("players") or [])
            if str(p.get("player_name") or "").strip()
        }
        self.assertEqual(board_names, roster_names)
        self.assertEqual(len(results), sum(len((e or {}).get("players") or []) for e in league_rosters.values()))

    def test_identical_live_draft_reuses_canonical_league_id(self) -> None:
        room = _completed_two_team_room()
        apply_live_draft_completion(room, self.session)
        _entry_a, ctx_a = save_live_draft_shared_league_context(
            self.session,
            room,
            my_team_name="Daniel",
            league_name="Canonical Live League",
            assign_team=True,
            preassign_owners={"Daniel": {"user_id": "user:daniel", "email": "daniel@test", "display_name": "Daniel"}},
        )
        _entry_b, ctx_b = save_live_draft_shared_league_context(
            self.session,
            room,
            my_team_name="Team 2",
            league_name="Canonical Live League copy",
            assign_team=True,
            preassign_owners={"Team 2": {"user_id": "user:coakley11", "email": "coakley11@test", "display_name": "Team 2"}},
        )
        self.assertEqual(resolve_canonical_league_id(ctx_a), resolve_canonical_league_id(ctx_b))

    def test_changed_roster_changes_canonical_league_id(self) -> None:
        room = _completed_two_team_room()
        apply_live_draft_completion(room, self.session)
        _entry_a, ctx_a = save_live_draft_shared_league_context(
            self.session,
            room,
            my_team_name="Daniel",
            league_name="Canonical A",
            assign_team=False,
        )
        mutated = dict(room)
        mutated_board = list(room["draft_board"])
        mutated_board[0] = dict(mutated_board[0])
        mutated_board[0]["fullName"] = "Different Player"
        mutated_board[0]["playerID"] = "px"
        mutated["draft_board"] = mutated_board
        mutated["rosters"] = dict(room["rosters"])
        mutated["rosters"]["Daniel"] = [
            {"playerID": "px", "fullName": "Different Player", "Primary Position": "OF"},
            {"playerID": "p4", "fullName": "Mookie Betts", "Primary Position": "OF"},
        ]
        apply_live_draft_completion(mutated, self.session)
        _entry_b, ctx_b = save_live_draft_shared_league_context(
            self.session,
            mutated,
            my_team_name="Daniel",
            league_name="Canonical B",
            assign_team=False,
        )
        self.assertNotEqual(resolve_canonical_league_id(ctx_a), resolve_canonical_league_id(ctx_b))

    def test_completion_blocks_additional_pick_gate(self) -> None:
        from draft_actions import resolve_player_draft_gate

        room = _completed_two_team_room()
        session = {"live_draft_room": apply_live_draft_completion(room, {})}
        gate = resolve_player_draft_gate(session, "Free Agent")
        self.assertTrue(gate.get("draft_complete"))
        self.assertEqual(gate.get("disable_reason"), "draft_complete")

    def test_preview_does_not_create_shared_league(self) -> None:
        room = _completed_two_team_room()
        apply_live_draft_completion(room, self.session)
        preview = preview_shared_league_creation(room, my_team_name="Daniel")
        self.assertTrue(preview.get("ready"))
        self.assertIsNone(get_league_context(self.session, str(preview.get("canonical_league_id") or "")))


if __name__ == "__main__":
    unittest.main()
