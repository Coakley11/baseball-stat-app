"""Live Draft Shared League: origin badge + second-account visibility."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from draft_archive_state import DRAFT_TYPE_IMPORTED, DRAFT_TYPE_LIVE, draft_type_display
from draft_archive_visibility import list_visible_draft_archives
from fantasy_league_context import (
    CONTEXT_TYPE_REAL_LEAGUE,
    CREATION_ORIGIN_LIVE_DRAFT_ROOM,
    resolve_archive_draft_type_with_reason,
)
from fantasy_shared_league_library_sync import materialize_owned_shared_leagues_for_session
from fantasy_shared_league_startup_sync import discover_shared_league_memberships_for_session
from fantasy_shared_league_store import LocalFileSharedLeagueStore, load_shared_league, set_shared_league_store
from live_draft_completion import COMPLETION_RECORD_KEY
from live_draft_shared_league import save_live_draft_shared_league_context
from tests.test_fantasy_trade_proposals import _as_user


def _auth_session(*, user_id: str, external_id: str, workspace: str, email: str, auth_uuid: str) -> dict:
    return {
        "_suite_auth_session": True,
        "_suite_auth_user_id": auth_uuid,
        "_suite_auth_user_email": email,
        "_suite_auth_external_id": external_id,
        "_suite_cloud_user_id": user_id,
        "_suite_active_workspace_id": workspace,
        "_suite_owned_workspace_id": workspace,
        "active_shared_draft_room_code": "ROOM99",
        "draft_shared_settings": {
            "fantasy_format": "5x5 Roto",
            "scoring_type": "Roto (5x5)",
            "slots": {"C": 1, "1B": 1, "OF": 1},
        },
    }


def _complete_two_team_room() -> dict:
    return {
        "status": "complete",
        "draft_room_id": "live-room-vis-1",
        "room_code": "ROOM99",
        "sync": {"room_code": "ROOM99"},
        "teams": ["Team 1", "Team 2"],
        "config": {
            "user_team": "Team 1",
            "num_teams": 2,
            "teams": ["Team 1", "Team 2"],
            "fantasy_format": "5x5 Roto",
            "scoring_type": "Roto (5x5)",
            "slots": {"C": 1, "1B": 1, "OF": 1},
            "league_name": "Visibility Live Draft",
        },
        "draft_board": [
            {"Round": 1, "Pick": 1, "Team": "Team 1", "Player": "Aaron Judge"},
            {"Round": 1, "Pick": 2, "Team": "Team 2", "Player": "Juan Soto"},
            {"Round": 2, "Pick": 3, "Team": "Team 2", "Player": "Mookie Betts"},
            {"Round": 2, "Pick": 4, "Team": "Team 1", "Player": "Freddie Freeman"},
        ],
        "pick_order": [
            {"Team": "Team 1"},
            {"Team": "Team 2"},
            {"Team": "Team 2"},
            {"Team": "Team 1"},
        ],
        "current_pick_index": 4,
        COMPLETION_RECORD_KEY: {"complete": True, "reason": "all_picks_filled"},
    }


class LiveDraftSharedLeagueOriginVisibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LocalFileSharedLeagueStore(root=Path(self._tmp.name))
        set_shared_league_store(self.store)

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmp.cleanup()

    def test_save_keeps_live_draft_origin_not_imported(self) -> None:
        daniel = _auth_session(
            user_id="user:daniel",
            external_id="daniel",
            workspace="daniel",
            email="daniel@example.com",
            auth_uuid="auth-daniel-uuid",
        )
        room = _complete_two_team_room()
        with _as_user("user:daniel"), patch(
            "live_draft_shared_league.load_shared_room",
            create=True,
        ), patch(
            "draft_room_shared_state.load_shared_room",
            return_value={
                "room_code": "ROOM99",
                "participants": {
                    "auth-daniel-uuid": {
                        "assigned_team": "Team 1",
                        "display_name": "daniel@example.com",
                        "user_id": "user:daniel",
                        "account_user_id": "user:daniel",
                        "external_id": "daniel",
                        "email": "daniel@example.com",
                    },
                    "auth-coakley-uuid": {
                        "assigned_team": "Team 2",
                        "display_name": "coakley11@aol.com",
                        "user_id": "user:coakley",
                        "account_user_id": "user:coakley",
                        "external_id": "coakley11",
                        "email": "coakley11@aol.com",
                    },
                },
            },
        ):
            entry, context = save_live_draft_shared_league_context(
                daniel,
                room,
                my_team_name="Team 1",
                league_name="Visibility Live Draft",
                draft_name="Visibility Live Draft",
                defer_activation=True,
                assign_team=True,
            )

        self.assertEqual(entry.get("draft_type"), DRAFT_TYPE_LIVE)
        self.assertEqual(draft_type_display(entry), "Live Draft")
        self.assertEqual(
            str((context.get("metadata") or {}).get("creation_origin") or ""),
            CREATION_ORIGIN_LIVE_DRAFT_ROOM,
        )
        league_id = str(context.get("league_id") or (context.get("metadata") or {}).get("league_id") or "")
        shared = load_shared_league(league_id)
        self.assertIsInstance(shared, dict)
        self.assertEqual(str(shared.get("created_from") or ""), "live_draft")
        self.assertEqual(str(shared.get("creation_origin") or ""), CREATION_ORIGIN_LIVE_DRAFT_ROOM)
        ownership = shared.get("team_ownership") or {}
        team2 = ownership.get("Team 2") or {}
        # Seat is reserved for coakley11 but stays unclaimed until invite Accept.
        self.assertFalse(str(team2.get("user_id") or ""))
        self.assertTrue(bool(team2.get("provisional")))
        self.assertEqual(str(team2.get("reserved_for_external_id") or "").lower(), "coakley11")
        self.assertIn("@", str(team2.get("reserved_for_email") or team2.get("email") or ""))

        # Commissioner repair must not rewrite Live Draft → Imported League.
        draft_type, reason, _ = resolve_archive_draft_type_with_reason(
            context={
                "context_type": CONTEXT_TYPE_REAL_LEAGUE,
                "metadata": {"commissioner_user_id": "user:daniel"},
            },
            shared_doc=shared,
            archive_entry={"draft_type": DRAFT_TYPE_LIVE},
        )
        self.assertEqual(draft_type, DRAFT_TYPE_LIVE)
        self.assertNotEqual(reason, "real_league_default_import")

    def test_second_account_discovers_membership_from_email_display_name(self) -> None:
        """Legacy docs may store Auth UUID + email display_name only."""
        from fantasy_shared_league_startup_sync import _record_matches_account

        legacy_owner = {
            "user_id": "auth-coakley-uuid",
            "email": "",
            "external_id": "",
            "display_name": "coakley11@aol.com",
        }
        self.assertTrue(
            _record_matches_account(
                legacy_owner,
                user_id="user:coakley",
                external_id="coakley11",
                workspace_id="coakley11",
            )
        )
        shared_doc = {
            "league_id": "league:legacy-live",
            "draft_id": "draft-legacy-live",
            "created_from": "live_draft",
            "source": "live_draft_room",
            "source_draft_type": "live_draft_room",
            "creation_origin": CREATION_ORIGIN_LIVE_DRAFT_ROOM,
            "commissioner_user_id": "user:daniel",
            "team_ownership": {
                "Team 1": {
                    "user_id": "user:daniel",
                    "email": "daniel@example.com",
                    "external_id": "daniel",
                    "display_name": "Daniel",
                },
                "Team 2": legacy_owner,
            },
            "league_rosters": {
                "Team 1": {"players": [{"player_name": "Aaron Judge"}]},
                "Team 2": {"players": [{"player_name": "Juan Soto"}]},
            },
            "roster_settings": {"roster_slots": {"C": 1}},
            "revision": 1,
        }
        self.store.save(shared_doc)
        coakley = _auth_session(
            user_id="user:coakley",
            external_id="coakley11",
            workspace="coakley11",
            email="coakley11@aol.com",
            auth_uuid="auth-coakley-uuid",
        )
        with _as_user("user:coakley"), patch(
            "fantasy_shared_league_startup_sync.list_shared_league_documents",
            return_value=[shared_doc],
        ):
            memberships = discover_shared_league_memberships_for_session(coakley)
            self.assertTrue(memberships)
            self.assertIn("league:legacy-live", {m.get("league_id") for m in memberships})
            self.assertIn("Team 2", memberships[0].get("owned_teams") or [])

    def test_second_account_sees_library_after_create_from_room_participants(self) -> None:
        daniel = _auth_session(
            user_id="user:daniel",
            external_id="daniel",
            workspace="daniel",
            email="daniel@example.com",
            auth_uuid="auth-daniel-uuid",
        )
        room = _complete_two_team_room()
        room_doc = {
            "room_code": "ROOM99",
            "participants": {
                "auth-daniel-uuid": {
                    "assigned_team": "Team 1",
                    "display_name": "daniel@example.com",
                    "user_id": "user:daniel",
                    "account_user_id": "user:daniel",
                    "external_id": "daniel",
                    "email": "daniel@example.com",
                },
                "auth-coakley-uuid": {
                    "assigned_team": "Team 2",
                    "display_name": "coakley11@aol.com",
                    "user_id": "user:coakley",
                    "account_user_id": "user:coakley",
                    "external_id": "coakley11",
                    "email": "coakley11@aol.com",
                },
            },
        }
        with _as_user("user:daniel"), patch(
            "draft_room_shared_state.load_shared_room",
            return_value=room_doc,
        ):
            entry, context = save_live_draft_shared_league_context(
                daniel,
                room,
                my_team_name="Team 1",
                league_name="Visibility Live Draft",
                draft_name="Visibility Live Draft",
                defer_activation=True,
                assign_team=True,
            )
        league_id = str(context.get("league_id") or (context.get("metadata") or {}).get("league_id") or "")
        shared = load_shared_league(league_id)
        self.assertIsInstance(shared, dict)
        coakley = _auth_session(
            user_id="user:coakley",
            external_id="coakley11",
            workspace="coakley11",
            email="coakley11@aol.com",
            auth_uuid="auth-coakley-uuid",
        )
        with _as_user("user:coakley"), patch(
            "fantasy_shared_league_startup_sync.list_shared_league_documents",
            return_value=[shared],
        ), patch(
            "fantasy_shared_league_startup_sync.load_shared_league",
            return_value=shared,
        ), patch(
            "fantasy_admin_draft_archive_repair.load_shared_league",
            create=True,
            return_value=shared,
        ):
            materialize_owned_shared_leagues_for_session(coakley)
            visible = list_visible_draft_archives(coakley)
            self.assertGreaterEqual(len(visible), 1)
            self.assertEqual(draft_type_display(visible[0]), "Live Draft")
            self.assertNotEqual(str(entry.get("draft_type") or ""), DRAFT_TYPE_IMPORTED)

    def test_real_league_default_does_not_override_live_archive(self) -> None:
        draft_type, reason, _ = resolve_archive_draft_type_with_reason(
            context={"context_type": CONTEXT_TYPE_REAL_LEAGUE, "metadata": {}},
            archive_entry={"draft_type": DRAFT_TYPE_LIVE},
        )
        self.assertEqual(draft_type, DRAFT_TYPE_LIVE)
        self.assertEqual(reason, "existing_archive_live_draft_type")
        imported_type, imported_reason, _ = resolve_archive_draft_type_with_reason(
            context={"context_type": CONTEXT_TYPE_REAL_LEAGUE, "metadata": {"created_from": "imported_draft"}},
            archive_entry={"draft_type": DRAFT_TYPE_IMPORTED},
        )
        self.assertEqual(imported_type, DRAFT_TYPE_IMPORTED)
        self.assertIn(imported_reason, {"canonical_shared_import_origin", "real_league_default_import", "immutable_creation_origin_validated_import"})


if __name__ == "__main__":
    unittest.main()
