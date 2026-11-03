"""Live Draft Library saves are kept (hotfix, 2026-11-02).

On ebcb540 a signed-in account's "Save to Draft Library" Live Draft entry recorded no owner, failed
Library visibility, and the next Library clean-up (Library visit, sign-in) deleted it and marked it
deleted. Now:
- a new save records the saving account (session id, cloud account id first) as owner of its team;
- the clean-up never deletes or marks anything; entries an account may not see stay hidden;
- legacy ownerless entries are kept exactly as stored, hidden, and not rewritten by repairs;
- existing deletion markers are left alone; nothing is resurrected.
All with sign-in on (the hosted configuration).
"""

from __future__ import annotations

import contextlib
import copy
import unittest
from unittest import mock

from draft_archive_state import ACTIVE_DRAFT_ARCHIVE_KEY, DELETED_DRAFT_ARCHIVE_IDS_KEY, list_draft_archives
from draft_archive_visibility import (
    list_visible_draft_archives,
    prune_invisible_shared_league_state,
    sanitize_workflow_library_for_account,
)
from fantasy_league_context import ensure_fantasy_league_context_state, get_league_context_for_archive, save_live_draft_league_context
from fantasy_league_team_ownership import get_team_ownership
from tests.test_fantasy_league_context import _live_room_fixture
from tests.test_fantasy_trade_proposals import _as_user

STORED = ("draft_archive_teams", "fantasy_league_context_state", ACTIVE_DRAFT_ARCHIVE_KEY, DELETED_DRAFT_ARCHIVE_IDS_KEY)


def signed_in(account: str, *, cloud_id: str = "", auth_id: str = "") -> dict:
    return {"_suite_auth_session": True, "_suite_auth_user_id": auth_id or f"auth-{account}",
            "_suite_cloud_user_id": cloud_id or f"cloud-{account}", "_suite_auth_external_id": account,
            "_suite_owned_workspace_id": account, "_suite_active_workspace_id": account}


def stored(session: dict) -> dict:
    snap = copy.deepcopy({k: session.get(k) for k in STORED})
    ((snap.get("fantasy_league_context_state") or {}).get("legacy_migration") or {}).pop("archives_scanned_at", None)
    return snap


class _SignedIn(unittest.TestCase):
    def setUp(self) -> None:
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}))
        stack.enter_context(mock.patch("suite_auth.is_authenticated", return_value=True))
        self.stack = stack

    def acting(self, session: dict):
        """The app's account-id helper returns this session's cloud id (as in the hosted app)."""
        return _as_user(str(session["_suite_cloud_user_id"]))

    def save(self, session: dict, team: str = "Daniel") -> dict:
        with self.acting(session):
            entry, _ctx = save_live_draft_league_context(session, _live_room_fixture(), my_team_name=team, save_only=True)
        return entry

    def legacy_ownerless(self, session: dict) -> dict:
        """An entry saved before the hotfix: no owner recorded."""
        entry = self.save(session)
        ctx_id = str(entry["league_context_id"])
        ctx = ensure_fantasy_league_context_state(session)["contexts"][ctx_id]
        meta = dict(ctx.get("metadata") or {})
        meta.pop("team_ownership", None)
        ctx["metadata"] = meta
        ctx.pop("team_ownership", None)
        return entry


class NewSavesTests(_SignedIn):
    def test_a_new_live_draft_save_records_the_saving_account_and_survives_the_cleanup(self) -> None:
        session = signed_in("danny")
        entry = self.save(session)
        ctx = get_league_context_for_archive(session, entry)
        self.assertEqual(get_team_ownership(ctx)["Daniel"]["user_id"], "cloud-danny")  # cloud account id first
        with self.acting(session):
            prune_invisible_shared_league_state(session)
            sanitize_workflow_library_for_account(session, persist_cleanup=False)
            self.assertEqual([e["draft_id"] for e in list_visible_draft_archives(session)], [entry["draft_id"]])

    def test_without_a_signed_in_id_no_owner_is_recorded(self) -> None:
        session = {}
        with _as_user("user:configured-default"):  # the deployment's fallback account must not become owner
            entry, _ = save_live_draft_league_context(session, _live_room_fixture(), my_team_name="Daniel", save_only=True)
        self.assertEqual(get_team_ownership(get_league_context_for_archive(session, entry)), {})

    def test_another_account_holding_the_entry_does_not_see_it(self) -> None:
        danny = signed_in("danny")
        self.save(danny)
        mallory = signed_in("mallory")
        for key in ("draft_archive_teams", "fantasy_league_context_state"):
            mallory[key] = copy.deepcopy(danny[key])
        with self.acting(mallory):
            self.assertEqual(list_visible_draft_archives(mallory), [])


