"""Stored copies of a Shared League an account may not see: hidden and not refreshed, never deleted
or rewritten (owner decision, 2026-11-02).

Covers: the access decision (member / not a member / league unreadable / not a Shared League /
signed out), the server-side refusal of refreshes and writes, the display filters (Library cards,
the active league for fantasy pages, the player page lists), and that the sign-in, Library and
page-entry flows leave every stored record byte-identical.
"""

from __future__ import annotations

import copy
import unittest
from unittest.mock import MagicMock, patch

import fantasy_shared_league_authz as authz
from draft_archive_state import ACTIVE_DRAFT_ARCHIVE_KEY, list_draft_archives
from draft_archive_visibility import (
    list_library_cards_for_display,
    list_visible_draft_archives,
    prune_invisible_shared_league_state,
    sanitize_workflow_library_for_account,
)
from fantasy_league_context import (
    ensure_fantasy_league_context_state,
    get_active_league_context,
    list_league_contexts,
    schedule_active_context_resync,
)
from fantasy_league_identity import resolve_canonical_league_id
from tests.test_draft_archive_visibility import _as_user, _auth_session, _seed_daniel_shared_league

STORED_KEYS = ("draft_archive_teams", "fantasy_league_context_state", ACTIVE_DRAFT_ARCHIVE_KEY, "_deleted_draft_archive_ids")


def _league_and_sessions(variant: str = "imported"):
    """variant "imported": an uploaded league with an accepted invite (the deployed prune keeps the
    copy and the overlay rewrites its team). "live_no_invite": a Live Draft copy without a stored
    commissioner and a league with no accepted invite (the deployed prune assigns this account as
    commissioner, or deletes the copy)."""
    owner = _auth_session(user_id="user:daniel", external_id="daniel", workspace="daniel")
    _seed_daniel_shared_league(owner)
    league_id = resolve_canonical_league_id(list_league_contexts(owner)[0])
    shared = {
        "league_id": league_id,
        "commissioner_user_id": owner["_suite_auth_user_id"],
        "team_ownership": {"Donny": {"user_id": owner["_suite_auth_user_id"]}},
        "league_invites": [
            {"invite_id": "i1", "status": "accepted", "invitee_user_id": "uuid-barry", "claimed_team": "Barry Team"}
        ],
        "league_rosters": {"Donny": {"players": [{"Player": "Fresh Data"}]}},
    }
    other = _auth_session(user_id="user:coakley", external_id="coakley11", workspace="coakley11")
    for key in ("draft_archive_teams", "fantasy_league_context_state"):
        other[key] = copy.deepcopy(owner.get(key))
    if variant == "live_no_invite":
        shared["league_invites"] = []
        store = ensure_fantasy_league_context_state(other)
        for ctx in (store.get("contexts") or {}).values():
            meta = dict(ctx.get("metadata") or {})
            meta["created_from"] = "live_draft"
            meta.pop("commissioner_user_id", None)
            ctx["metadata"] = meta
    # The unrelated account even has the copy selected as its Active Draft.
    draft_id = str(list_draft_archives(other)[0].get("draft_id"))
    other[ACTIVE_DRAFT_ARCHIVE_KEY] = draft_id
    ctx_id = str(list_league_contexts(other)[0].get("league_context_id"))
    ensure_fantasy_league_context_state(other)["active_league_context_id"] = ctx_id
    # The existing one-time legacy migration index (account-wide bookkeeping, not a league copy;
    # deployed behaviour) is settled first, so the tests can require that nothing else changes.
    from fantasy_league_context import migrate_legacy_archives_to_contexts

    migrate_legacy_archives_to_contexts(other)
    return owner, other, shared


def _stored(session) -> dict:
    """Every stored record, except the one field allowed to move: the account-wide legacy
    migration scan time, re-stamped whenever that existing migration runs (deployed behaviour for
    every account; not part of any league copy)."""
    snap = copy.deepcopy({k: session.get(k) for k in STORED_KEYS})
    ((snap.get("fantasy_league_context_state") or {}).get("legacy_migration") or {}).pop("archives_scanned_at", None)
    return snap


def _sign_in_enabled():
    """The hosted configuration: sign-in on, so separate accounts exist."""
    return patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"})


class _Base(unittest.TestCase):
    VARIANT = "imported"

    def setUp(self) -> None:
        self._auth = _sign_in_enabled()
        self._auth.start()
        self.addCleanup(self._auth.stop)
        authz.clear_league_copy_decisions()
        self.owner, self.other, self.shared = _league_and_sessions(self.VARIANT)
        self._found = patch.object(authz, "checked_load", return_value=(authz.LOAD_FOUND, self.shared))
        self._found.start()

    def tearDown(self) -> None:
        self._found.stop()
        authz.clear_league_copy_decisions()


