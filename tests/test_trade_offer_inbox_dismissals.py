"""Durable per-user Trade Center offer inbox dismissals."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state
from fantasy_league_context import FANTASY_LEAGUE_CONTEXT_STATE_KEY, get_active_league_context
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from fantasy_trade_proposals import (
    TRADE_PROPOSAL_STATUS_ACCEPTED,
    accept_trade_proposal,
    archived_offer_ids,
    archive_offer_from_inbox,
    create_trade_proposal,
    get_incoming_trade_proposals,
    get_trade_history,
    get_trade_proposal,
    is_offer_archived,
)
from tests.test_fantasy_trade_proposals import _as_user, _seed_league


def _st(session: dict) -> object:
    return type("_St", (), {"session_state": session})()


class TradeOfferInboxDismissalTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmp.name)))

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmp.cleanup()

    def _accept_incoming_for_donny(self, session: dict) -> str:
        ctx = _seed_league(session)
        session["_suite_auth_user_id"] = "user:donny"
        session["_suite_active_workspace_id"] = "daniel"
        with _as_user("user:seal11"):
            proposal, err = create_trade_proposal(
                session,
                proposer_team="Team 2",
                recipient_team="Donny",
                proposer_gives=["Player B"],
                proposer_receives=["Player A"],
            )
        self.assertFalse(err)
        assert proposal is not None
        pid = str(proposal.get("proposal_id") or "")
        with _as_user("user:donny"):
            accepted, accept_err = accept_trade_proposal(session, pid)
        self.assertFalse(accept_err, accept_err)
        self.assertIsNotNone(accepted)
        self.assertEqual(accepted.get("status"), TRADE_PROPOSAL_STATUS_ACCEPTED)
        league_id = str(ctx.get("league_id") or "")
        return pid if league_id else pid

    def test_clear_accepted_incoming_offer(self) -> None:
        session: dict = {}
        pid = self._accept_incoming_for_donny(session)
        ctx = get_active_league_context(session)
        assert ctx is not None
        league_id = str(ctx.get("league_id") or "")
        archive_offer_from_inbox(session, pid, league_id=league_id)
        self.assertIn(pid, archived_offer_ids(session, league_id))
        incoming = get_incoming_trade_proposals(session, "Donny")
        self.assertTrue(any(str(p.get("proposal_id") or "") == pid for p in incoming))
        self.assertTrue(is_offer_archived(session, pid, league_id=league_id))

    def test_dismissal_survives_refresh(self) -> None:
        session: dict = {}
        pid = self._accept_incoming_for_donny(session)
        ctx = get_active_league_context(session)
        assert ctx is not None
        league_id = str(ctx.get("league_id") or "")
        archive_offer_from_inbox(session, pid, league_id=league_id)
        blob = build_baseball_disk_state(_st(session))
        refreshed: dict = {
            FANTASY_LEAGUE_CONTEXT_STATE_KEY: session.get(FANTASY_LEAGUE_CONTEXT_STATE_KEY),
            "_suite_auth_user_id": "user:donny",
            "_suite_active_workspace_id": "daniel",
        }
        apply_baseball_disk_state(_st(refreshed), blob)
        self.assertIn(pid, archived_offer_ids(refreshed, league_id))

    def test_dismissal_survives_sign_out_in_simulation(self) -> None:
        session: dict = {}
        pid = self._accept_incoming_for_donny(session)
        ctx = get_active_league_context(session)
        assert ctx is not None
        league_id = str(ctx.get("league_id") or "")
        archive_offer_from_inbox(session, pid, league_id=league_id)
        blob = build_baseball_disk_state(_st(session))
        signed_in: dict = {
            FANTASY_LEAGUE_CONTEXT_STATE_KEY: session.get(FANTASY_LEAGUE_CONTEXT_STATE_KEY),
            "_suite_auth_user_id": "user:donny",
            "_suite_active_workspace_id": "daniel",
        }
        apply_baseball_disk_state(_st(signed_in), blob)
        self.assertIn(pid, archived_offer_ids(signed_in, league_id))

    def test_other_participant_dismissal_is_independent(self) -> None:
        session: dict = {}
        pid = self._accept_incoming_for_donny(session)
        ctx = get_active_league_context(session)
        assert ctx is not None
        league_id = str(ctx.get("league_id") or "")

        archive_offer_from_inbox(session, pid, league_id=league_id)

        team2_session: dict = {
            FANTASY_LEAGUE_CONTEXT_STATE_KEY: session.get(FANTASY_LEAGUE_CONTEXT_STATE_KEY),
            "_suite_auth_user_id": "user:seal11",
            "_suite_active_workspace_id": "coakley11",
        }
        self.assertNotIn(pid, archived_offer_ids(team2_session, league_id))
        archive_offer_from_inbox(team2_session, pid, league_id=league_id)
        self.assertIn(pid, archived_offer_ids(team2_session, league_id))
        self.assertIn(pid, archived_offer_ids(session, league_id))

    def test_history_still_shows_cleared_transaction(self) -> None:
        session: dict = {}
        pid = self._accept_incoming_for_donny(session)
        ctx = get_active_league_context(session)
        assert ctx is not None
        league_id = str(ctx.get("league_id") or "")
        archive_offer_from_inbox(session, pid, league_id=league_id)
        proposal = get_trade_proposal(ctx, pid)
        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertEqual(str(proposal.get("status") or ""), TRADE_PROPOSAL_STATUS_ACCEPTED)
        history = get_trade_history(ctx)
        accepted = history.get("accepted") or []
        self.assertTrue(any(str(p.get("proposal_id") or "") == pid for p in accepted))

    def test_accepted_trade_appears_once_in_history(self) -> None:
        session: dict = {}
        pid = self._accept_incoming_for_donny(session)
        ctx = get_active_league_context(session)
        assert ctx is not None
        history = get_trade_history(ctx)
        accepted_rows = [
            row for row in (history.get("accepted") or []) if str(row.get("proposal_id") or "") == pid
        ]
        self.assertEqual(len(accepted_rows), 1)


if __name__ == "__main__":
    unittest.main()