class LegacyOwnerlessEntriesTests(_SignedIn):
    def test_an_ownerless_entry_is_kept_unchanged_hidden_and_unmarked(self) -> None:
        session = signed_in("danny")
        self.legacy_ownerless(session)
        before = stored(session)
        with self.acting(session):
            result = prune_invisible_shared_league_state(session)
            sanitize_workflow_library_for_account(session, persist_cleanup=False)
            self.assertEqual(list_visible_draft_archives(session), [])  # isolation unchanged: not shown
        self.assertEqual((result["archives_removed"], result["contexts_removed"]), (0, 0))
        self.assertEqual(result["archives_hidden"], 1)
        self.assertEqual(stored(session), before)  # kept exactly as stored, no deletion marker

    def test_an_ownerless_active_entry_stops_being_the_active_draft_but_is_kept(self) -> None:
        session = signed_in("danny")
        entry = self.legacy_ownerless(session)
        session[ACTIVE_DRAFT_ARCHIVE_KEY] = entry["draft_id"]
        ensure_fantasy_league_context_state(session)["active_league_context_id"] = entry["league_context_id"]
        with self.acting(session):
            prune_invisible_shared_league_state(session)
        self.assertNotIn(ACTIVE_DRAFT_ARCHIVE_KEY, session)
        self.assertFalse(ensure_fantasy_league_context_state(session).get("active_league_context_id"))
        self.assertEqual(len(list_draft_archives(session)), 1)

    def test_repairs_never_delete_or_unhide_an_ownerless_entry(self) -> None:
        # The origin repairs still correct labels on stored entries (as before the hotfix); they
        # never delete an entry, add a deletion marker, or record an owner.
        from fantasy_league_context import repair_archive_draft_types_from_contexts

        session = signed_in("danny")
        entry = self.legacy_ownerless(session)
        with self.acting(session):
            repair_archive_draft_types_from_contexts(session)
            prune_invisible_shared_league_state(session)
            self.assertEqual(list_visible_draft_archives(session), [])
        self.assertEqual([e["draft_id"] for e in list_draft_archives(session)], [entry["draft_id"]])
        self.assertFalse(session.get(DELETED_DRAFT_ARCHIVE_IDS_KEY))
        self.assertEqual(get_team_ownership(get_league_context_for_archive(session, entry)), {})

    def test_the_player_page_does_not_list_an_ownerless_entry(self) -> None:
        from player_trade_context import collect_player_roster_contexts

        session = signed_in("danny")
        self.legacy_ownerless(session)
        with self.acting(session):
            self.assertEqual(collect_player_roster_contexts(session, "Aaron Judge"), [])
        owned = signed_in("barry")
        self.save(owned)
        with self.acting(owned):
            self.assertTrue(collect_player_roster_contexts(owned, "Aaron Judge"))


class DeletionMarkersTests(_SignedIn):
    def test_existing_markers_are_left_alone_by_saves_and_cleanup(self) -> None:
        session = signed_in("danny")
        session[DELETED_DRAFT_ARCHIVE_IDS_KEY] = ["old-deleted-1", "old-deleted-2"]
        self.save(session)
        with self.acting(session):
            prune_invisible_shared_league_state(session)
        self.assertEqual(session[DELETED_DRAFT_ARCHIVE_IDS_KEY], ["old-deleted-1", "old-deleted-2"])

    def test_a_marked_draft_is_not_brought_back_by_a_restore(self) -> None:
        from workflow_persist_guard import merge_protected_workflow_on_restore

        session = signed_in("danny")
        entry = self.save(session)
        marked = copy.deepcopy(entry)
        session["draft_archive_teams"] = []
        session[DELETED_DRAFT_ARCHIVE_IDS_KEY] = [entry["draft_id"]]
        with self.acting(session), mock.patch(
            "workflow_persist_guard._load_disk_workflow_snapshot", return_value={"draft_archive_teams": [marked]}
        ), mock.patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value={}):
            merge_protected_workflow_on_restore(session, {})
        self.assertEqual(list_draft_archives(session), [])


if __name__ == "__main__":
    unittest.main()
