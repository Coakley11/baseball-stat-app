"""Shared League invites with the hosted account arrangement (2026-11-03/04 acceptance).

Production: Danny created "Danny vs Barry League" and invited username "coakley11". That username
belongs to a different account (hash 16fc8a); Barry's account is "user_coakley11" (hash 20c4cd).
The invite was stored with no account id, so it named nobody but the typed text. Hosted accounts
carry two ids, the Supabase Auth id and the suite_users id, plus a username and a workspace. All
ids below are sanitized placeholders.

Covered: the username lookup records the account id; the commissioner confirms the account before
anything is stored; unknown usernames and failed lookups are refused; Barry receives an invite to
user_coakley11; the invite addressed to coakley11 is never shown to or accepted by Barry; the
commissioner can cancel (revoke) an invite, after which nobody can accept it; reads refresh within
seconds for a session that is already open.
"""

from __future__ import annotations

import copy
import json
import types
import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import fantasy_shared_league_authz as authz
from draft_archive_state import list_draft_archives
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_league_invites import (
    create_league_invite,
    join_shared_league_from_invite,
    list_pending_invites_for_session,
    preview_league_invitee,
    revoke_league_invite,
)
from fantasy_shared_league_store import invalidate_shared_league_doc_cache, load_shared_league
import tests.test_fantasy_league_invites as _invite_suite  # module import: its tests are not re-collected here
from tests.test_fantasy_trade_proposals import _as_user

DANNY = {"auth": "auth-danny-0001", "suite": "suite-danny-0001", "username": "daniel", "workspace": "daniel"}
BARRY = {"auth": "auth-barry-0002", "suite": "suite-barry-0002", "username": "user_coakley11",
         "workspace": "user_coakley11"}
OTHER = {"auth": "auth-coak-0003", "suite": "suite-coak-0003", "username": "coakley11", "workspace": "coakley11"}
SUITE_USERS = [
    {"id": DANNY["suite"], "external_id": "daniel", "email": "danny@example.com"},
    {"id": BARRY["suite"], "external_id": "user_coakley11", "email": "coakley11@example.org"},
    {"id": OTHER["suite"], "external_id": "coakley11", "email": "other@example.com"},
]


def _find_user_rows(*, external_id: str = "", email: str = "") -> list[dict[str, str]]:
    return [dict(r) for r in SUITE_USERS if external_id and r["external_id"] == external_id]


def _signed_in(account: dict) -> dict:
    return {
        "_suite_auth_session": True,
        "_suite_auth_user_id": account["auth"],     # Supabase Auth id
        "_suite_cloud_user_id": account["suite"],   # suite_users id: differs, as hosted
        "_suite_auth_external_id": account["username"],
        "_suite_owned_workspace_id": account["workspace"],
        "_suite_active_workspace_id": account["workspace"],
    }


def isolate_shared_room_store(case: unittest.TestCase) -> None:
    """Shared Draft rooms in a temporary store for this test (the default local store is the
    repository's data/draft_rooms, which kept rooms between runs)."""
    import tempfile
    from pathlib import Path

    import draft_room_shared_state as rooms

    tmp = tempfile.TemporaryDirectory()
    previous = rooms._DEFAULT_STORE
    rooms._DEFAULT_STORE = rooms.LocalFileSharedRoomStore(root=Path(tmp.name))

    def _restore() -> None:
        rooms._DEFAULT_STORE = previous
        tmp.cleanup()

    case.addCleanup(_restore)


