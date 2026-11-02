"""Legitimate members still trade with sign-in on (the hosted configuration); an unrelated account
holding a copy cannot, and the shared league is unchanged by its attempt (security review 2026-11-02).

The existing trade suites run with sign-in off, where no account is hidden from any league.
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fantasy_shared_league_authz as authz
from fantasy_league_context import get_active_league_context
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_shared_league_store import (
    LocalFileSharedLeagueStore,
    load_shared_league,
    push_league_context_to_shared,
    set_shared_league_store,
)
from fantasy_trade_proposals import TRADE_PROPOSAL_STATUS_ACCEPTED, accept_trade_proposal, create_trade_proposal
from tests.test_fantasy_trade_proposals import _as_user, _seed_league


def _signed_in(session: dict, uid: str) -> dict:
    session["_suite_auth_session"] = True
    session["_suite_auth_user_id"] = uid
    session["_suite_cloud_user_id"] = uid
    session["_suite_auth_external_id"] = uid.split(":", 1)[-1]
    return session


class MemberTradesWithSignInOnTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmp.name)))
        for p in (
            patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}),
            patch("fantasy_shared_league_store._anonymous_guest", return_value=False),
        ):
            p.start()
            self.addCleanup(p.stop)
        authz.clear_league_copy_decisions()
        self.session = _signed_in({}, "user:donny")
        with _as_user("user:donny"):
            context = _seed_league(self.session)
            push_league_context_to_shared(self.session, context)
        self.league_id = resolve_canonical_league_id(context)
        self.assertIsInstance(load_shared_league(self.league_id), dict)

    def tearDown(self) -> None:
        set_shared_league_store(None)
        self._tmp.cleanup()
        authz.clear_league_copy_decisions()

    def _propose(self, session: dict, uid: str):
        with _as_user(uid):
            return create_trade_proposal(
                session,
                proposer_team="Donny",
                recipient_team="Team 2",
                proposer_gives=["Player A"],
                proposer_receives=["Player B"],
                verdict="Good for your team",
            )

    def test_owner_proposes_and_the_other_owner_accepts(self) -> None:
        self.assertIsNotNone(get_active_league_context(self.session))
        proposal, err = self._propose(self.session, "user:donny")
        self.assertEqual(err, "")
        _signed_in(self.session, "user:seal11")
        authz.clear_league_copy_decisions()
        with _as_user("user:seal11"):
            accepted, err = accept_trade_proposal(self.session, str(proposal["proposal_id"]))
        self.assertEqual(err, "")
        self.assertEqual(accepted["status"], TRADE_PROPOSAL_STATUS_ACCEPTED)

    def test_unrelated_account_with_a_copy_cannot_trade_and_changes_nothing(self) -> None:
        stored_before = copy.deepcopy(load_shared_league(self.league_id))
        intruder = _signed_in(copy.deepcopy(dict(self.session)), "user:mallory")
        authz.clear_league_copy_decisions()
        self.assertIsNone(get_active_league_context(intruder))
        proposal, err = self._propose(intruder, "user:mallory")
        self.assertIsNone(proposal)
        self.assertTrue(err)
        from fantasy_shared_league_store import invalidate_shared_league_doc_cache

        invalidate_shared_league_doc_cache()
        self.assertEqual(load_shared_league(self.league_id), stored_before)


if __name__ == "__main__":
    unittest.main()
