"""Shared League invite discovery with the hosted account arrangement (2026-11-03 acceptance).

Danny created "Danny vs Barry League" and invited username coakley11 (invite pending); Barry,
signed in to his own account, saw no invite. Hosted accounts carry two ids: the Supabase Auth id
(_suite_auth_user_id) and the suite_users id (_suite_cloud_user_id, get_account_user_id), plus a
username (external id) and an owned workspace. The ids below are sanitized placeholders.

Found:
1. A session reused its first read of baseball_shared_leagues for as long as it lived, and the
   invite scan was keyed only by the invitee's own identity and save revision. An invite sent
   while the invitee was already signed in never showed in that session.
2. The username lookup called suite_storage_supabase.list_suite_users_by_external_ids, which no
   longer exists; the error was swallowed and invites were stored with no account id, matched only
   by the typed text. With sign-in on, an invite now records the account id or is refused.
"""

from __future__ import annotations

import json
import types
import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import fantasy_shared_league_authz as authz
from fantasy_league_identity import resolve_canonical_league_id
from fantasy_league_invites import create_league_invite, list_pending_invites_for_session
from fantasy_shared_league_store import load_shared_league
import tests.test_fantasy_league_invites as _invite_suite  # module import: its tests are not re-collected here
from tests.test_fantasy_trade_proposals import _as_user

DANNY = {"auth": "auth-danny-0001", "suite": "suite-danny-0001", "username": "daniel", "workspace": "daniel"}
BARRY = {"auth": "auth-barry-0002", "suite": "suite-barry-0002", "username": "coakley11", "workspace": "coakley11"}
SUITE_USERS = [
    {"id": DANNY["suite"], "external_id": "daniel", "email": "danny@example.com"},
    {"id": BARRY["suite"], "external_id": "coakley11", "email": "barry@example.com"},
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


class _Case(unittest.TestCase):
    setUp = _invite_suite.TestFantasyLeagueInvites.setUp
    tearDown = _invite_suite.TestFantasyLeagueInvites.tearDown
    _write_registry = _invite_suite.TestFantasyLeagueInvites._write_registry
    _workspace = _invite_suite.TestFantasyLeagueInvites._workspace

    def on(self) -> ExitStack:
        """Sign-in on, as hosted. The hosted registry file is on the app's own disk and does not
        know Barry, so the username is resolved from suite_users."""
        authz.clear_league_copy_decisions()
        stack = ExitStack()
        stack.enter_context(patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}))
        stack.enter_context(patch("fantasy_shared_league_store._anonymous_guest", return_value=False))
        stack.enter_context(patch("suite_storage_supabase.find_user_rows", side_effect=_find_user_rows))
        return stack

    def league(self) -> tuple[dict, str]:
        self._write_registry({"by_owner": {}})
        context = _invite_suite._seed_imported_league({}, user_id=DANNY["suite"], workspace=DANNY["workspace"])
        return context, resolve_canonical_league_id(context)

    @contextmanager
    def as_account(self, account: dict):
        with _as_user(account["suite"]), self._workspace(account["workspace"]), patch(
            "fantasy_league_invites._resolve_external_id", return_value=account["username"]
        ):
            yield

    def invite(self, context: dict, target: str = "coakley11") -> tuple[dict | None, str]:
        with self.on(), self.as_account(DANNY):
            return create_league_invite({}, context, invitee_target=target)

    def pending(self, session: dict, account: dict) -> list[dict]:
        with self.on(), self.as_account(account):
            return list_pending_invites_for_session(session)


class InviteeIdentityTests(_Case):
    def test_barry_sees_the_invite_with_auth_and_suite_ids_that_differ(self) -> None:
        context, league_id = self.league()
        invite, err = self.invite(context)
        self.assertEqual(err, "")
        rows = self.pending(_signed_in(BARRY), BARRY)
        self.assertEqual([(r["invite_id"], r["league_id"]) for r in rows], [(invite["invite_id"], league_id)])

    def test_the_invite_records_barrys_account_id_not_only_the_typed_username(self) -> None:
        context, league_id = self.league()
        invite, err = self.invite(context)
        self.assertEqual(err, "")
        self.assertEqual(invite["invitee_user_id"], BARRY["suite"])
        with self.on():
            stored = load_shared_league(league_id)
        stored_invite = next(i for i in stored["league_invites"] if i["invite_id"] == invite["invite_id"])
        self.assertEqual(
            (stored_invite["invitee_user_id"], stored_invite["invitee_external_id"], stored_invite["status"]),
            (BARRY["suite"], "coakley11", "pending"),
        )

    def test_barry_is_found_by_account_id_alone(self) -> None:
        # Neither the typed username nor the workspace matches; only the recorded account id does.
        context, _league_id = self.league()
        self.invite(context)
        renamed = dict(BARRY, workspace="barry_ws2", username="barry_renamed")
        with patch("fantasy_league_invites._read_inbox", side_effect=lambda _ws: []):
            self.assertEqual(len(self.pending(_signed_in(renamed), renamed)), 1)

    def test_an_invite_to_another_accounts_username_is_not_shown_to_barry(self) -> None:
        # If "coakley11" is not Barry's username, the invite is addressed to that other account.
        context, _league_id = self.league()
        self.invite(context)
        other_barry = {"auth": "auth-barry-9", "suite": "suite-barry-9", "username": "barry_ab12cd34",
                       "workspace": "barry_ab12cd34"}
        self.assertEqual(self.pending(_signed_in(other_barry), other_barry), [])

    def test_an_unknown_username_is_refused_and_nothing_is_stored(self) -> None:
        context, league_id = self.league()
        invite, err = self.invite(context, "coakley111")
        self.assertIsNone(invite)
        self.assertIn("No Baseball account has the username 'coakley111'", err)
        with self.on():
            stored = load_shared_league(league_id) or {}
        self.assertEqual(stored.get("league_invites") or [], [])

    def test_a_failed_username_lookup_is_refused_never_stored_without_an_account(self) -> None:
        context, _league_id = self.league()
        with self.on(), self.as_account(DANNY), patch(
            "suite_storage_supabase.find_user_rows", side_effect=RuntimeError("store down")
        ):
            invite, err = create_league_invite({}, context, invitee_target="coakley11")
        self.assertIsNone(invite)
        self.assertIn("Couldn't check that username", err)

    def test_danny_still_cannot_invite_himself(self) -> None:
        context, _league_id = self.league()
        invite, err = self.invite(context, "daniel")
        self.assertIsNone(invite)
        self.assertIn("cannot invite your own account", err)

    def test_a_stranger_never_sees_the_invite(self) -> None:
        context, _league_id = self.league()
        self.invite(context)
        stranger = {"auth": "auth-x", "suite": "suite-x", "username": "mallory", "workspace": "mallory"}
        self.assertEqual(self.pending(_signed_in(stranger), stranger), [])


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
