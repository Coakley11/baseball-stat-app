"""Fantasy page identity must follow shared-league ownership, never archive Team 1/2."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fantasy_league_context import ensure_fantasy_league_context_state, upsert_league_context
from fantasy_league_team_ownership import resolve_account_fantasy_team
from global_fantasy_settings_state import get_active_fantasy_team


def _shared_xy_context(*, local_my_team: str = "Team 2") -> dict:
    return {
        "context_type": "real_league",
        "league_context_id": "ctx:xy",
        "my_team_name": local_my_team,
        "display_name": "Shared XY League",
        "metadata": {"league_id": "league:xy"},
        "team_ownership": {
            "Team X": {
                "user_id": "user:daniel",
                "display_name": "Daniel",
                "claim_status": "claimed",
            },
            "Team Y": {
                "user_id": "user:coakley11",
                "display_name": "coakley11",
                "claim_status": "claimed",
            },
        },
        "league_rosters": {
            "Team X": {"players": []},
            "Team Y": {"players": []},
        },
        "workflow": {},
    }


def _base_session(context: dict, *, uid: str, external: str, workspace: str) -> dict:
    session: dict = {
        "_suite_auth_user_id": uid,
        "_suite_auth_external_id": external,
        "_suite_owned_workspace_id": workspace,
        "_suite_active_workspace_id": workspace,
        "active_draft_archive_id": "xy",
        "room_your_team": "Team 2",
        "lineup_team": "Team 2",
        "live_draft_my_team": "Team 2",
        "draft_archive_teams": [
            {
                "draft_id": "xy",
                "draft_name": "Shared XY League",
                "team_name": "Team 2",
                "league_context_id": "ctx:xy",
            }
        ],
    }
    ensure_fantasy_league_context_state(session)
    upsert_league_context(session, context)
    store = ensure_fantasy_league_context_state(session)
    store["active_league_context_id"] = "ctx:xy"
    return session


class SharedLeagueIdentityConsistencyTests(unittest.TestCase):
    def test_daniel_resolves_team_x_not_archive_team_2(self) -> None:
        context = _shared_xy_context(local_my_team="Team 2")
        session = _base_session(context, uid="user:daniel", external="daniel", workspace="daniel")
        with (
            patch(
                "fantasy_shared_league_store.sync_context_with_shared_store",
                side_effect=lambda _s, ctx, **_k: ctx,
            ),
            patch(
                "fantasy_league_team_ownership.upsert_league_context",
                side_effect=lambda _s, ctx, **_k: ctx,
            ),
            patch(
                "global_fantasy_settings_state.active_fantasy_team_source",
                return_value="active_draft",
            ),
            patch("draft_room_context.is_multiplayer_draft_active", return_value=False),
        ):
            self.assertEqual(resolve_account_fantasy_team(session, context), "Team X")
            self.assertEqual(get_active_fantasy_team(session), "Team X")

    def test_coakley_resolves_team_y_not_team_x_or_team_2(self) -> None:
        context = _shared_xy_context(local_my_team="Team X")
        session = _base_session(
            context, uid="user:coakley11", external="coakley11", workspace="coakley11"
        )
        with (
            patch(
                "fantasy_shared_league_store.sync_context_with_shared_store",
                side_effect=lambda _s, ctx, **_k: ctx,
            ),
            patch(
                "fantasy_league_team_ownership.upsert_league_context",
                side_effect=lambda _s, ctx, **_k: ctx,
            ),
            patch(
                "global_fantasy_settings_state.active_fantasy_team_source",
                return_value="active_draft",
            ),
            patch("draft_room_context.is_multiplayer_draft_active", return_value=False),
        ):
            self.assertEqual(resolve_account_fantasy_team(session, context), "Team Y")
            self.assertEqual(get_active_fantasy_team(session), "Team Y")

    def test_no_archive_fallback_when_shared_claims_exist(self) -> None:
        from fantasy_league_team_ownership import ownership_blocks_archive_team_fallback

        self.assertTrue(ownership_blocks_archive_team_fallback(_shared_xy_context()))


if __name__ == "__main__":
    unittest.main()