class AccessDecisionTests(_Base):
    def _ctx(self, session):
        return list_league_contexts(session)[0]

    def test_member_allowed_and_unrelated_account_refused(self) -> None:
        self.assertEqual(authz.league_copy_access(self.owner, self._ctx(self.owner)), authz.COPY_ALLOWED)
        self.assertEqual(authz.league_copy_access(self.other, self._ctx(self.other)), authz.COPY_REFUSED)

    def test_invitee_allowed(self) -> None:
        barry = _auth_session(user_id="b", external_id="barry", workspace="barry")
        barry["_suite_auth_user_id"] = "uuid-barry"
        barry["fantasy_league_context_state"] = copy.deepcopy(self.other["fantasy_league_context_state"])
        self.assertEqual(authz.league_copy_access(barry, self._ctx(barry)), authz.COPY_ALLOWED)

    def test_unreadable_league_is_hidden_not_granted(self) -> None:
        with patch.object(authz, "checked_load", return_value=(authz.LOAD_ERROR, None)):
            self.assertTrue(authz.league_copy_hidden(self.owner, self._ctx(self.owner)))

    def test_not_a_shared_league_is_unaffected(self) -> None:
        with patch.object(authz, "checked_load", return_value=(authz.LOAD_MISSING, None)):
            self.assertFalse(authz.league_copy_hidden(self.other, self._ctx(self.other)))
        mock_ctx = {"context_type": "mock_draft", "league_id": "x"}
        self.assertEqual(authz.league_copy_access(self.other, mock_ctx), authz.COPY_NOT_SHARED)

    def test_no_signed_in_identity_is_refused_without_fallback(self) -> None:
        signed_out = copy.deepcopy(self.other)
        for key in ("_suite_auth_user_id", "_suite_cloud_user_id"):
            signed_out.pop(key, None)
        self.assertEqual(authz.league_copy_access(signed_out, self._ctx(signed_out)), authz.COPY_REFUSED)


class RefreshRefusedTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        # A unit test has no Streamlit session, which the existing guest check treats as a
        # signed-out guest (and returns before any refresh). These are signed-in accounts.
        guest = patch("fantasy_shared_league_store._anonymous_guest", return_value=False)
        guest.start()
        self.addCleanup(guest.stop)

    def test_unrelated_account_gets_no_fresh_league_data(self) -> None:
        from fantasy_shared_league_store import sync_context_with_shared_store

        ctx = list_league_contexts(self.other)[0]
        before = _stored(self.other)
        with patch("fantasy_shared_league_store.load_shared_league", return_value=self.shared), patch(
            "fantasy_league_context.upsert_league_context"
        ) as upsert:
            out = sync_context_with_shared_store(self.other, ctx, force=True)
        upsert.assert_not_called()
        self.assertIs(out, ctx)
        self.assertNotIn("Fresh Data", str(out.get("league_rosters")))
        self.assertEqual(_stored(self.other), before)

    def test_member_still_refreshes(self) -> None:
        from fantasy_shared_league_store import sync_context_with_shared_store

        ctx = list_league_contexts(self.owner)[0]
        with _as_user("user:daniel"), patch("fantasy_shared_league_store.load_shared_league", return_value=self.shared):
            out = sync_context_with_shared_store(self.owner, ctx, force=True)
        self.assertIn("Fresh Data", str(out.get("league_rosters")))

    def test_lineup_format_refresh_refused(self) -> None:
        from fantasy_league_lineup_format import hydrate_lineup_format_from_shared

        ctx = list_league_contexts(self.other)[0]
        ctx["roster_settings"] = {}
        shared = {**self.shared, "roster_settings": {"lineup_format": {"C": 1}}}
        before = _stored(self.other)
        with patch("fantasy_shared_league_store.load_shared_league", return_value=shared), patch(
            "fantasy_league_lineup_format.upsert_league_context"
        ) as upsert:
            out = hydrate_lineup_format_from_shared(self.other, ctx)
        upsert.assert_not_called()
        self.assertIs(out, ctx)
        self.assertEqual(_stored(self.other), before)


