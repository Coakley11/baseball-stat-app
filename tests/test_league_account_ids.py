"""Shared League authorization with the hosted app's two account ids (2026-11-02).

In the hosted app the sign-in (Auth) user id and the suite account id differ: rooms and
participant keys use the Auth id, league records (commissioner_user_id, team_ownership user_id,
invitee_user_id) store the suite account id. The security release compared league records with the
Auth id only, so a real commissioner was not recognised as commissioner (their rename was reverted).
A stored id now matches when it equals either of the session's OWN ids; nothing else is added.
"""

from __future__ import annotations

import unittest
from unittest import mock

import fantasy_shared_league_authz as authz

DANNY = {"_suite_auth_session": True, "_suite_auth_user_id": "auth-danny", "_suite_cloud_user_id": "suite-danny",
         "_suite_auth_external_id": "danny", "_suite_owned_workspace_id": "danny"}
BARRY = {"_suite_auth_session": True, "_suite_auth_user_id": "auth-barry", "_suite_cloud_user_id": "suite-barry",
         "_suite_auth_external_id": "barry", "_suite_owned_workspace_id": "barry"}
MALLORY = {"_suite_auth_session": True, "_suite_auth_user_id": "auth-mallory", "_suite_cloud_user_id": "suite-mallory",
           "_suite_auth_external_id": "mallory", "_suite_owned_workspace_id": "mallory"}
LEAGUE = {
    "league_id": "league:dvb",
    "league_name": "My Fantasy League",
    "draft_id": "d1",
    "commissioner_user_id": "suite-danny",
    "team_ownership": {
        "Danny": {"user_id": "suite-danny", "email": "danny@example.com", "external_id": "danny"},
        "Barry": {"user_id": "suite-barry"},  # an older record holding only the suite account id
    },
    "league_invites": [],
}


class AccountIdTests(unittest.TestCase):
    def setUp(self) -> None:
        p = mock.patch("suite_auth.current_auth_email", return_value="")
        p.start()
        self.addCleanup(p.stop)

    def test_the_commissioner_is_recognised_and_may_rename(self) -> None:
        self.assertTrue(authz.is_league_commissioner(DANNY, LEAGUE))
        out = authz.authorize_league_write(DANNY, {**LEAGUE, "league_name": "Renamed"}, LEAGUE)
        self.assertEqual(out["league_name"], "Renamed")

    def test_a_member_recorded_only_by_suite_id_is_a_member_not_commissioner(self) -> None:
        self.assertTrue(authz.is_league_member_or_invitee(BARRY, LEAGUE))
        self.assertFalse(authz.is_league_commissioner(BARRY, LEAGUE))
        out = authz.authorize_league_write(BARRY, {**LEAGUE, "league_name": "Barry's now"}, LEAGUE)
        self.assertEqual(out["league_name"], "My Fantasy League")  # commissioner-only field kept

    def test_an_unrelated_account_is_still_refused(self) -> None:
        self.assertFalse(authz.is_league_commissioner(MALLORY, LEAGUE))
        self.assertFalse(authz.is_league_member_or_invitee(MALLORY, LEAGUE))
        with self.assertRaises(authz.SharedLeagueWriteRefused):
            authz.authorize_league_write(MALLORY, dict(LEAGUE), LEAGUE)

    def test_no_fallback_account_is_ever_used(self) -> None:
        # A session with no ids of its own does not match, even when the deployment's configured
        # account (get_account_user_id) happens to equal the stored commissioner.
        with mock.patch("suite_user.get_account_user_id", return_value="suite-danny"):
            self.assertFalse(authz.is_league_commissioner({"_suite_auth_session": True}, LEAGUE))
            self.assertFalse(authz.is_league_member_or_invitee({"_suite_auth_session": True}, LEAGUE))

    def test_auth_id_only_records_still_match(self) -> None:
        league = {**LEAGUE, "commissioner_user_id": "auth-danny"}
        self.assertTrue(authz.is_league_commissioner(DANNY, league))


if __name__ == "__main__":
    unittest.main()
