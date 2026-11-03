"""Invite inbox, accept and decline with sign-in on (security review, 2026-11-02).

_invite_matches_user accepts the "daniel" fallback workspace and helper-resolved ids. Without a
second check, a signed-in account whose workspace fell back to "daniel" saw invites addressed to
that workspace (league name, inviter) and, on accept, had the league's full rosters copied into its
own workspace, although the server refused the league write. The flows now also require the strict
member/invitee check against the stored league.
"""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import fantasy_shared_league_authz as authz
from draft_archive_state import list_draft_archives
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_league_invites import (
    INVITE_STATUS_PENDING,
    _invite_matches_user,
    create_league_invite,
    decline_league_invite,
    join_shared_league_from_invite,
    list_pending_invites_for_session,
)
from fantasy_shared_league_store import invalidate_shared_league_doc_cache, load_shared_league, save_shared_league
import tests.test_fantasy_league_invites as _invite_suite  # module import: its tests are not re-collected here
from tests.test_fantasy_trade_proposals import _as_user


def _signed_in(uid: str, external: str, workspace: str) -> dict:
    return {
        "_suite_auth_session": True,
        "_suite_auth_user_id": uid,
        "_suite_cloud_user_id": uid,
        "_suite_auth_external_id": external,
        "_suite_owned_workspace_id": workspace,
        "_suite_active_workspace_id": workspace,
    }


class InviteFlowsStrictTests(unittest.TestCase):
    setUp = _invite_suite.TestFantasyLeagueInvites.setUp
    tearDown = _invite_suite.TestFantasyLeagueInvites.tearDown
    _write_registry = _invite_suite.TestFantasyLeagueInvites._write_registry
    _workspace = _invite_suite.TestFantasyLeagueInvites._workspace

    def _league(self) -> tuple[dict, str]:
        self._write_registry(
            {
                "by_owner": {
                    "user:donny": {"owner_user_id": "user:donny", "owner_external_id": "donny", "workspace_id": "donny_ws"},
                    "user:seal11": {"owner_user_id": "user:seal11", "owner_external_id": "seal11", "workspace_id": "ariel"},
                }
            }
        )
        owner = {}
        context = _invite_suite._seed_imported_league(owner, user_id="user:donny", workspace="donny_ws")
        league_id = resolve_canonical_league_id(context)
        return context, league_id

    def _on(self):
        """Sign-in on. A unit test has no Streamlit session, which the existing guest check
        reads as signed out; these accounts are signed in."""
        from contextlib import ExitStack

        authz.clear_league_copy_decisions()
        stack = ExitStack()
        stack.enter_context(patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}))
        stack.enter_context(patch("fantasy_shared_league_store._anonymous_guest", return_value=False))
        return stack

    def test_a_real_invitee_still_sees_and_accepts(self) -> None:
        context, league_id = self._league()
        with _as_user("user:donny"):
            invite, err = create_league_invite({}, context, invitee_target="ariel")
        self.assertEqual(err, "")
        session = _signed_in("user:seal11", "seal11", "ariel")
        with self._on(), _as_user("user:seal11"), self._workspace("ariel"):
            self.assertEqual(len(list_pending_invites_for_session(session)), 1)
            entry, _ctx, err = join_shared_league_from_invite(
                session, league_id=league_id, invite_id=str(invite["invite_id"]), team_name="Team 2"
            )
        self.assertEqual(err, "")
        self.assertIsNotNone(entry)

    def _daniel_workspace_invite(self, league_id: str) -> str:
        shared = load_shared_league(league_id)
        shared["league_invites"] = list(shared.get("league_invites") or []) + [
            {"invite_id": "inv_fallback", "league_id": league_id, "status": INVITE_STATUS_PENDING,
             "invitee_workspace_id": "daniel", "league_name": "Private League"}
        ]
        save_shared_league(shared)
        invalidate_shared_league_doc_cache()
        return "inv_fallback"

    def test_a_daniel_fallback_account_sees_reads_and_changes_nothing(self) -> None:
        _context, league_id = self._league()
        invite_id = self._daniel_workspace_invite(league_id)
        stored_before = copy.deepcopy(load_shared_league(league_id))
        mallory = _signed_in("user:mallory", "mallory", "daniel")  # workspace fell back to "daniel"
        invite = next(i for i in stored_before["league_invites"] if i["invite_id"] == invite_id)
        # The tolerant matcher alone would let this account in:
        self.assertTrue(_invite_matches_user(invite, user_id="user:mallory", external_id="mallory", workspace_id="daniel"))
        with self._on(), _as_user("user:mallory"), self._workspace("daniel"):
            self.assertEqual(list_pending_invites_for_session(mallory), [])
            entry, ctx, err = join_shared_league_from_invite(
                mallory, league_id=league_id, invite_id=invite_id, team_name="Team 2"
            )
            ok, decline_err = decline_league_invite(mallory, league_id=league_id, invite_id=invite_id)
        self.assertIsNone(entry)
        self.assertIsNone(ctx)
        self.assertIn("different account", err)
        self.assertFalse(ok)
        self.assertIn("different account", decline_err)
        self.assertEqual(list_draft_archives(mallory), [])  # no copy of the league's rosters
        invalidate_shared_league_doc_cache()
        self.assertEqual(load_shared_league(league_id), stored_before)


if __name__ == "__main__":
    unittest.main()