class DisplayHiddenTests(_Base):
    def test_library_cards_hide_the_copy_but_retention_still_keeps_it(self) -> None:
        with patch("fantasy_shared_league_store.load_shared_league", return_value=self.shared):
            self.assertEqual(list_library_cards_for_display(self.other), [])
            self.assertEqual(len(list_visible_draft_archives(self.other)), 1)  # retention rules unchanged
            with _as_user("user:daniel"):
                self.assertEqual(len(list_library_cards_for_display(self.owner)), 1)

    def test_fantasy_pages_see_no_active_league_and_the_selection_is_kept(self) -> None:
        before = _stored(self.other)
        self.assertIsNone(get_active_league_context(self.other))
        self.assertIsNotNone(get_active_league_context(self.other, respect_source_priority=False))
        self.assertEqual(_stored(self.other), before)

    def test_member_still_sees_the_active_league(self) -> None:
        ensure_fantasy_league_context_state(self.owner)["active_league_context_id"] = str(
            list_league_contexts(self.owner)[0].get("league_context_id")
        )
        with _as_user("user:daniel"):
            self.assertIsNotNone(get_active_league_context(self.owner))

    def test_player_page_lists_skip_the_copy(self) -> None:
        from player_trade_context import collect_player_roster_contexts

        archive = list_draft_archives(self.other)[0]
        player = next(
            (str(p.get("Player") or p.get("player_name") or p.get("Name") or "") for p in archive.get("players") or []),
            "",
        )
        self.assertTrue(player)
        self.assertEqual(collect_player_roster_contexts(self.other, player), [])
        # The owner is genuinely signed in. This fixture has no real tokens, so the board's sign-in
        # re-check (restore_auth_session) would sign it out, and a signed-out session now sees no
        # Shared League at all (2026-11-05 security fixes: a verified sign-in is required).
        with _as_user("user:daniel"), patch("suite_auth.ensure_authenticated_session_hydrated", return_value=True):
            self.assertTrue(collect_player_roster_contexts(self.owner, player))

    def test_activation_prompt_reports_unavailable_instead_of_rendering_the_league(self) -> None:
        from fantasy_context_ui import render_fantasy_context_activation_prompt

        st = MagicMock()
        st.columns.return_value = (MagicMock(), MagicMock())
        self.assertFalse(render_fantasy_context_activation_prompt(st, self.other))
        self.assertIn("isn't available", str(st.info.call_args))


class StoredDataUntouchedTests(_Base):
    def test_sign_in_library_and_page_entry_flows_change_nothing_stored(self) -> None:
        from fantasy_shared_league_store import sync_context_with_shared_store
        from saved_draft_library_selection import prepare_saved_draft_library_active_selection
        from fantasy_league_context import PENDING_ARCHIVE_ACTIVATION_KEY, migrate_legacy_archives_to_contexts
        from workflow_persist_guard import restore_active_draft_archive_selection

        # Page entry always runs the existing legacy migration first (deployed behaviour for every
        # account; it records already-migrated archive ids). Settle it, then require no change at all.
        migrate_legacy_archives_to_contexts(self.other)
        before = _stored(self.other)
        with _as_user("user:coakley"), patch(
            "fantasy_shared_league_store.load_shared_league", return_value=self.shared
        ):
            pruned = prune_invisible_shared_league_state(self.other)
            self.assertEqual((pruned["archives_removed"], pruned["contexts_removed"]), (0, 0))
            sanitize_workflow_library_for_account(self.other, persist_cleanup=False)
            restore_active_draft_archive_selection(self.other, cloud_state={}, disk_state={}, respect_canonical_membership=True)
            prepare_saved_draft_library_active_selection(self.other)
            self.assertFalse(schedule_active_context_resync(self.other))
            get_active_league_context(self.other)
            list_library_cards_for_display(self.other)
            sync_context_with_shared_store(self.other, list_league_contexts(self.other)[0], force=True)
        self.assertEqual(_stored(self.other), before)
        self.assertNotIn(PENDING_ARCHIVE_ACTIVATION_KEY, self.other)


