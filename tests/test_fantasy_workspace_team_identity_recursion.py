"""Regression tests for nonrecursive team identity resolution."""

from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from fantasy_workspace_team_identity import (
    _local_team_preference_allowed,
    _raw_live_draft_participant_team,
    _team_from_live_draft_participants,
    resolve_current_account_team_for_live_draft_and_league,
)


class TeamIdentityRecursionTests(unittest.TestCase):
    def test_bare_draft_room_participant_team_is_not_authoritative(self) -> None:
        session = {
            "draft_room_participant_team": "Donny",
            "live_draft_room": {"config": {}},
        }
        self.assertEqual(_raw_live_draft_participant_team(session, None), "")
        self.assertEqual(_team_from_live_draft_participants(session, None), "")

    def test_no_recursion_when_resolving_with_bare_alias(self) -> None:
        session = {
            "draft_room_participant_team": "Donny",
            "room_your_team": "Donny",
            "live_draft_room": {"config": {}},
        }
        team = resolve_current_account_team_for_live_draft_and_league(session)
        self.assertEqual(team, "")

    def test_participant_membership_resolves_team_b(self) -> None:
        session = {
            "draft_room_participant_id": "p1",
            "draft_room_participant_membership": {"p1": {"assigned_team": "Team B"}},
            "live_draft_room": {"config": {}},
        }
        self.assertEqual(_raw_live_draft_participant_team(session, None), "Team B")
        self.assertEqual(resolve_current_account_team_for_live_draft_and_league(session), "Team B")

    def test_shared_ownership_resolves_donny(self) -> None:
        session = {
            "_suite_auth_user_id": "user:daniel",
            "_suite_auth_external_id": "daniel",
            "room_your_team": "Team B",
            "draft_room_participant_team": "Team B",
        }
        context = {
            "my_team_name": "Team B",
            "metadata": {"league_id": "league:robins"},
            "league_rosters": {"Donny": {}, "Team B": {}},
        }
        shared = {
            "league_id": "league:robins",
            "team_ownership": {
                "Donny": {"user_id": "user:daniel", "external_id": "daniel"},
                "Team B": {"user_id": "user:coakley11"},
            },
        }
        with patch(
            "fantasy_workspace_team_identity._load_shared_doc_for_context",
            return_value=shared,
        ):
            team = resolve_current_account_team_for_live_draft_and_league(session, context=context, shared_doc=shared)
        self.assertEqual(team, "Donny")

    def test_local_preference_never_calls_participant_resolver(self) -> None:
        source = inspect.getsource(_local_team_preference_allowed)
        self.assertNotIn("_team_from_live_draft_participants", source)

    def test_participant_resolver_never_calls_local_preference(self) -> None:
        source = inspect.getsource(_raw_live_draft_participant_team)
        self.assertNotIn("_local_team_preference_allowed", source)

    def test_local_preference_uses_participant_team_argument(self) -> None:
        session = {"_suite_auth_user_id": "user:x"}
        allowed = _local_team_preference_allowed(
            session,
            "Team B",
            shared_doc=None,
            context=None,
            participant_team="Team B",
        )
        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