def store_room_with_host(room_code: str, host: dict, participants: tuple[dict, ...] = ()) -> None:
    """A stored Shared Draft room as production records it (2026-10-30 audit D4b: every room's host
    is an Auth user, and the host participant id is that Auth id)."""
    from draft_room_shared_state import get_shared_room_store

    seated = {acct["auth"]: {"user_id": acct["suite"]} for acct in (host, *participants)}
    get_shared_room_store().save({
        "room_code": room_code.upper(),
        "host_participant_id": host["auth"],
        "host_user_id": host["suite"],
        "participants": seated,
        "room": {"status": "complete"},
        "status": "complete",
        "revision": 1,
    })


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        _invite_suite.TestFantasyLeagueInvites.setUp(self)
        isolate_shared_room_store(self)

    tearDown = _invite_suite.TestFantasyLeagueInvites.tearDown
    _write_registry = _invite_suite.TestFantasyLeagueInvites._write_registry
    _workspace = _invite_suite.TestFantasyLeagueInvites._workspace

    def on(self) -> ExitStack:
        """Sign-in on, as hosted. The hosted registry file is on the app's own disk and does not
        know these accounts, so usernames are resolved from suite_users."""
        authz.clear_league_copy_decisions()
        invalidate_shared_league_doc_cache()
        stack = ExitStack()
        stack.enter_context(patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}))
        stack.enter_context(patch("fantasy_shared_league_store._anonymous_guest", return_value=False))
        stack.enter_context(patch("suite_storage_supabase.find_user_rows", side_effect=_find_user_rows))
        return stack

    def league(self) -> tuple[dict, str]:
        self._write_registry({"by_owner": {}})
        self.danny_session = _signed_in(DANNY)
        self.owner_session: dict = {}
        context = _invite_suite._seed_imported_league(self.owner_session, user_id=DANNY["suite"],
                                                      workspace=DANNY["workspace"])
        return context, resolve_canonical_league_id(context)

    @contextmanager
    def as_account(self, account: dict):
        with _as_user(account["suite"]), self._workspace(account["workspace"]), patch(
            "fantasy_league_invites._resolve_external_id", return_value=account["username"]
        ):
            yield

    def invite(self, context: dict, target: str = "user_coakley11") -> tuple[dict | None, str]:
        """Danny's two steps: find the account, confirm it, send."""
        with self.on(), self.as_account(DANNY):
            found = preview_league_invitee({}, context, target)
            if not found.get("ok"):
                return None, found["error"]
            return create_league_invite({}, context, invitee_target=target,
                                        confirmed_invitee_user_id=found["invitee_user_id"])

    def legacy_invite(self, context: dict, target: str = "coakley11") -> dict:
        """The production invite: addressed by typed text only, with no account id (as stored by
        the deployed code before this fix)."""
        with patch("fantasy_league_invites._separate_accounts_on", return_value=False), patch(
            "fantasy_league_invites.resolve_invitee_target",
            return_value={"invitee_workspace_id": target, "invitee_user_id": "", "invitee_external_id": target,
                          "resolve_source": "slug_fallback"},
        ), self.as_account(DANNY):
            invite, err = create_league_invite({}, context, invitee_target=target)
        self.assertEqual(err, "")
        return invite

    def pending(self, session: dict, account: dict) -> list[dict]:
        with self.on(), self.as_account(account):
            return list_pending_invites_for_session(session)

    def accept(self, session: dict, account: dict, league_id: str, invite_id: str, team: str):
        with self.on(), self.as_account(account):
            return join_shared_league_from_invite(session, league_id=league_id, invite_id=invite_id, team_name=team)

    def stored_invite(self, league_id: str, invite_id: str) -> dict:
        invalidate_shared_league_doc_cache()
        with self.on():
            doc = load_shared_league(league_id) or {}
        return next(i for i in doc.get("league_invites") or [] if i["invite_id"] == invite_id)

    def open_team(self, league_id: str) -> str:
        with self.on():
            doc = load_shared_league(league_id) or {}
        owned = {t for t, r in (doc.get("team_ownership") or {}).items() if (r or {}).get("user_id")}
        return next(t for t in sorted(doc.get("league_rosters") or {}) if t not in owned)


