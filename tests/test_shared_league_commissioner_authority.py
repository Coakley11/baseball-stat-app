"""Shared League security fixes R-1..R-7 (security review 2026-11-05, owner-approved).

Every case runs as a USER REQUEST (fantasy_shared_league_authz.current_session patched to the test
session) with sign-in on, which is how the hosted app runs. Outside a user request (scripts and
tests) nothing is checked, so the older suites never exercised these rules.

Covered: forged local metadata (finding 1 reproduction); every privileged mutation a member could
attempt, refused on the server; legitimate member writes still pass; invitation races
(compare-and-swap); room-host authority incl. reconnect and a room with no recorded host;
existing-league compatibility (legacy league without a stored commissioner); sign-in-off refusal;
the Shared Draft room write check; the atomic Supabase compare-and-swap.
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import draft_room_shared_state as rooms
import fantasy_shared_league_authz as authz
from fantasy_league_context import CONTEXT_TYPE_REAL_LEAGUE
from fantasy_shared_league_store import (
    LocalFileSharedLeagueStore,
    SharedLeagueConflict,
    invalidate_shared_league_doc_cache,
    load_shared_league,
    save_shared_league,
    set_shared_league_store,
)

COMMISSIONER = {"auth": "auth-comm-0001", "suite": "suite-comm-0001", "username": "danny"}
MEMBER = {"auth": "auth-memb-0002", "suite": "suite-memb-0002", "username": "barry"}
INVITEE = {"auth": "auth-invt-0003", "suite": "suite-invt-0003", "username": "cara"}
OUTSIDER = {"auth": "auth-outs-0004", "suite": "suite-outs-0004", "username": "mallory"}

LEAGUE_ID = "league:test-authority"


def signed_in(account: dict) -> dict:
    return {
        "_suite_auth_session": True,
        "_suite_auth_user_id": account["auth"],
        "_suite_cloud_user_id": account["suite"],
        "_suite_auth_external_id": account["username"],
        "_suite_owned_workspace_id": account["username"],
        "_suite_active_workspace_id": account["username"],
    }


def stored_league(**overrides) -> dict:
    doc = {
        "schema_version": 1,
        "league_id": LEAGUE_ID,
        "league_name": "Danny vs Barry League",
        "draft_id": "draft-1",
        "commissioner_user_id": COMMISSIONER["suite"],
        "revision": 5,
        "roster_settings": {"lineup_format": {"slots": {"C": 1}}},
        "metadata": {"created_from": "live_draft"},
        "team_ownership": {
            "Danny": {"user_id": COMMISSIONER["suite"], "claim_status": "claimed"},
            "Barry": {"user_id": MEMBER["suite"], "claim_status": "claimed"},
            "Open": {},
        },
        "league_rosters": {"Danny": {"players": ["A"]}, "Barry": {"players": ["B"]}, "Open": {"players": ["C"]}},
        "league_invites": [
            {"invite_id": "inv_pending", "status": "pending", "invitee_user_id": INVITEE["suite"]},
            {"invite_id": "inv_revoked", "status": "revoked", "invitee_user_id": OUTSIDER["suite"]},
        ],
        "trade_proposals": [
            {"proposal_id": "t1", "status": "pending", "proposer_team": "Danny", "recipient_team": "Barry"},
        ],
        "season_ledger": {
            "calendar": {"first_day": "2030-04-01"},
            "periods": {
                "P1": {"start": "2030-04-01", "finalized_at": "", "lineups": {}},
                "P0": {"start": "2020-04-01", "finalized_at": "2020-04-08", "lineups": {"Barry": {"saved_at": "x"}}},
            },
        },
        "league_activity": [{"entry": 1}],
    }
    doc.update(overrides)
    return doc


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._stack = ExitStack()
        self.addCleanup(self._stack.close)
        self._stack.enter_context(patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}))
        self._stack.enter_context(patch("fantasy_shared_league_store._anonymous_guest", return_value=False))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = LocalFileSharedLeagueStore(root=Path(tmp.name) / "leagues")
        set_shared_league_store(self.store)
        self.addCleanup(set_shared_league_store, None)
        previous_rooms = rooms._DEFAULT_STORE
        rooms._DEFAULT_STORE = rooms.LocalFileSharedRoomStore(root=Path(tmp.name) / "rooms")
        self.addCleanup(setattr, rooms, "_DEFAULT_STORE", previous_rooms)
        authz.clear_league_copy_decisions()
        invalidate_shared_league_doc_cache()

    @contextmanager
    def request(self, session: dict):
        """A user request by ``session`` (the hosted app always has one)."""
        with patch.object(authz, "current_session", return_value=session):
            yield

    def put(self, doc: dict) -> dict:
        self.store.save(copy.deepcopy(doc))
        invalidate_shared_league_doc_cache()
        return doc

    def stored(self) -> dict:
        return self.store.load(LEAGUE_ID) or {}

    def member_write(self, account: dict, change) -> dict:
        """What the server keeps when ``account`` pushes a copy edited by ``change``."""
        existing = stored_league()
        incoming = copy.deepcopy(existing)
        change(incoming)
        session = signed_in(account)
        with self.request(session):
            return authz.authorize_league_write(session, incoming, existing)


class ForgedLocalMetadataTests(_Base):
    def _member_copy(self, commissioner: str) -> dict:
        return {
            "context_type": CONTEXT_TYPE_REAL_LEAGUE,
            "league_id": LEAGUE_ID,
            "league_context_id": "ctx-member",
            "my_team_name": "Barry",
            "metadata": {"league_id": LEAGUE_ID, "commissioner_user_id": commissioner,
                         "joined_via_live_draft": True, "preassigned_live_draft_owner": True},
            "team_ownership": copy.deepcopy(stored_league()["team_ownership"]),
            "league_rosters": copy.deepcopy(stored_league()["league_rosters"]),
        }

    def test_the_review_reproduction_no_longer_makes_a_member_commissioner(self) -> None:
        from fantasy_league_invites import is_league_commissioner

        self.put(stored_league())
        for forged in (COMMISSIONER["suite"], MEMBER["suite"], ""):
            ctx = self._member_copy(forged)
            with self.request(signed_in(MEMBER)):
                self.assertFalse(is_league_commissioner(ctx), forged)
            with self.request(signed_in(COMMISSIONER)):
                self.assertTrue(is_league_commissioner(ctx), forged)

    def test_a_forged_copy_cannot_cancel_an_invite(self) -> None:
        from fantasy_league_invites import revoke_league_invite

        self.put(stored_league())
        ctx = self._member_copy(MEMBER["suite"])  # the member's copy claims they are commissioner
        session = signed_in(MEMBER)
        with self.request(session), patch("fantasy_league_invites._resolve_user_id", return_value=MEMBER["suite"]):
            ok, err = revoke_league_invite(session, ctx, invite_id="inv_pending")
        self.assertFalse(ok)
        self.assertIn("commissioner", err.lower())
        self.assertEqual(self.stored()["league_invites"][0]["status"], "pending")

    def test_the_commissioner_cancels_on_the_stored_league(self) -> None:
        from fantasy_league_invites import revoke_league_invite

        self.put(stored_league())
        ctx = self._member_copy(COMMISSIONER["suite"])
        session = signed_in(COMMISSIONER)
        with self.request(session), patch("fantasy_league_invites._resolve_user_id", return_value=COMMISSIONER["suite"]), \
                patch("fantasy_league_invites.remove_invite_from_inbox"):
            ok, err = revoke_league_invite(session, ctx, invite_id="inv_pending")
        self.assertTrue(ok, err)
        stored = self.stored()
        self.assertEqual(stored["league_invites"][0]["status"], "revoked")
        self.assertEqual(stored["revision"], 6)

    def test_merging_the_stored_league_replaces_a_forged_local_commissioner(self) -> None:
        from fantasy_shared_league_store import merge_shared_into_context

        merged = merge_shared_into_context(self._member_copy(MEMBER["suite"]), stored_league())
        self.assertEqual(merged["metadata"]["commissioner_user_id"], COMMISSIONER["suite"])


class PrivilegedMutationTests(_Base):
    """Each change a member might push; the server keeps the stored value."""

    def assertKept(self, out: dict, field: str) -> None:
        self.assertEqual(out.get(field), stored_league().get(field), field)

    def test_league_wide_settings_and_identity_are_the_commissioners(self) -> None:
        def change(doc):
            doc["commissioner_user_id"] = MEMBER["suite"]
            doc["league_name"] = "Mine"
            doc["draft_id"] = "x"
            doc["roster_settings"] = {"lineup_format": {"slots": {"C": 9}}}
            doc["metadata"] = {"created_from": "forged"}
            doc["scoring_settings"] = {"HR": 100}

        out = self.member_write(MEMBER, change)
        for field in ("commissioner_user_id", "league_name", "draft_id", "roster_settings", "metadata"):
            self.assertKept(out, field)
        self.assertNotIn("scoring_settings", out)

    def test_members_cannot_send_or_cancel_invites(self) -> None:
        def change(doc):
            doc["league_invites"][0]["status"] = "revoked"
            doc["league_invites"].append({"invite_id": "inv_new", "status": "pending", "invitee_user_id": OUTSIDER["suite"]})

        self.assertKept(self.member_write(MEMBER, change), "league_invites")

    def test_members_cannot_touch_another_team_or_claim_a_second_one(self) -> None:
        def change(doc):
            doc["league_rosters"]["Danny"] = {"players": []}
            doc["league_rosters"]["Open"] = {"players": []}
            doc["team_ownership"]["Danny"] = {"user_id": MEMBER["suite"]}
            doc["team_ownership"]["Open"] = {"user_id": MEMBER["suite"]}
            del doc["team_ownership"]["Barry"]

        out = self.member_write(MEMBER, change)
        self.assertKept(out, "team_ownership")
        self.assertEqual(out["league_rosters"]["Danny"], {"players": ["A"]})
        self.assertEqual(out["league_rosters"]["Open"], {"players": ["C"]})

    def test_members_cannot_finalize_or_reconfigure_the_season(self) -> None:
        def change(doc):
            doc["season_ledger"]["calendar"] = {"first_day": "2031-01-01"}
            doc["season_ledger"]["periods"]["P1"]["finalized_at"] = "2030-04-08"
            doc["season_ledger"]["periods"]["P1"]["lineups"]["Danny"] = {"saved_at": "z"}
            doc["season_ledger"]["periods"]["P0"]["lineups"]["Barry"] = {"saved_at": "late"}

        self.assertKept(self.member_write(MEMBER, change), "season_ledger")

    def test_members_cannot_accept_or_rewrite_someone_elses_trade(self) -> None:
        def change(doc):
            doc["trade_proposals"][0]["recipient_team"] = "Open"
            doc["trade_proposals"].append({"proposal_id": "t2", "status": "pending", "proposer_team": "Danny",
                                           "recipient_team": "Open"})

        out = self.member_write(MEMBER, change)
        self.assertEqual(out["trade_proposals"], stored_league()["trade_proposals"])

    def test_outsiders_and_revoked_invitees_are_refused_outright(self) -> None:
        for account in (OUTSIDER,):  # OUTSIDER holds only a revoked invite
            with self.assertRaises(authz.SharedLeagueWriteRefused):
                self.member_write(account, lambda doc: doc.update(league_rosters={}))
            session = signed_in(account)
            with self.request(session):
                self.assertFalse(authz.may_read_league(session, stored_league()))

    def test_the_commissioner_may_change_league_settings(self) -> None:
        out = self.member_write(COMMISSIONER, lambda doc: doc.update(league_name="Renamed"))
        self.assertEqual(out["league_name"], "Renamed")


class LegitimateMemberWriteTests(_Base):
    def test_a_member_manages_their_own_team(self) -> None:
        def change(doc):
            doc["league_rosters"]["Barry"] = {"players": ["B", "waiver add"]}
            doc["season_ledger"]["periods"]["P1"]["lineups"]["Barry"] = {"saved_at": "now"}
            doc["league_activity"].append({"entry": 2})
            doc["trade_proposals"].append({"proposal_id": "t3", "status": "pending", "proposer_team": "Barry",
                                           "recipient_team": "Danny"})

        out = self.member_write(MEMBER, change)
        self.assertEqual(out["league_rosters"]["Barry"]["players"], ["B", "waiver add"])
        self.assertEqual(out["season_ledger"]["periods"]["P1"]["lineups"]["Barry"], {"saved_at": "now"})
        self.assertIn({"entry": 2}, out["league_activity"])
        self.assertEqual([p["proposal_id"] for p in out["trade_proposals"]], ["t1", "t3"])

    def test_accepting_a_trade_swaps_both_rosters(self) -> None:
        def change(doc):
            doc["trade_proposals"][0]["status"] = "accepted"
            doc["league_rosters"]["Danny"] = {"players": ["B"]}
            doc["league_rosters"]["Barry"] = {"players": ["A"]}

        out = self.member_write(MEMBER, change)  # Barry is the recipient
        self.assertEqual(out["trade_proposals"][0]["status"], "accepted")
        self.assertEqual(out["league_rosters"]["Danny"], {"players": ["B"]})
        self.assertEqual(out["league_rosters"]["Barry"], {"players": ["A"]})

    def test_an_invitee_answers_their_own_invite_and_claims_an_open_team(self) -> None:
        def change(doc):
            doc["league_invites"][0].update(status="accepted", claimed_team="Open", invitee_user_id=OUTSIDER["suite"])
            doc["team_ownership"]["Open"] = {"user_id": INVITEE["suite"], "claim_status": "claimed"}

        out = self.member_write(INVITEE, change)
        self.assertEqual(out["league_invites"][0]["status"], "accepted")
        self.assertEqual(out["league_invites"][0]["invitee_user_id"], INVITEE["suite"])  # who it was for: unchanged
        self.assertEqual(out["team_ownership"]["Open"]["user_id"], INVITEE["suite"])


class InvitationRaceTests(_Base):
    def test_a_write_from_a_stale_read_is_refused_and_changes_nothing(self) -> None:
        self.put(stored_league())
        stale = stored_league()  # read at revision 5
        accept = copy.deepcopy(stale)
        accept["league_invites"][0]["status"] = "accepted"
        revoke = copy.deepcopy(stale)
        revoke["league_invites"][0]["status"] = "revoked"
        save_shared_league(revoke, expected_revision=5)  # the commissioner's cancel lands first
        with self.assertRaises(SharedLeagueConflict):
            save_shared_league(accept, expected_revision=5)
        stored = self.stored()
        self.assertEqual(stored["league_invites"][0]["status"], "revoked")
        self.assertEqual(stored["revision"], 6)

    def test_a_cancel_racing_an_acceptance_reloads_and_reports_it(self) -> None:
        from fantasy_league_invites import revoke_league_invite

        self.put(stored_league())
        session = signed_in(COMMISSIONER)
        ctx = {"context_type": CONTEXT_TYPE_REAL_LEAGUE, "league_id": LEAGUE_ID, "metadata": {"league_id": LEAGUE_ID}}
        real_save = self.store.save_if_revision
        calls = {"n": 0}

        def accept_first(document, *, expected_revision):
            calls["n"] += 1
            if calls["n"] == 1:  # the invitee's acceptance is saved between the cancel's read and write
                accepted = stored_league(revision=6)
                accepted["league_invites"][0]["status"] = "accepted"
                self.store.save(accepted)
            return real_save(document, expected_revision=expected_revision)

        with self.request(session), patch("fantasy_league_invites._resolve_user_id", return_value=COMMISSIONER["suite"]), \
                patch.object(self.store, "save_if_revision", side_effect=accept_first):
            ok, err = revoke_league_invite(session, ctx, invite_id="inv_pending")
        self.assertFalse(ok)
        self.assertIn("no longer pending", err)
        self.assertEqual(self.stored()["league_invites"][0]["status"], "accepted")

    def test_revoked_declined_and_expired_invites_confer_nothing(self) -> None:
        for status in ("revoked", "declined", "expired"):
            doc = stored_league()
            doc["league_invites"][0]["status"] = status
            session = signed_in(INVITEE)
            with self.request(session):
                self.assertFalse(authz.is_league_member_or_invitee(session, doc), status)
        session = signed_in(INVITEE)
        with self.request(session):
            self.assertTrue(authz.is_league_member_or_invitee(session, stored_league()))  # pending still counts


def store_room(code: str, *, host: dict | None, seated: tuple[dict, ...] = (), status: str = "complete") -> None:
    doc = {"room_code": code, "participants": {a["auth"]: {"user_id": a["suite"]} for a in seated},
           "room": {"status": status}, "status": status, "revision": 3}
    if host:
        doc.update(host_participant_id=host["auth"], host_user_id=host["suite"])
        doc["participants"][host["auth"]] = {"user_id": host["suite"]}
    rooms.get_shared_room_store().save(doc)


class RoomHostAuthorityTests(_Base):
    def _create(self, account: dict, code: str, commissioner: str = "") -> dict:
        doc = {"league_id": f"league:room-{code}", "source_room_code": code, "commissioner_user_id": commissioner}
        session = signed_in(account)
        with self.request(session):
            return authz.authorize_league_write(session, doc, None)

    def test_only_the_stored_host_creates_the_rooms_league_and_becomes_commissioner(self) -> None:
        store_room("ROOM01", host=COMMISSIONER, seated=(MEMBER,))
        with self.assertRaises(authz.SharedLeagueWriteRefused) as refused:
            self._create(MEMBER, "ROOM01")
        self.assertIn("not_room_host", str(refused.exception))
        out = self._create(COMMISSIONER, "ROOM01")
        self.assertEqual(out["commissioner_user_id"], COMMISSIONER["suite"])

    def test_a_participant_cannot_name_someone_else_commissioner(self) -> None:
        store_room("ROOM02", host=COMMISSIONER, seated=(MEMBER,))
        with self.assertRaises(authz.SharedLeagueWriteRefused):
            self._create(MEMBER, "ROOM02", commissioner=COMMISSIONER["suite"])
        with self.assertRaises(authz.SharedLeagueWriteRefused) as refused:
            self._create(COMMISSIONER, "ROOM02", commissioner=MEMBER["suite"])
        self.assertIn("commissioner_must_be_creator", str(refused.exception))

    def test_the_host_reconnecting_in_a_new_session_is_still_the_host(self) -> None:
        store_room("ROOM03", host=COMMISSIONER, seated=(MEMBER,))
        reconnected = signed_in(COMMISSIONER)  # a new browser session of the same account
        reconnected["draft_room_participant_id"] = "some-other-local-id"
        with self.request(reconnected):
            self.assertEqual(authz.room_league_creation_error(reconnected, "ROOM03"), "")

    def test_a_room_without_a_recorded_host_is_never_guessed(self) -> None:
        store_room("ROOM04", host=None, seated=(COMMISSIONER, MEMBER))
        for account in (COMMISSIONER, MEMBER):
            with self.assertRaises(authz.SharedLeagueWriteRefused) as refused:
                self._create(account, "ROOM04")
            self.assertIn("room_host_unknown", str(refused.exception))

    def test_the_create_button_explains_why_a_guest_cannot_create(self) -> None:
        from live_draft_shared_league import ROOM_HOST_MESSAGES, room_host_creation_error

        store_room("ROOM05", host=COMMISSIONER, seated=(MEMBER,))
        member = signed_in(MEMBER)
        with self.request(member):
            self.assertEqual(room_host_creation_error(member, "ROOM05"), ROOM_HOST_MESSAGES["not_room_host"])
        host = signed_in(COMMISSIONER)
        with self.request(host):
            self.assertEqual(room_host_creation_error(host, "ROOM05"), "")


class ExistingLeagueCompatibilityTests(_Base):
    def test_a_legacy_room_league_without_a_stored_commissioner_keeps_its_host(self) -> None:
        """As the production Danny-Barry league may be stored: no commissioner id, a room code."""
        store_room("DA9E78", host=COMMISSIONER, seated=(MEMBER,))
        legacy = stored_league(commissioner_user_id="", source_room_code="DA9E78")
        del legacy["commissioner_user_id"]
        self.put(legacy)
        with self.request(signed_in(COMMISSIONER)):
            self.assertTrue(authz.is_league_commissioner(signed_in(COMMISSIONER), legacy))
        member = signed_in(MEMBER)
        with self.request(member):
            self.assertFalse(authz.is_league_commissioner(member, legacy))
            self.assertTrue(authz.may_read_league(member, legacy))
        before = copy.deepcopy(self.stored())
        with self.request(member):
            load_shared_league(LEAGUE_ID)
        self.assertEqual(self.stored(), before)  # reading derives; nothing is written

    def test_a_league_with_neither_commissioner_nor_room_has_no_commissioner_but_keeps_members(self) -> None:
        orphan = stored_league(commissioner_user_id="")
        member = signed_in(MEMBER)
        with self.request(member):
            self.assertFalse(authz.is_league_commissioner(member, orphan))
            self.assertTrue(authz.may_read_league(member, orphan))
        out = self.member_write(MEMBER, lambda doc: doc.update(commissioner_user_id=MEMBER["suite"]))
        self.assertEqual(out["commissioner_user_id"], COMMISSIONER["suite"])  # stored value (fixture)
        orphan_existing = stored_league(commissioner_user_id="")
        incoming = copy.deepcopy(orphan_existing)
        incoming["commissioner_user_id"] = MEMBER["suite"]
        with self.request(member):
            out = authz.authorize_league_write(member, incoming, orphan_existing)
        self.assertEqual(out["commissioner_user_id"], "")  # a member cannot claim an empty commissioner

    def test_a_member_write_keeps_league_ids_teams_and_draft_results(self) -> None:
        existing = stored_league(draft_results=[{"pick": 1}], source_room_code="KEEP01")
        incoming = copy.deepcopy(existing)
        for key in ("league_id", "draft_results", "source_room_code", "draft_id"):
            incoming[key] = "forged"
        session = signed_in(MEMBER)
        with self.request(session):
            out = authz.authorize_league_write(session, incoming, existing)
        self.assertEqual(out["draft_results"], [{"pick": 1}])
        self.assertEqual(out["source_room_code"], "KEEP01")
        self.assertEqual(out["draft_id"], "draft-1")
        self.assertEqual(set(out["team_ownership"]), {"Danny", "Barry", "Open"})


class SignInOffTests(_Base):
    def _off(self):
        return patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "0"})

    def test_sign_in_off_never_acts_on_a_shared_league_in_a_user_request(self) -> None:
        session = signed_in(COMMISSIONER)
        with self._off(), self.request(session):
            self.assertEqual(authz.verified_account_ids(session), [])
            self.assertFalse(authz.may_read_league(session, stored_league()))
            self.assertFalse(authz.is_league_commissioner(session, stored_league()))
            self.assertIn("Sign-in is off", authz.shared_league_sign_in_error(session))
            with self.assertRaises(authz.SharedLeagueWriteRefused) as refused:
                authz.authorize_league_write(session, stored_league(), stored_league())
            self.assertIn("sign_in_required", str(refused.exception))
            self.put(stored_league())
            self.assertIsNone(load_shared_league(LEAGUE_ID))

    def test_signed_out_visitors_are_refused_with_sign_in_on(self) -> None:
        guest = {"_suite_auth_user_id": "", "_suite_cloud_user_id": "fallback-account"}
        with self.request(guest):
            self.assertEqual(authz.shared_league_sign_in_error(guest), "Sign in to use Shared Leagues.")
            with self.assertRaises(authz.SharedLeagueWriteRefused):
                authz.authorize_league_write(guest, {"league_id": "league:new"}, None)

    def test_claiming_needs_sign_in_only_for_a_shared_league(self) -> None:
        from fantasy_league_team_ownership import _shared_claim_error

        self.put(stored_league())
        shared_ctx = {"context_type": CONTEXT_TYPE_REAL_LEAGUE, "league_id": LEAGUE_ID, "metadata": {"league_id": LEAGUE_ID}}
        private_ctx = {"context_type": CONTEXT_TYPE_REAL_LEAGUE, "league_id": "league:private-only",
                       "metadata": {"league_id": "league:private-only"}}
        session = signed_in(MEMBER)
        with self._off(), self.request(session):
            self.assertTrue(_shared_claim_error(session, shared_ctx))
            self.assertEqual(_shared_claim_error(session, private_ctx), "")


class RoomWriteTests(_Base):
    def _room(self, status: str = "in_progress") -> dict:
        return {"room_code": "PICK01", "host_participant_id": COMMISSIONER["auth"], "host_user_id": COMMISSIONER["suite"],
                "participants": {COMMISSIONER["auth"]: {}, MEMBER["auth"]: {}}, "room": {"status": status}, "status": status}

    def refusal(self, account: dict, new_status: str, old_status: str = "in_progress") -> str:
        session = signed_in(account)
        with self.request(session):
            return authz.room_pick_write_refusal(session, self._room(old_status), {"status": new_status})

    def test_room_write_rules(self) -> None:
        self.assertEqual(self.refusal(MEMBER, "in_progress"), "")          # a seated pick
        self.assertEqual(self.refusal(MEMBER, "complete"), "")             # the final pick
        self.assertEqual(self.refusal(MEMBER, "paused"), "status_host_only")
        self.assertEqual(self.refusal(MEMBER, "in_progress", "paused"), "status_host_only")  # resume
        self.assertEqual(self.refusal(OUTSIDER, "in_progress"), "not_seated")
        self.assertEqual(self.refusal(COMMISSIONER, "paused"), "")

    def test_commit_refuses_and_writes_nothing(self) -> None:
        store = MagicMock()
        stored = {**self._room(), "revision": 4}
        session = signed_in(OUTSIDER)
        session[rooms.ACTIVE_SHARED_ROOM_CODE_KEY] = "PICK01"
        with self.request(session), patch.object(rooms, "load_shared_room_document", return_value=stored), \
                patch.object(rooms, "publish_shared_room_runtime"):
            ok, doc = rooms.commit_shared_room_pick(session, {"status": "in_progress"}, store=store)
        self.assertFalse(ok)
        self.assertIs(doc, stored)
        store.save_if_revision.assert_not_called()
        self.assertEqual(session["_shared_room_write_refused"]["reason"], "not_seated")


class AtomicCompareAndSwapTests(unittest.TestCase):
    def test_the_supabase_store_patches_only_the_expected_revision(self) -> None:
        from fantasy_shared_league_supabase_store import SupabaseSharedLeagueStore

        store = SupabaseSharedLeagueStore.__new__(SupabaseSharedLeagueStore)
        doc = {"league_id": LEAGUE_ID, "revision": 6}
        with patch("fantasy_shared_league_supabase_store._request", return_value=[]) as request, \
                patch.object(SupabaseSharedLeagueStore, "load", return_value={"league_id": LEAGUE_ID, "revision": 7}):
            ok, current = store.save_if_revision(doc, expected_revision=5)
        self.assertFalse(ok)
        self.assertEqual(current["revision"], 7)
        method, _table = request.call_args.args[:2]
        self.assertEqual(method, "PATCH")
        self.assertEqual(request.call_args.kwargs["params"], {"league_id": f"eq.{LEAGUE_ID}", "revision": "eq.5"})
        self.assertEqual(request.call_args.kwargs["prefer"], "return=representation")


class InstallScriptTests(unittest.TestCase):
    def test_install_scripts_never_reopen_the_tables(self) -> None:
        root = Path(__file__).resolve().parents[1] / "scripts" / "sql"
        for name in ("baseball_shared_leagues.sql", "baseball_shared_draft_rooms.sql"):
            sql = "\n".join(
                line for line in (root / name).read_text(encoding="utf-8").splitlines() if not line.strip().startswith("--")
            ).lower()
            self.assertIn("enable row level security", sql, name)
            self.assertIn("from anon, authenticated", sql, name)
            self.assertNotIn("to anon", sql, name)
            self.assertNotIn("to authenticated", sql, name)
            self.assertNotIn("disable row level security", sql, name)


if __name__ == "__main__":
    unittest.main()
