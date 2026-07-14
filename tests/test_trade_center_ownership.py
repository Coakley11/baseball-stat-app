"""Trade Center must use shared-league ownership, not stale local/cached team."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fantasy_league_team_ownership import resolve_trade_team_for_session
from fantasy_trade_center_ui import _resolve_trade_scope
from fantasy_trade_proposals import get_incoming_trade_proposals, get_outgoing_trade_proposals


def _team_y_session() -> dict:
    return {
        "_suite_auth_user_id": "user:coakley11",
        "_suite_auth_external_id": "coakley11",
        "_suite_owned_workspace_id": "coakley11",
        "_suite_active_workspace_id": "coakley11",
        "_suite_auth_user_email": "coakley11@aol.com",
        "lineup_team": "Team X",
        "room_your_team": "Team X",
    }


def _shared_context_stale_local_team_x() -> dict:
    """Local cache says Team X; firm ownership says this account owns Team Y."""
    return {
        "context_type": "real_league",
        "league_context_id": "ctx:trade-own",
        "my_team_name": "Team X",
        "metadata": {"league_id": "league:trade-own"},
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
            "Team X": {"players": [{"player_name": "A", "player_key": "a"}]},
            "Team Y": {"players": [{"player_name": "B", "player_key": "b"}]},
        },
        "workflow": {
            "trade_proposals": [
                {
                    "proposal_id": "p1",
                    "status": "pending",
                    "proposer_team": "Team X",
                    "recipient_team": "Team Y",
                    "proposer_gives": [{"player_name": "A"}],
                    "proposer_receives": [{"player_name": "B"}],
                }
            ]
        },
    }


class TradeCenterOwnershipTests(unittest.TestCase):
    def test_resolve_trade_team_ignores_stale_my_team_name(self) -> None:
        session = _team_y_session()
        context = _shared_context_stale_local_team_x()
        with (
            patch(
                "fantasy_shared_league_store.sync_context_with_shared_store",
                side_effect=lambda _s, ctx, **_k: ctx,
            ),
            patch(
                "fantasy_league_team_ownership.upsert_league_context",
                side_effect=lambda _s, ctx, **_k: ctx,
            ),
        ):
            self.assertEqual(resolve_trade_team_for_session(context, session), "Team Y")

    def test_trade_scope_ignores_page_lineup_team_x(self) -> None:
        session = _team_y_session()
        context = _shared_context_stale_local_team_x()

        def _fake_get_active(_session, **_kwargs):
            return context

        with (
            patch(
                "fantasy_league_context.get_active_league_context",
                side_effect=_fake_get_active,
            ),
            patch(
                "fantasy_shared_league_store.sync_context_with_shared_store",
                side_effect=lambda _s, ctx, **_k: ctx,
            ),
            patch(
                "fantasy_league_team_ownership.upsert_league_context",
                side_effect=lambda _s, ctx, **_k: ctx,
            ),
        ):
            scope = _resolve_trade_scope(session, page_lineup_team="Team X")
        self.assertEqual(scope["my_team"], "Team Y")

    def test_team_y_sees_team_x_offer_as_incoming_not_outgoing(self) -> None:
        session = _team_y_session()
        context = _shared_context_stale_local_team_x()

        with (
            patch(
                "fantasy_trade_proposals.get_active_league_context",
                return_value=context,
            ),
            patch(
                "fantasy_shared_league_store.sync_context_with_shared_store",
                side_effect=lambda _s, ctx, **_k: ctx,
            ),
            patch(
                "fantasy_league_team_ownership.upsert_league_context",
                side_effect=lambda _s, ctx, **_k: ctx,
            ),
        ):
            my_team = resolve_trade_team_for_session(context, session)
            self.assertEqual(my_team, "Team Y")
            incoming = get_incoming_trade_proposals(session, my_team)
            outgoing = get_outgoing_trade_proposals(session, my_team)
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0]["proposal_id"], "p1")
        self.assertEqual(outgoing, [])

    def test_does_not_fall_back_to_local_team_when_other_claims_exist(self) -> None:
        session = {
            "_suite_auth_user_id": "user:unclaimed",
            "_suite_auth_external_id": "unclaimed",
            "_suite_owned_workspace_id": "unclaimed",
            "_suite_active_workspace_id": "unclaimed",
        }
        context = _shared_context_stale_local_team_x()
        context["my_team_name"] = "Team X"
        with patch(
            "fantasy_shared_league_store.sync_context_with_shared_store",
            side_effect=lambda _s, ctx, **_k: ctx,
        ):
            self.assertEqual(resolve_trade_team_for_session(context, session), "")


if __name__ == "__main__":
    unittest.main()