class ResolveAndConfirmTests(_Case):
    def test_1_a_new_invite_records_the_right_existing_account_id(self) -> None:
        context, league_id = self.league()
        invite, err = self.invite(context)
        self.assertEqual(err, "")
        stored = self.stored_invite(league_id, invite["invite_id"])
        self.assertEqual((stored["invitee_user_id"], stored["invitee_external_id"], stored["status"]),
                         (BARRY["suite"], "user_coakley11", "pending"))

    def test_2_the_account_is_confirmed_before_anything_is_stored(self) -> None:
        context, league_id = self.league()
        with self.on(), self.as_account(DANNY):
            found = preview_league_invitee({}, context, "user_coakley11")
            unconfirmed = create_league_invite({}, context, invitee_target="user_coakley11")
            swapped = create_league_invite({}, context, invitee_target="user_coakley11",
                                           confirmed_invitee_user_id=OTHER["suite"])
        self.assertEqual((found["ok"], found["username"], found["invitee_user_id"]),
                         (True, "user_coakley11", BARRY["suite"]))
        self.assertIsNone(unconfirmed[0])
        self.assertIn("Confirm the account", unconfirmed[1])
        self.assertIsNone(swapped[0])
        self.assertIn("different account than the one confirmed", swapped[1])
        with self.on():
            self.assertEqual((load_shared_league(league_id) or {}).get("league_invites") or [], [])

    def test_3_unknown_usernames_and_failed_lookups_are_refused(self) -> None:
        context, league_id = self.league()
        _invite, err = self.invite(context, "coakley111")
        self.assertIn("No Baseball account has the username 'coakley111'", err)
        with self.on(), self.as_account(DANNY), patch(
            "suite_storage_supabase.find_user_rows", side_effect=RuntimeError("store down")
        ):
            found = preview_league_invitee({}, context, "user_coakley11")
            sent = create_league_invite({}, context, invitee_target="user_coakley11",
                                        confirmed_invitee_user_id=BARRY["suite"])
        self.assertIn("Couldn't check that username", found["error"])
        self.assertIsNone(sent[0])
        with self.on():
            self.assertEqual((load_shared_league(league_id) or {}).get("league_invites") or [], [])

    def test_danny_cannot_invite_himself(self) -> None:
        context, _league_id = self.league()
        _invite, err = self.invite(context, "daniel")
        self.assertIn("cannot invite your own account", err)


class BarryReceivesTests(_Case):
    def test_4_barry_receives_and_accepts_an_invite_to_user_coakley11(self) -> None:
        context, league_id = self.league()
        invite, _err = self.invite(context)
        barry = _signed_in(BARRY)
        rows = self.pending(barry, BARRY)
        self.assertEqual([(r["invite_id"], r["league_id"]) for r in rows], [(invite["invite_id"], league_id)])
        team = self.open_team(league_id)
        _entry, ctx, err = self.accept(barry, BARRY, league_id, invite["invite_id"], team)
        self.assertEqual(err, "")
        self.assertEqual(self.stored_invite(league_id, invite["invite_id"])["status"], "accepted")

    def test_barry_is_found_by_account_id_alone(self) -> None:
        context, _league_id = self.league()
        self.invite(context)
        renamed = dict(BARRY, workspace="barry_ws2", username="barry_renamed")
        with patch("fantasy_league_invites._read_inbox", side_effect=lambda _ws: []):
            self.assertEqual(len(self.pending(_signed_in(renamed), renamed)), 1)


