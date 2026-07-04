"""Tests for Fantasy League Context model, migration, and persistence."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import pandas as pd

from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state
from draft_archive_state import (
    ACTIVE_DRAFT_ARCHIVE_KEY,
    DRAFT_ARCHIVE_KEY,
    activate_draft_archive,
    get_active_draft_archive,
    get_draft_archive,
    list_draft_archives,
    save_live_draft_team_archive,
    save_simulator_team_archive,
)
from fantasy_league_context import (
    CONTEXT_TYPE_LIVE_DRAFT_RESULT,
    CONTEXT_TYPE_MOCK_DRAFT_SIMULATION,
    FANTASY_LEAGUE_CONTEXT_STATE_KEY,
    MIGRATION_STATUS_FULL_LEAGUE,
    MIGRATION_STATUS_SINGLE_TEAM_LEGACY,
    SOURCE_LIVE_DRAFT_ROOM,
    activate_league_context,
    build_league_rosters_from_live_room,
    build_league_rosters_from_simulator_board,
    build_ownership_map,
    clear_active_league_context,
    context_id_for_archive,
    create_league_context_from_live_room,
    create_league_context_from_simulator_board,
    ensure_fantasy_league_context_state,
    get_active_league_context,
    get_league_context,
    get_league_context_for_archive,
    has_full_league_rosters,
    league_context_coverage_badge,
    league_context_type_badge,
    league_team_count,
    list_league_contexts,
    migrate_archive_to_league_context,
    migrate_legacy_archives_to_contexts,
    save_league_context,
    save_live_draft_league_context,
    save_simulator_league_context,
    set_active_league_context,
    upsert_league_context,
    activate_archive_league_context,
)


def _live_room_fixture() -> dict:
    return {
        "config": {
            "league_name": "Home League",
            "fantasy_format": "5x5 Roto",
            "slots": {"C": 1, "OF": 3},
            "scoring_type": "5x5 Roto",
        },
        "rosters": {
            "Daniel": [
                {"fullName": "Aaron Judge", "Primary Position": "OF", "playerID": "judgea01"},
            ],
            "Team 2": [
                {"fullName": "Juan Soto", "Primary Position": "OF", "playerID": "sotoj01"},
            ],
            "Team 3": [
                {"fullName": "Mike Trout", "Primary Position": "OF", "playerID": "troum01"},
            ],
        },
        "draft_board": [
            {"Fantasy Team": "Daniel", "fullName": "Aaron Judge", "Pick": 1, "Round": 1},
            {"Fantasy Team": "Team 2", "fullName": "Juan Soto", "Pick": 2, "Round": 1},
        ],
    }


class FantasyLeagueContextModelTests(unittest.TestCase):
    def test_ensure_state_initializes_empty_store(self) -> None:
        session: dict = {}
        store = ensure_fantasy_league_context_state(session)
        self.assertEqual(store["schema_version"], 1)
        self.assertEqual(store["active_league_context_id"], "")
        self.assertEqual(store["contexts"], {})
        self.assertIn(FANTASY_LEAGUE_CONTEXT_STATE_KEY, session)

    def test_build_league_rosters_from_live_room_multi_team(self) -> None:
        rosters = build_league_rosters_from_live_room(_live_room_fixture(), "Daniel")
        self.assertEqual(len(rosters), 3)
        self.assertTrue(rosters["Daniel"]["is_user_team"])
        self.assertFalse(rosters["Team 2"]["is_user_team"])
        self.assertEqual(rosters["Daniel"]["players"][0]["player_name"], "Aaron Judge")
        self.assertEqual(rosters["Daniel"]["players"][0]["player_key"], "aaron judge")
        self.assertEqual(rosters["Team 2"]["players"][0]["player_id"], "sotoj01")

    def test_build_league_rosters_from_simulator_multi_team(self) -> None:
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1, "Round": 1, "Primary Position": "OF"},
                {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2, "Round": 1, "Primary Position": "OF"},
            ]
        )
        rosters = build_league_rosters_from_simulator_board(board, "Daniel")
        self.assertEqual(len(rosters), 2)
        self.assertEqual(rosters["Daniel"]["players"][0]["player_name"], "Aaron Judge")
        self.assertEqual(rosters["Rivals"]["players"][0]["player_key"], "juan soto")

    def test_ownership_map_built_from_league_rosters(self) -> None:
        rosters = build_league_rosters_from_live_room(_live_room_fixture(), "Daniel")
        context = {
            "league_rosters": rosters,
        }
        ownership = build_ownership_map(context)
        self.assertEqual(ownership["aaron judge"]["owner_team"], "Daniel")
        self.assertTrue(ownership["aaron judge"]["is_user_team"])
        self.assertEqual(ownership["juan soto"]["owner_team"], "Team 2")
        self.assertFalse(ownership["juan soto"]["is_user_team"])


class FantasyLeagueContextMigrationTests(unittest.TestCase):
    def test_migrate_legacy_archive_single_team(self) -> None:
        archive = {
            "draft_id": "abc123",
            "draft_type": "simulator",
            "draft_name": "Mock 2026 — Daniel",
            "team_name": "Daniel",
            "fantasy_format": "5x5 Roto",
            "roster_slots": {"OF": 3},
            "slot_instances": [],
            "projection_settings": {"scoring_type": "5x5 Roto"},
            "players": [{"fullName": "Aaron Judge", "Primary Position": "OF"}],
            "created_at": "2026-07-01T12:00:00+00:00",
            "updated_at": "2026-07-02T12:00:00+00:00",
        }
        context = migrate_archive_to_league_context(archive)
        self.assertEqual(context["league_context_id"], "archive:abc123")
        self.assertEqual(context["context_type"], CONTEXT_TYPE_MOCK_DRAFT_SIMULATION)
        self.assertEqual(context["my_team_name"], "Daniel")
        self.assertEqual(context["metadata"]["migration_status"], MIGRATION_STATUS_SINGLE_TEAM_LEGACY)
        self.assertEqual(context["metadata"]["source_draft_id"], "abc123")
        self.assertIn("Daniel", context["league_rosters"])
        self.assertEqual(context["ownership_map"]["aaron judge"]["owner_team"], "Daniel")

    def test_migrate_legacy_archives_bulk_preserves_archives(self) -> None:
        session: dict = {}
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1, "Round": 1}])
        entry = save_simulator_team_archive(session, board, team_name="Daniel", draft_name="Legacy Draft")
        draft_id = str(entry["draft_id"])
        created = migrate_legacy_archives_to_contexts(session)
        self.assertEqual(created, 1)
        self.assertEqual(len(list_draft_archives(session)), 1)
        self.assertEqual(get_draft_archive(session, draft_id)["draft_name"], "Legacy Draft")
        contexts = list_league_contexts(session)
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0]["league_context_id"], context_id_for_archive(draft_id))

    def test_legacy_archives_still_load_after_migration(self) -> None:
        session: dict = {}
        board = pd.DataFrame([{"Team": "A", "Player": "Player One", "Pick": 1, "Round": 1}])
        entry = save_simulator_team_archive(session, board, team_name="A")
        activate_draft_archive(session, entry["draft_id"])
        migrate_legacy_archives_to_contexts(session)
        active_archive = get_active_draft_archive(session)
        assert active_archive is not None
        self.assertEqual(active_archive["team_name"], "A")
        self.assertEqual(len(session[DRAFT_ARCHIVE_KEY]), 1)

    def test_migrate_does_not_duplicate_existing_context(self) -> None:
        session: dict = {}
        board = pd.DataFrame([{"Team": "A", "Player": "P1", "Pick": 1, "Round": 1}])
        entry = save_simulator_team_archive(session, board, team_name="A")
        first = migrate_legacy_archives_to_contexts(session)
        second = migrate_legacy_archives_to_contexts(session)
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(len(list_league_contexts(session)), 1)
        store = ensure_fantasy_league_context_state(session)
        self.assertIn(str(entry["draft_id"]), store["legacy_migration"]["migrated_archive_ids"])


class FantasyLeagueContextPersistenceTests(unittest.TestCase):
    def test_upsert_persists_league_rosters_and_ownership_map(self) -> None:
        session: dict = {}
        rosters = build_league_rosters_from_live_room(_live_room_fixture(), "Daniel")
        context = create_league_context_from_live_room(
            session,
            _live_room_fixture(),
            my_team_name="Daniel",
            league_context_id="live:test001",
        )
        saved = upsert_league_context(session, context)
        self.assertEqual(len(saved["league_rosters"]), 3)
        self.assertIn("aaron judge", saved["ownership_map"])
        self.assertIn("juan soto", saved["ownership_map"])
        loaded = get_league_context(session, "live:test001")
        assert loaded is not None
        self.assertEqual(len(loaded["league_rosters"]), 3)
        self.assertEqual(loaded["ownership_map"]["mike trout"]["owner_team"], "Team 3")

    def test_save_new_league_context_from_simulator(self) -> None:
        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1, "Round": 1},
                {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2, "Round": 1},
            ]
        )
        context = create_league_context_from_simulator_board(
            session,
            board,
            my_team_name="Daniel",
            league_context_id="sim:test002",
        )
        self.assertEqual(context["context_type"], CONTEXT_TYPE_MOCK_DRAFT_SIMULATION)
        self.assertTrue(has_full_league_rosters(context))
        self.assertEqual(context["metadata"]["migration_status"], MIGRATION_STATUS_FULL_LEAGUE)
        stored = get_league_context(session, "sim:test002")
        assert stored is not None
        self.assertEqual(len(stored["league_rosters"]), 2)

    def test_active_league_context_set_restore_and_legacy_sync(self) -> None:
        session: dict = {}
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1, "Round": 1}])
        entry = save_simulator_team_archive(session, board, team_name="Daniel", draft_name="My Draft")
        migrate_legacy_archives_to_contexts(session)
        context_id = context_id_for_archive(str(entry["draft_id"]))
        activated = activate_league_context(session, context_id)
        assert activated is not None
        active = get_active_league_context(session)
        assert active is not None
        self.assertEqual(active["league_context_id"], context_id)
        self.assertEqual(session.get(ACTIVE_DRAFT_ARCHIVE_KEY), entry["draft_id"])
        self.assertEqual(session.get("room_your_team"), "Daniel")
        clear_active_league_context(session)
        self.assertIsNone(get_active_league_context(session))

    def test_set_active_without_activate_keeps_legacy_aliases(self) -> None:
        session: dict = {}
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1, "Round": 1}])
        entry = save_simulator_team_archive(session, board, team_name="Daniel")
        migrate_legacy_archives_to_contexts(session)
        context_id = context_id_for_archive(str(entry["draft_id"]))
        set_active_league_context(session, context_id)
        self.assertEqual(
            ensure_fantasy_league_context_state(session)["active_league_context_id"],
            context_id,
        )
        self.assertNotIn(ACTIVE_DRAFT_ARCHIVE_KEY, session)

    def test_disk_persistence_round_trip(self) -> None:
        st1 = MagicMock()
        st1.session_state = {}
        session = st1.session_state
        create_league_context_from_live_room(
            session,
            _live_room_fixture(),
            my_team_name="Daniel",
            league_context_id="live:disk001",
        )
        activate_league_context(session, "live:disk001")
        blob = build_baseball_disk_state(st1)
        self.assertIn(FANTASY_LEAGUE_CONTEXT_STATE_KEY, blob)
        store = blob[FANTASY_LEAGUE_CONTEXT_STATE_KEY]
        self.assertEqual(store["active_league_context_id"], "live:disk001")
        self.assertIn("live:disk001", store["contexts"])
        self.assertIn("aaron judge", store["contexts"]["live:disk001"]["ownership_map"])

        st2 = MagicMock()
        st2.session_state = {}
        apply_baseball_disk_state(st2, blob)
        restored = get_active_league_context(st2.session_state)
        assert restored is not None
        self.assertEqual(restored["league_context_id"], "live:disk001")
        self.assertEqual(len(restored["league_rosters"]), 3)
        self.assertEqual(restored["ownership_map"]["juan soto"]["owner_team"], "Team 2")

    def test_disk_apply_migrates_legacy_archives(self) -> None:
        session: dict = {}
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1, "Round": 1}])
        entry = save_simulator_team_archive(session, board, team_name="Daniel")
        activate_draft_archive(session, entry["draft_id"])
        st1 = MagicMock()
        st1.session_state = session
        blob = build_baseball_disk_state(st1)

        st2 = MagicMock()
        st2.session_state = {DRAFT_ARCHIVE_KEY: blob[DRAFT_ARCHIVE_KEY], ACTIVE_DRAFT_ARCHIVE_KEY: entry["draft_id"]}
        apply_baseball_disk_state(st2, blob)
        ss = st2.session_state
        contexts = list_league_contexts(ss)
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0]["metadata"]["migration_status"], MIGRATION_STATUS_SINGLE_TEAM_LEGACY)
        active = get_active_league_context(ss)
        assert active is not None
        self.assertEqual(active["league_context_id"], context_id_for_archive(str(entry["draft_id"])))

    def test_live_draft_archive_migration_type(self) -> None:
        session: dict = {}
        room = _live_room_fixture()
        entry = save_live_draft_team_archive(session, room, team_name="Daniel", draft_name="Live Save")
        migrate_legacy_archives_to_contexts(session)
        context = get_league_context(session, context_id_for_archive(str(entry["draft_id"])))
        assert context is not None
        self.assertEqual(context["context_type"], CONTEXT_TYPE_LIVE_DRAFT_RESULT)
        self.assertEqual(context["metadata"]["source"], "legacy_migration")

    def test_save_league_context_wrapper(self) -> None:
        session: dict = {}
        rosters = build_league_rosters_from_live_room(_live_room_fixture(), "Daniel")
        context = {
            "league_context_id": "live:wrapper01",
            "context_type": CONTEXT_TYPE_LIVE_DRAFT_RESULT,
            "league_name": "Home League",
            "display_name": "Home League — Daniel",
            "my_team_name": "Daniel",
            "fantasy_format": "5x5 Roto",
            "scoring_settings": {},
            "roster_settings": {"roster_slots": {}, "slot_instances": []},
            "league_rosters": rosters,
            "ownership_map": {},
            "workflow": {
                "trade_candidates": [],
                "acquire_targets": [],
                "add_targets": [],
                "drop_candidates": [],
            },
            "metadata": {
                "created_at": "2026-07-04T12:00:00+00:00",
                "updated_at": "2026-07-04T12:00:00+00:00",
                "source_draft_id": "",
                "source_workspace": "",
                "source": SOURCE_LIVE_DRAFT_ROOM,
                "migration_status": MIGRATION_STATUS_FULL_LEAGUE,
            },
        }
        saved = save_league_context(session, context)
        self.assertIn("aaron judge", saved["ownership_map"])
        loaded = get_league_context(session, "live:wrapper01")
        assert loaded is not None
        self.assertEqual(loaded["display_name"], "Home League — Daniel")


class FantasyLeagueContextSaveFlowTests(unittest.TestCase):
    def test_save_live_draft_league_context_full_league(self) -> None:
        session: dict = {}
        entry, context = save_live_draft_league_context(
            session,
            _live_room_fixture(),
            my_team_name="Daniel",
            draft_name="Home League — Daniel",
        )
        self.assertEqual(len(entry.get("league_rosters") or {}), 3)
        self.assertEqual(entry.get("league_context_id"), context_id_for_archive(str(entry["draft_id"])))
        self.assertTrue(has_full_league_rosters(context))
        self.assertEqual(context["context_type"], CONTEXT_TYPE_LIVE_DRAFT_RESULT)
        self.assertEqual(league_context_coverage_badge(context), "Full League Context")
        active = get_active_league_context(session)
        assert active is not None
        self.assertEqual(active["league_context_id"], context["league_context_id"])

    def test_save_simulator_league_context_mock_draft(self) -> None:
        session: dict = {}
        board = pd.DataFrame(
            [
                {"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1, "Round": 1},
                {"Team": "Rivals", "Player": "Juan Soto", "Pick": 2, "Round": 1},
            ]
        )
        entry, context = save_simulator_league_context(
            session,
            board,
            my_team_name="Daniel",
            draft_name="Mock 2026",
        )
        self.assertEqual(len(entry.get("league_rosters") or {}), 2)
        self.assertEqual(context["context_type"], CONTEXT_TYPE_MOCK_DRAFT_SIMULATION)
        self.assertEqual(league_context_type_badge(context), "Mock Draft Simulation")
        self.assertEqual(league_context_coverage_badge(context), "Full League Context")

    def test_legacy_archive_badges(self) -> None:
        session: dict = {}
        board = pd.DataFrame([{"Team": "Daniel", "Player": "Aaron Judge", "Pick": 1, "Round": 1}])
        entry = save_simulator_team_archive(session, board, team_name="Daniel")
        migrate_legacy_archives_to_contexts(session)
        context = get_league_context_for_archive(session, entry)
        assert context is not None
        self.assertEqual(league_context_coverage_badge(context), "My Team Only / Legacy")
        self.assertEqual(league_context_type_badge(context), "Mock Draft Simulation")
        self.assertEqual(league_team_count(context, entry), 1)

    def test_activate_archive_league_context(self) -> None:
        session: dict = {}
        entry, _ = save_live_draft_league_context(
            session,
            _live_room_fixture(),
            my_team_name="Daniel",
        )
        clear_active_league_context(session)
        from draft_archive_state import clear_active_draft_archive

        clear_active_draft_archive(session)
        loaded_entry, loaded_context = activate_archive_league_context(session, str(entry["draft_id"]))
        assert loaded_entry is not None
        assert loaded_context is not None
        self.assertEqual(get_active_league_context(session)["league_context_id"], loaded_context["league_context_id"])


if __name__ == "__main__":
    unittest.main()
