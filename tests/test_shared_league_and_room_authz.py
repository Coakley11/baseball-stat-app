"""Authorization for Shared Leagues and the live-room controls (security review, 2026-11-02).

1. Every signed-in account was treated as a member of every Shared League: the matcher put the
   session's own identifiers (and the record's email) on both sides of the comparison.
2. Shared League writes had no authorization: any account holding a copy could push its local
   rosters, settings and commissioner over the shared league.
3. Resume and Auto Pick Now relied on disabled= only, which the server does not enforce.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import fantasy_shared_league_authz as authz
from fantasy_shared_league_startup_sync import _record_matches_account, discover_shared_league_memberships_for_session

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "control_center_forged_click_app.py"

OWNER = {"user_id": "uuid-owner", "email": "owner@example.com", "display_name": "owner@example.com", "team": "Team 1"}
LEAGUE = {
    "league_id": "league:abc",
    "league_name": "Owner League",
    "draft_id": "draft-1",
    "commissioner_user_id": "uuid-owner",
    "revision": 3,
    "team_ownership": {"Team 1": OWNER, "Team 2": {"user_id": "uuid-member", "email": "member@example.com"}},
    "league_invites": [{"invite_id": "i1", "status": "pending", "invitee_user_id": "uuid-invitee", "invitee_username": "invitee"}],
    "league_rosters": {"Team 1": {"players": []}},
}


def _session(uid: str, external: str = "", workspace: str = "") -> dict:
    """A verified sign-in (2026-11-05: Shared League authority needs sign-in enabled and a signed-in
    session; an id alone, or sign-in off, is never an account)."""
    return {
        "_suite_auth_session": bool(uid),
        "_suite_auth_user_id": uid,
        "_suite_auth_external_id": external,
        "_suite_owned_workspace_id": workspace,
    }


class _SignInOn(unittest.TestCase):
    def setUp(self) -> None:
        env = patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"})
        env.start()
        self.addCleanup(env.stop)
        authz.clear_league_copy_decisions()


class MembershipMatcherTests(_SignInOn):
    def test_unrelated_account_matches_nothing(self) -> None:
        for record in (OWNER, *LEAGUE["league_invites"]):
            self.assertFalse(_record_matches_account(record, user_id="uuid-attacker", external_id="attacker", workspace_id="attacker_ws"))

    def test_a_record_never_matches_itself_through_its_own_email(self) -> None:
        self.assertFalse(_record_matches_account(OWNER, user_id="uuid-attacker", external_id="", workspace_id=""))

    def test_shared_workspace_ids_are_not_identity(self) -> None:
        record = {"invitee_workspace_id": "guest", "accepted_by_workspace_id": "default"}
        self.assertFalse(_record_matches_account(record, user_id="", external_id="guest", workspace_id="default"))

    def test_real_members_still_match(self) -> None:
        self.assertTrue(_record_matches_account(OWNER, user_id="uuid-owner", external_id="", workspace_id=""))
        legacy = {"user_id": "auth-uuid", "display_name": "coakley11@aol.com"}  # Auth UUID + email only
        self.assertTrue(
            _record_matches_account(legacy, user_id="user:coakley", external_id="coakley11", workspace_id="", email="coakley11@aol.com")
        )
        invite = {"invitee_user_id": "", "invitee_username": "barry"}
        self.assertTrue(_record_matches_account(invite, user_id="uuid-b", external_id="barry", workspace_id=""))

    def test_a_matching_email_local_part_at_another_domain_is_not_identity(self) -> None:
        record = {"display_name": "victim@gmail.com", "email": "victim@gmail.com"}
        self.assertFalse(
            _record_matches_account(record, user_id="uuid-x", external_id="victim", workspace_id="victim", email="victim@yahoo.com")
        )
        self.assertTrue(_record_matches_account(record, user_id="uuid-x", external_id="", workspace_id="", email="victim@gmail.com"))

    def test_the_fallback_daniel_workspace_is_not_identity_but_the_bound_profile_is(self) -> None:
        record = {"invitee_workspace_id": "daniel", "external_id": "daniel"}
        self.assertFalse(_record_matches_account(record, user_id="uuid-x", external_id="stranger_ab12cd34", workspace_id="daniel"))
        self.assertTrue(_record_matches_account(record, user_id="uuid-owner", external_id="daniel", workspace_id="daniel"))

    def test_after_an_account_switch_the_previous_accounts_league_no_longer_matches(self) -> None:
        session = _session("uuid-member", "member", "member_ws")
        self.assertTrue(authz.is_league_member_or_invitee(session, LEAGUE))
        session.update(_session("uuid-attacker", "attacker", "attacker_ws"))  # the next account signs in
        self.assertFalse(authz.is_league_member_or_invitee(session, LEAGUE))

    def test_discovery_gives_an_unrelated_account_no_leagues(self) -> None:
        with patch("fantasy_shared_league_startup_sync.list_shared_league_documents", return_value=[LEAGUE]):
            self.assertEqual(discover_shared_league_memberships_for_session(_session("uuid-attacker", "attacker", "attacker_ws")), [])
            member = discover_shared_league_memberships_for_session(_session("uuid-member", "member", "member_ws"))
        self.assertEqual(len(member), 1)


class LeagueWriteAuthorizationTests(_SignInOn):
    def test_outside_a_user_request_nothing_is_checked(self) -> None:
        doc = {"x": 1}
        self.assertIs(authz.authorize_league_write(None, doc, LEAGUE), doc)

    def test_signed_out_and_non_members_are_refused(self) -> None:
        with self.assertRaises(authz.SharedLeagueWriteRefused):
            authz.authorize_league_write(_session(""), dict(LEAGUE), LEAGUE)
        with self.assertRaises(authz.SharedLeagueWriteRefused):
            authz.authorize_league_write(_session("uuid-attacker", "attacker", "attacker_ws"), dict(LEAGUE), LEAGUE)

    def test_a_new_league_may_be_created_by_a_signed_in_account(self) -> None:
        doc = {"league_id": "league:new", "commissioner_user_id": "uuid-creator"}
        self.assertEqual(authz.authorize_league_write(_session("uuid-creator"), doc, None), doc)

    def test_a_member_cannot_take_over_the_commissioner_name_or_draft(self) -> None:
        incoming = {**LEAGUE, "commissioner_user_id": "uuid-member", "league_name": "Mine", "draft_id": "x", "league_rosters": {"Team 2": {}}}
        out = authz.authorize_league_write(_session("uuid-member"), incoming, LEAGUE)
        self.assertEqual((out["commissioner_user_id"], out["league_name"], out["draft_id"]), ("uuid-owner", "Owner League", "draft-1"))
        # A member's own team saves go through; another team's stored roster is never dropped or
        # overwritten by a member's copy (2026-11-05: it used to replace the whole roster map).
        self.assertEqual(out["league_rosters"], {"Team 1": {"players": []}, "Team 2": {}})

    def test_team_owner_and_invitee_cannot_become_commissioner_by_editing_the_document(self) -> None:
        for session in (_session("uuid-member"), _session("uuid-invitee", "invitee")):
            out = authz.authorize_league_write(session, {**LEAGUE, "commissioner_user_id": session["_suite_auth_user_id"]}, LEAGUE)
            self.assertEqual(out["commissioner_user_id"], "uuid-owner")
            self.assertFalse(authz.is_league_commissioner(session, out))

    def test_a_member_push_cannot_reassign_another_owners_firm_team(self) -> None:
        from fantasy_shared_league_store import push_league_context_to_shared

        store = MagicMock()
        stored = {
            **LEAGUE,
            "team_ownership": {
                "Team 1": {**OWNER, "claim_status": "firm"},
                "Team 2": {"user_id": "uuid-member", "email": "member@example.com"},
            },
        }
        store.load.return_value = stored
        store.save.side_effect = lambda doc: doc
        context = {
            "metadata": {"league_id": "league:abc"},
            "team_ownership": {"Team 1": {"user_id": "uuid-member", "claim_status": "firm"}},
            "league_rosters": {},
        }
        with patch.object(authz, "current_session", return_value=_session("uuid-member", "member")), patch(
            "fantasy_shared_league_store._anonymous_guest", return_value=False
        ), patch("fantasy_league_context.upsert_league_context", return_value=None):
            saved = push_league_context_to_shared({}, context, store=store)
        self.assertEqual(saved["team_ownership"]["Team 1"]["user_id"], "uuid-owner")

    def test_an_invitee_may_answer_and_the_commissioner_may_change_anything(self) -> None:
        self.assertTrue(authz.authorize_league_write(_session("uuid-invitee", "invitee"), dict(LEAGUE), LEAGUE))
        incoming = {**LEAGUE, "league_name": "Renamed"}
        self.assertEqual(authz.authorize_league_write(_session("uuid-owner"), incoming, LEAGUE)["league_name"], "Renamed")


class LeagueWritersRefuseNonMembersTests(_SignInOn):
    def _store(self):
        store = MagicMock()
        store.load.return_value = dict(LEAGUE)
        return store

    def test_save_shared_league_refuses_a_non_member(self) -> None:
        from fantasy_shared_league_store import save_shared_league

        store = self._store()
        with patch.object(authz, "current_session", return_value=_session("uuid-attacker", "attacker", "attacker_ws")):
            with self.assertRaises(RuntimeError):  # SharedLeagueWriteRefused; callers catch RuntimeError
                save_shared_league({**LEAGUE, "league_rosters": {}}, store=store)
        store.save.assert_not_called()

    def test_push_context_refuses_a_non_member_and_keeps_the_commissioner_for_members(self) -> None:
        from fantasy_shared_league_store import push_league_context_to_shared

        context = {"metadata": {"league_id": "league:abc", "commissioner_user_id": "uuid-attacker"}, "league_rosters": {"Team 1": {}}}
        store = self._store()
        with patch.object(authz, "current_session", return_value=_session("uuid-attacker", "attacker", "attacker_ws")), patch(
            "fantasy_shared_league_store._anonymous_guest", return_value=False
        ):
            self.assertIsNone(push_league_context_to_shared({}, context, store=store))
        store.save.assert_not_called()
        store = self._store()
        store.save.side_effect = lambda doc: doc
        with patch.object(authz, "current_session", return_value=_session("uuid-member", "member")), patch(
            "fantasy_shared_league_store._anonymous_guest", return_value=False
        ), patch("fantasy_league_context.upsert_league_context", return_value=None):
            saved = push_league_context_to_shared({}, dict(context), store=store)
        self.assertEqual(saved["commissioner_user_id"], "uuid-owner")


class ForgedControlCenterClickTests(unittest.TestCase):
    def _app(self, *, commissioner: bool, status: str):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(FIXTURE), default_timeout=60)
        at.session_state["active_shared_draft_room_code"] = "ABC123"
        at.session_state["_fixture_commissioner"] = commissioner
        at.session_state["_fixture_status"] = status
        at.run()
        self.assertFalse(at.exception, [str(e.value)[:200] for e in at.exception])
        return at

    def test_forged_resume_from_a_guest_does_not_unpause(self) -> None:
        at = self._app(commissioner=False, status="paused")
        resume = at.button(key="live_draft_resume")
        self.assertTrue(resume.disabled)
        resume.click().run()  # what a crafted widget message does
        self.assertEqual(at.session_state["_fixture_room"]["status"], "paused")
        self.assertEqual(list(at.session_state["_fixture_calls"]), [])

    def test_forged_auto_pick_from_a_guest_does_nothing(self) -> None:
        at = self._app(commissioner=False, status="in_progress")
        at.button(key="live_draft_auto_now").click().run()
        self.assertNotIn(("auto_pick",), list(at.session_state["_fixture_calls"]))

    def test_the_commissioner_can_still_resume(self) -> None:
        at = self._app(commissioner=True, status="paused")
        at.button(key="live_draft_resume").click().run()
        self.assertNotEqual(at.session_state["_fixture_room"]["status"], "paused")


if __name__ == "__main__":
    unittest.main()