class WronglyAddressedInviteTests(_Case):
    """The production invite: to "coakley11", no account id."""

    def test_5_barry_cannot_see_or_accept_the_invite_to_coakley11(self) -> None:
        context, league_id = self.league()
        wrong = self.legacy_invite(context)
        barry = _signed_in(BARRY)
        self.assertEqual(self.pending(barry, BARRY), [])
        _entry, _ctx, err = self.accept(barry, BARRY, league_id, wrong["invite_id"], self.open_team(league_id))
        self.assertIn("sent to a different account", err)
        self.assertEqual(self.stored_invite(league_id, wrong["invite_id"])["status"], "pending")
        self.assertEqual(list_draft_archives(barry), [])

    def test_6_after_cancelling_nobody_can_use_it(self) -> None:
        context, league_id = self.league()
        wrong = self.legacy_invite(context)
        other = _signed_in(OTHER)
        clock = [1000.0]
        with patch("fantasy_league_invites._monotonic", side_effect=lambda: clock[0], create=True):
            self.assertEqual(len(self.pending(other, OTHER)), 1)  # the exposure: coakley11 could accept today
            with self.on(), self.as_account(DANNY):
                ok, err = revoke_league_invite(self.danny_session, context, invite_id=wrong["invite_id"])
            self.assertEqual((ok, err), (True, ""))
            # Accepting is refused at once (it re-reads the stored league) ...
            _entry, _ctx, err = self.accept(other, OTHER, league_id, wrong["invite_id"], self.open_team(league_id))
            self.assertIn("no longer pending", err)
            clock[0] += 16.0  # ... and the invite leaves their list on the next rerun after 15 s
            self.assertEqual(self.pending(other, OTHER), [])
        stored = self.stored_invite(league_id, wrong["invite_id"])
        self.assertEqual((stored["status"], stored["revoked_by_user_id"]), ("revoked", DANNY["suite"]))
        with self.on():
            doc = load_shared_league(league_id)
        self.assertEqual(len(doc["league_invites"]), 1)  # kept as a record, never deleted
        self.assertTrue(doc["league_rosters"])          # the league is untouched

    def test_a_stale_pending_copy_cannot_undo_a_cancel(self) -> None:
        from fantasy_shared_league_store import _merge_league_invites

        context, league_id = self.league()
        wrong = self.legacy_invite(context)
        stale = copy.deepcopy(wrong)
        with self.on(), self.as_account(DANNY):
            revoke_league_invite(self.danny_session, context, invite_id=wrong["invite_id"])
        revoked = self.stored_invite(league_id, wrong["invite_id"])
        self.assertEqual(_merge_league_invites([revoked], [stale])[0]["status"], "revoked")
        self.assertEqual(_merge_league_invites([stale], [revoked])[0]["status"], "revoked")

    def test_only_the_commissioner_can_cancel(self) -> None:
        context, league_id = self.league()
        wrong = self.legacy_invite(context)
        for account in (BARRY, OTHER):
            with self.on(), self.as_account(account):
                ok, err = revoke_league_invite(_signed_in(account), context, invite_id=wrong["invite_id"])
            self.assertFalse(ok)
            self.assertIn("Only the league commissioner", err)
        self.assertEqual(self.stored_invite(league_id, wrong["invite_id"])["status"], "pending")

    def test_cancelling_one_invite_leaves_barrys_new_invite_pending(self) -> None:
        context, league_id = self.league()
        wrong = self.legacy_invite(context)
        right, err = self.invite(context)
        self.assertEqual(err, "")
        with self.on(), self.as_account(DANNY):
            revoke_league_invite(self.danny_session, context, invite_id=wrong["invite_id"])
        self.assertEqual(self.stored_invite(league_id, right["invite_id"])["status"], "pending")
        self.assertEqual([r["invite_id"] for r in self.pending(_signed_in(BARRY), BARRY)], [right["invite_id"]])


class IsolationTests(_Case):
    def test_7_a_stranger_never_sees_an_invite_or_the_league(self) -> None:
        context, league_id = self.league()
        self.invite(context)
        stranger = {"auth": "auth-x", "suite": "suite-x", "username": "mallory", "workspace": "mallory"}
        session = _signed_in(stranger)
        self.assertEqual(self.pending(session, stranger), [])
        with self.on():
            doc = load_shared_league(league_id)
            self.assertFalse(authz.may_read_league(session, doc))
            self.assertTrue(authz.may_read_league(_signed_in(BARRY), doc))  # the invitee only
            self.assertFalse(authz.may_read_league(_signed_in(OTHER), doc))  # not coakley11

    def test_8_workspace_invites_with_sign_in_off_still_work(self) -> None:
        self._write_registry({"by_owner": {"user:seal11": {"owner_user_id": "user:seal11",
                                                          "owner_external_id": "seal11", "workspace_id": "ariel"}}})
        context = _invite_suite._seed_imported_league({}, user_id="user:donny", workspace="donny_ws")
        with _as_user("user:donny"), self._workspace("donny_ws"):
            invite, err = create_league_invite({}, context, invitee_target="ariel")
        self.assertEqual(err, "")
        self.assertEqual((invite["invitee_workspace_id"], invite["invitee_user_id"]), ("ariel", "user:seal11"))


