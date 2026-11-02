"""The security release changes no stored workspace data (owner rule, 2026-11-02).

With the strict membership matcher, the Saved Draft Library prune deleted (with tombstones) the
league copies a non-member already held, and the team overlay cleared their team, on that
account's next sign-in or Library visit. That is the clean-up the owner decides after the
exposure audit, so until then those paths keep the deployed behaviour. New copies, discovery and
every Shared League write still use the strict matcher.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from draft_archive_state import list_draft_archives
from draft_archive_visibility import prune_invisible_shared_league_state, sanitize_workflow_blob_for_account
from fantasy_league_context import list_league_contexts
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_shared_league_startup_sync import discover_shared_league_memberships_for_session
from fantasy_workspace_team_identity import _claimed_team_from_accepted_invite
from tests.test_draft_archive_visibility import _as_user, _auth_session, _seed_daniel_shared_league


def _exposed_copy():
    owner = _auth_session(user_id="user:daniel", external_id="daniel", workspace="daniel")
    _seed_daniel_shared_league(owner)
    league_id = resolve_canonical_league_id(list_league_contexts(owner)[0])
    shared = {
        "league_id": league_id,
        "commissioner_user_id": "user:daniel",
        "team_ownership": {"Donny": {"user_id": "user:daniel"}},
        "league_invites": [
            {"invite_id": "i1", "status": "accepted", "invitee_user_id": "user:barry",
             "invitee_username": "barry", "claimed_team": "Barry Team"}
        ],
    }
    other = _auth_session(user_id="user:coakley", external_id="coakley11", workspace="coakley11")
    other["draft_archive_teams"] = list(owner.get("draft_archive_teams") or [])
    other["fantasy_league_context_state"] = dict(owner.get("fantasy_league_context_state") or {})
    return other, shared


class ExistingCopiesArePreservedTests(unittest.TestCase):
    def test_prune_keeps_a_non_members_existing_copy_as_deployed(self) -> None:
        other, shared = _exposed_copy()
        before = len(list_draft_archives(other))
        with _as_user("user:coakley"), patch("fantasy_shared_league_store.load_shared_league", return_value=shared):
            removed = prune_invisible_shared_league_state(other)
        self.assertEqual(removed, {"archives_removed": 0, "contexts_removed": 0})
        self.assertEqual(len(list_draft_archives(other)), before)
        self.assertFalse(other.get("_deleted_draft_archive_ids"))

    def test_sanitized_blob_keeps_the_copy(self) -> None:
        other, shared = _exposed_copy()
        blob = {k: other[k] for k in ("draft_archive_teams", "fantasy_league_context_state")}
        with _as_user("user:coakley"), patch("fantasy_shared_league_store.load_shared_league", return_value=shared):
            out = sanitize_workflow_blob_for_account(other, blob)
        self.assertEqual(len(out["draft_archive_teams"]), len(blob["draft_archive_teams"]))

    def test_team_overlay_resolves_the_same_team_as_deployed(self) -> None:
        other, shared = _exposed_copy()
        self.assertEqual(_claimed_team_from_accepted_invite(other, shared), "Barry Team")  # unchanged, wrong as before

    def test_but_the_non_member_still_gets_no_new_copy_and_cannot_write(self) -> None:
        import fantasy_shared_league_authz as authz

        other, shared = _exposed_copy()
        with patch("fantasy_shared_league_startup_sync.list_shared_league_documents", return_value=[shared]):
            self.assertEqual(discover_shared_league_memberships_for_session(other), [])
        self.assertFalse(authz.is_league_member_or_invitee(other, shared))
        with self.assertRaises(authz.SharedLeagueWriteRefused):
            authz.authorize_league_write(other, dict(shared), shared)


if __name__ == "__main__":
    unittest.main()