class LibraryPageTests(unittest.TestCase):
    """The real Saved Draft Library page, rendered for the unrelated account and for the owner."""

    def _render(self, session: dict, shared: dict):
        from pathlib import Path

        from streamlit.testing.v1 import AppTest

        authz.clear_league_copy_decisions()
        fixture = Path(__file__).resolve().parent / "fixtures" / "library_hidden_copy_app.py"
        at = AppTest.from_file(str(fixture), default_timeout=120)
        for key, value in session.items():
            at.session_state[key] = copy.deepcopy(value)
        at.session_state["_fx_shared"] = copy.deepcopy(shared)
        with _sign_in_enabled():
            at.run()
        self.assertFalse(at.exception, [str(e.value)[:300] for e in at.exception])
        return at

    @staticmethod
    def _page_text(at) -> str:
        parts = [str(getattr(el, "value", "")) for el in list(at.markdown) + list(at.info) + list(at.caption)]
        parts += [str(getattr(el, "label", "")) for el in list(at.button) + list(at.expander)]
        return "\n".join(parts)

    def test_unrelated_account_sees_no_card_and_nothing_stored_changes(self) -> None:
        for variant in ("imported", "live_no_invite"):
            with self.subTest(variant=variant):
                self._unrelated_account_page(variant)

    def _unrelated_account_page(self, variant: str) -> None:
        owner, other, shared = _league_and_sessions(variant)
        draft_name = str(list_draft_archives(other)[0].get("draft_name") or "")
        at = self._render(other, shared)
        after = _stored({k: at.session_state[k] for k in STORED_KEYS if k in at.session_state})
        self.assertEqual(after, _stored(other))
        self.assertEqual(at.session_state["_fx_save_reasons"], [])
        text = self._page_text(at)
        self.assertNotIn(draft_name, text)
        self.assertNotIn("Barry Team", text)
        self.assertIn("No active draft yet", text)

    def test_owner_still_sees_the_league(self) -> None:
        owner, _other, shared = _league_and_sessions()
        ensure_fantasy_league_context_state(owner)["active_league_context_id"] = str(
            list_league_contexts(owner)[0].get("league_context_id")
        )
        owner[ACTIVE_DRAFT_ARCHIVE_KEY] = str(list_draft_archives(owner)[0].get("draft_id"))
        draft_name = str(list_draft_archives(owner)[0].get("draft_name") or "")
        at = self._render(owner, shared)
        self.assertIn(draft_name, self._page_text(at))


class StoredDataUntouchedLiveDraftCopyTests(StoredDataUntouchedTests):
    VARIANT = "live_no_invite"


class SignInOffTests(unittest.TestCase):
    """With sign-in off the app has one configured account: nothing is hidden from it."""

    def test_nothing_hidden_when_there_are_no_separate_accounts(self) -> None:
        authz.clear_league_copy_decisions()
        _owner, other, shared = _league_and_sessions()
        with patch.dict("os.environ", {"SUITE_AUTH_ENABLED": ""}), patch.object(
            authz, "checked_load", return_value=(authz.LOAD_FOUND, shared)
        ), patch("suite_auth.is_auth_enabled", return_value=False):
            self.assertFalse(authz.league_copy_hidden(other, list_league_contexts(other)[0]))
            self.assertTrue(authz.may_read_league(other, shared))


class WritesRefusedServerSideTests(_Base):
    def test_unrelated_account_write_refused(self) -> None:
        with self.assertRaises(authz.SharedLeagueWriteRefused):
            authz.authorize_league_write(self.other, dict(self.shared), self.shared)

    def test_a_failed_read_is_not_permission_to_create(self) -> None:
        with patch.object(authz, "checked_load", return_value=(authz.LOAD_ERROR, None)):
            with self.assertRaises(authz.SharedLeagueWriteRefused):
                authz.authorize_league_write(self.owner, {"league_id": self.shared["league_id"]}, None)

    def test_a_write_built_without_the_stored_league_is_refused_even_for_the_commissioner(self) -> None:
        with self.assertRaises(authz.SharedLeagueWriteRefused):
            authz.authorize_league_write(self.owner, {"league_id": self.shared["league_id"]}, None)

    def test_a_genuinely_new_league_may_be_created(self) -> None:
        with patch.object(authz, "checked_load", return_value=(authz.LOAD_MISSING, None)):
            doc = {"league_id": "league:new"}
            out = authz.authorize_league_write(self.owner, doc, None)
        # Allowed, and a new league's commissioner is its creator (2026-11-05 security fixes).
        self.assertEqual(out["league_id"], "league:new")
        self.assertIn(out["commissioner_user_id"], authz.verified_account_ids(self.owner))

    def test_supabase_store_reports_a_failed_request_as_error_and_no_config_as_missing(self) -> None:
        from fantasy_shared_league_supabase_store import SupabaseSharedLeagueStore

        store = SupabaseSharedLeagueStore.__new__(SupabaseSharedLeagueStore)
        with patch("suite_storage_supabase.get_cloud_config", return_value=object()), patch(
            "fantasy_shared_league_supabase_store._request", side_effect=RuntimeError("timeout")
        ):
            self.assertEqual(store.load_checked("league:x"), ("error", None))
        with patch("suite_storage_supabase.get_cloud_config", return_value=None):
            self.assertEqual(store.load_checked("league:x"), ("missing", None))


if __name__ == "__main__":
    unittest.main()