class InviteSenderLabelTests(_Case):
    def test_an_account_id_is_never_shown_as_the_sender(self) -> None:
        from fantasy_league_invites import invite_sender_label

        uid = "a555b840-d350-4371-bbfb-8182914ed4ea"
        stored_before_fix = {"invited_by_user_id": uid, "invited_by_display": uid}
        self.assertEqual(invite_sender_label(stored_before_fix), "the league commissioner")
        self.assertEqual(invite_sender_label({**stored_before_fix, "invited_by_username": "qa_danny"}), "qa_danny")
        self.assertEqual(invite_sender_label({"invited_by_user_id": "u1", "invited_by_display": "u1"}),
                         "the league commissioner")
        self.assertEqual(invite_sender_label({"invited_by_user_id": uid, "invited_by_display": "Danny C"}), "Danny C")

    def test_the_commissioner_sees_the_invitees_username_not_an_account_id(self) -> None:
        from fantasy_league_invites import (
            _readable_response_message,
            invitee_label,
            list_commissioner_invite_response_notifications,
        )

        uid = "b243eff8-09fe-41cb-855a-c28848de116a"
        self.assertEqual(invitee_label({"invitee_user_id": uid, "invitee_external_id": "qa_barry"}), "qa_barry")
        self.assertEqual(invitee_label({"invitee_user_id": uid}), "The invited manager")
        stored_before_fix = {"invite_id": "inv_1", "responder_user_id": uid,
                             "message": f"{uid} accepted your invitation and claimed Barry"}
        doc = {"league_invites": [{"invite_id": "inv_1", "invitee_user_id": uid, "invitee_external_id": "qa_barry"}]}
        self.assertEqual(_readable_response_message(stored_before_fix, doc),
                         "qa_barry accepted your invitation and claimed Barry")
        # The real path: Barry accepts, Danny's Library reads the notice.
        context, league_id = self.league()
        invite, _err = self.invite(context)
        team = self.open_team(league_id)
        _entry, _ctx, err = self.accept(_signed_in(BARRY), BARRY, league_id, invite["invite_id"], team)
        self.assertEqual(err, "")
        with self.on(), self.as_account(DANNY):
            notes = list_commissioner_invite_response_notifications(self.danny_session)
        self.assertIn(f"user_coakley11 accepted your invitation and claimed {team}", [n["message"] for n in notes])
        self.assertFalse([n for n in notes if BARRY["suite"] in n["message"] or BARRY["auth"] in n["message"]])

    def test_a_new_invite_records_the_senders_username(self) -> None:
        context, league_id = self.league()
        invite, err = self.invite(context)
        self.assertEqual(err, "")
        stored = self.stored_invite(league_id, invite["invite_id"])
        self.assertEqual(stored["invited_by_username"], "daniel")
        self.assertNotEqual(stored["invited_by_display"], stored["invited_by_user_id"])


