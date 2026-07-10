"""Tests for canonical per-workspace team identity resolution."""

from __future__ import annotations

import unittest

from fantasy_workspace_team_identity import (
    build_account_aliases,
    owned_team_from_ownership,
    owned_team_from_shared_doc,
    overlay_workspace_team_on_context,
    resolve_archive_display_team,
)


class TestFantasyWorkspaceTeamIdentity(unittest.TestCase):
    def test_email_alias_resolves_daniel_team(self) -> None:
        session = {
            "_suite_auth_user_id": "supabase-uuid-daniel",
            "_suite_auth_external_id": "daniel",
            "_suite_owned_workspace_id": "daniel",
            "_suite_auth_user_email": "daniel.cohen11@yahoo.com",
        }
        ownership = {
            "Daniel": {
                "user_id": "supabase-uuid-daniel",
                "email": "daniel.cohen11@yahoo.com",
                "display_name": "daniel",
            },
            "Team 2": {
                "user_id": "supabase-uuid-coakley",
                "email": "coakley11@yahoo.com",
                "display_name": "coakley11",
            },
        }
        aliases = build_account_aliases(session)
        self.assertIn("daniel.cohen11@yahoo.com", aliases)
        self.assertIn("daniel.cohen11", aliases)
        self.assertEqual(
            owned_team_from_ownership(ownership, owner_user_id="supabase-uuid-daniel", aliases=aliases),
            "Daniel",
        )

    def test_stale_archive_team_name_does_not_override_ownership(self) -> None:
        session = {
            "_suite_auth_user_id": "user:daniel",
            "_suite_auth_external_id": "daniel",
            "_suite_owned_workspace_id": "daniel",
        }
        shared_doc = {
            "league_id": "league:test",
            "team_ownership": {
                "Daniel": {"user_id": "user:daniel", "email": "daniel.cohen11@yahoo.com"},
                "Team 2": {"user_id": "user:coakley11"},
            },
        }
        context = {
            "context_type": "real_league",
            "my_team_name": "Team 2",
            "metadata": {"league_id": "league:test"},
            "league_rosters": {"Daniel": {}, "Team 2": {}},
        }
        archive = {"draft_id": "abc123", "team_name": "Team 2", "draft_name": "UPLOAD TEST DEMO"}
        overlaid = overlay_workspace_team_on_context(session, context, shared_doc=shared_doc)
        assert overlaid is not None
        self.assertEqual(overlaid.get("my_team_name"), "Daniel")
        self.assertEqual(resolve_archive_display_team(session, archive, overlaid), "Daniel")
        self.assertEqual(owned_team_from_shared_doc(shared_doc, session), "Daniel")


if __name__ == "__main__":
    unittest.main()