class LibraryPageTests(_Case):
    """The real Saved Draft Library page (AppTest), sign-in on."""

    def app(self, account: dict, extra: dict | None = None):
        from pathlib import Path

        from streamlit.testing.v1 import AppTest

        fixture = Path(__file__).resolve().parent / "fixtures" / "library_invite_app.py"
        at = AppTest.from_file(str(fixture), default_timeout=180)
        for key, value in {**copy.deepcopy(extra or {}), **_signed_in(account)}.items():
            at.session_state[key] = value
        at.session_state["_fx_league_root"] = str(self.store_root)
        at.session_state["_fx_suite_users"] = SUITE_USERS
        return at

    @staticmethod
    def text(at) -> str:
        parts = [str(getattr(e, "value", "")) for e in list(at.markdown) + list(at.caption) + list(at.success)
                 + list(at.warning) + list(at.error) + list(at.info)]
        return " ".join(parts) + " " + " ".join(str(getattr(e, "label", "")) for e in at.checkbox)

    def run_ok(self, at, step=None):
        with patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}):
            (step or at).run()
        self.assertFalse(at.exception, [str(e.value)[:300] for e in at.exception])

    def test_barry_sees_the_invite_and_his_username_on_saved_draft_library(self) -> None:
        context, _league_id = self.league()
        self.invite(context)
        at = self.app(BARRY)
        self.run_ok(at)
        page = self.text(at)
        self.assertIn("Shared league invites", page)
        self.assertIn("Invite Test League", page)
        self.assertIn("Your username for Shared League invites: **user_coakley11**", page)

    def test_the_coakley11_invite_is_not_on_barrys_page(self) -> None:
        context, _league_id = self.league()
        self.legacy_invite(context)
        at = self.app(BARRY)
        self.run_ok(at)
        self.assertNotIn("Shared league invites", self.text(at))

    def test_barry_accepts_and_the_invite_leaves_his_page_at_once(self) -> None:
        # QA run 2: after Accept the card stayed (a 15 s scan reuse) and the result never showed.
        context, league_id = self.league()
        invite, _err = self.invite(context)
        at = self.app(BARRY)
        self.run_ok(at)
        page = self.text(at)
        self.assertIn("Invited by **daniel**", page)  # the username, not an account id
        self.assertNotIn(DANNY["suite"], page)
        self.run_ok(at, next(b for b in at.button if b.label == "Accept invite").click())
        page = self.text(at)
        self.assertIn("Joined", page)
        self.assertNotIn("invited to join", page)
        self.assertFalse([b for b in at.button if b.label == "Accept invite"])
        self.assertEqual(self.stored_invite(league_id, invite["invite_id"])["status"], "accepted")

    def test_an_unknown_username_message_stays_visible(self) -> None:
        # QA run 2: the refusal rendered only in the lookup's own run, inside a panel that collapsed.
        context, league_id = self.league()
        at = self.app(DANNY, extra=self.owner_session)
        self.run_ok(at)
        at.text_input(key="commissioner_invite_target").set_value("qa_nobody_here")
        self.run_ok(at, next(b for b in at.button if b.label == "Find account").click())
        self.assertIn("No Baseball account has the username 'qa_nobody_here'", self.text(at))
        self.run_ok(at)  # any later rerun
        self.assertIn("No Baseball account has the username 'qa_nobody_here'", self.text(at))
        self.assertFalse([b for b in at.button if b.key == "commissioner_invite_send"])
        with self.on():
            self.assertEqual((load_shared_league(league_id) or {}).get("league_invites") or [], [])

    def test_the_run_that_sends_shows_the_new_invite_and_no_send_button(self) -> None:
        # QA run 2: after Send the page still showed the confirm step and a list without the invite.
        context, league_id = self.league()
        at = self.app(DANNY, extra=self.owner_session)
        self.run_ok(at)
        at.text_input(key="commissioner_invite_target").set_value("user_coakley11")
        self.run_ok(at, next(b for b in at.button if b.label == "Find account").click())
        self.run_ok(at, at.checkbox(key="commissioner_invite_confirm_user_coakley11").check())
        self.run_ok(at, at.button(key="commissioner_invite_send").click())
        with self.on():
            invalidate_shared_league_doc_cache()
            (invite,) = load_shared_league(league_id)["league_invites"]
        self.assertFalse([b for b in at.button if b.key == "commissioner_invite_send"])
        self.assertIn("Invite to **user_coakley11**", self.text(at))
        self.assertTrue([b for b in at.button if b.key == f"invite_revoke_{invite['invite_id']}"])

    def test_danny_finds_confirms_and_sends_then_cancels_the_wrong_invite(self) -> None:
        context, league_id = self.league()
        wrong = self.legacy_invite(context)
        at = self.app(DANNY, extra=self.owner_session)
        self.run_ok(at)
        at.text_input(key="commissioner_invite_target").set_value("user_coakley11")
        find = next(b for b in at.button if b.label == "Find account")
        self.run_ok(at, find.click())
        self.assertIn("Username **user_coakley11** belongs to an existing Baseball account.", self.text(at))
        send = at.button(key="commissioner_invite_send")
        self.assertTrue(send.disabled)  # not until the account is confirmed
        self.run_ok(at, at.checkbox(key="commissioner_invite_confirm_user_coakley11").check())
        self.run_ok(at, at.button(key="commissioner_invite_send").click())
        with self.on():
            invalidate_shared_league_doc_cache()
            stored = load_shared_league(league_id)["league_invites"]
        new = [i for i in stored if i["invite_id"] != wrong["invite_id"]]
        self.assertEqual([(i["invitee_user_id"], i["status"]) for i in new], [(BARRY["suite"], "pending")])

        self.run_ok(at, at.button(key=f"invite_revoke_{wrong['invite_id']}").click())
        self.assertIn("Cancel the invite to coakley11?", self.text(at))
        self.run_ok(at, at.button(key=f"invite_revoke_yes_{wrong['invite_id']}").click())
        self.assertEqual(self.stored_invite(league_id, wrong["invite_id"])["status"], "revoked")
        self.assertEqual(self.stored_invite(league_id, new[0]["invite_id"])["status"], "pending")


class InviteSentWhileSignedInTests(_Case):
    def test_an_invite_sent_while_barry_is_signed_in_shows_within_seconds(self) -> None:
        # The server's local inbox file is lost on every app restart (Streamlit Cloud disk), so
        # the stored Shared League is the lasting path; this reads only that.
        context, _league_id = self.league()
        barry = _signed_in(BARRY)
        clock = [1000.0]
        with patch("fantasy_league_invites._monotonic", side_effect=lambda: clock[0], create=True), patch(
            "fantasy_league_invites._read_inbox", side_effect=lambda _ws: []
        ), patch("fantasy_league_context.list_league_contexts", return_value=[]):  # not in the league yet
            self.assertEqual(self.pending(barry, BARRY), [])  # Barry's Library opened first
            invite, err = self.invite(context)
            self.assertEqual(err, "")
            clock[0] += 16.0  # Barry's next rerun, a little later, in the same session
            self.assertEqual([r["invite_id"] for r in self.pending(barry, BARRY)], [invite["invite_id"]])


class _Response:
    def __init__(self, payload) -> None:
        self.status_code = 200
        self.content = json.dumps(payload).encode("utf-8")
        self.text = self.content.decode("utf-8")

    def json(self):
        return json.loads(self.content)


class SessionReadCacheTests(unittest.TestCase):
    """suite_storage_supabase._request keeps a per-browser-session GET cache."""

    def setUp(self) -> None:
        import suite_storage_supabase as storage

        self.storage = storage
        self.tables: dict[str, list] = {"baseball_shared_leagues": [], "suite_users": [{"id": "u1"}]}
        self.buckets = {"barry": {}, "danny": {}}
        self.who = "barry"
        self.clock = [1000.0]

        def fake_request(method, url, **kwargs):
            table = url.rsplit("/rest/v1/", 1)[1].split("?", 1)[0]
            if method.upper() == "GET":
                return _Response(list(self.tables.get(table, [])))
            self.tables.setdefault(table, []).append(kwargs.get("json"))
            return _Response([kwargs.get("json")])

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(storage, "get_cloud_config", return_value=types.SimpleNamespace(url="https://x")))
        stack.enter_context(patch.object(storage, "_headers", return_value={}))
        stack.enter_context(patch.object(storage, "_read_cache_bucket", side_effect=lambda: self.buckets[self.who]))
        stack.enter_context(patch.object(storage, "_monotonic", side_effect=lambda: self.clock[0], create=True))
        stack.enter_context(patch("requests.request", side_effect=fake_request))

    def get(self, table: str):
        return self.storage._request("GET", table, params={"select": "*"}, prefer="return=representation")

    def test_another_accounts_new_league_reaches_an_open_session_after_a_few_seconds(self) -> None:
        self.assertEqual(self.get("baseball_shared_leagues"), [])  # Barry's session reads first
        self.who = "danny"
        self.storage._request("POST", "baseball_shared_leagues", json_body={"league_id": "league:1"})
        self.who = "barry"
        self.clock[0] += 16.0
        self.assertEqual(self.get("baseball_shared_leagues"), [{"league_id": "league:1"}])

    def test_a_read_is_still_reused_briefly_so_renders_do_not_refetch(self) -> None:
        self.get("baseball_shared_leagues")
        self.tables["baseball_shared_leagues"].append({"league_id": "league:2"})
        self.clock[0] += 5.0
        self.assertEqual(self.get("baseball_shared_leagues"), [])

    def test_other_tables_keep_their_existing_caching(self) -> None:
        self.assertEqual(self.get("suite_users"), [{"id": "u1"}])
        self.tables["suite_users"].append({"id": "u2"})
        self.clock[0] += 3600.0
        self.assertEqual(self.get("suite_users"), [{"id": "u1"}])  # unchanged behaviour


if __name__ == "__main__":
    unittest.main()
