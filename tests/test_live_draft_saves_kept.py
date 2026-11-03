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


def core(state: dict) -> dict:
    """What a Library visit must never change: entries and their contents, each context's team,
    owners and rosters, deletion markers and the active selection."""
    store = state.get("fantasy_league_context_state") or {}
    return {
        "entries": [{k: e.get(k) for k in ("draft_id", "draft_name", "team_name", "players", "draft_board", "league_context_id")}
                    for e in (state.get("draft_archive_teams") or [])],
        "contexts": {cid: {"my_team_name": c.get("my_team_name"), "ownership": get_team_ownership(c),
                           "league_rosters": c.get("league_rosters")}
                     for cid, c in (store.get("contexts") or {}).items()},
        "active": (state.get(ACTIVE_DRAFT_ARCHIVE_KEY) or None, store.get("active_league_context_id") or None),
        "markers": state.get(DELETED_DRAFT_ARCHIVE_IDS_KEY),
    }


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

    def test_with_sign_in_off_no_owner_is_recorded_and_no_fallback_account_is_used(self) -> None:
        # Single-account mode (sign-in off): the save works as before and records no owner; the
        # deployment's configured account is never written as one.
        session = {}
        with mock.patch.dict("os.environ", {"SUITE_AUTH_ENABLED": ""}), mock.patch(
            "suite_auth.is_auth_enabled", return_value=False
        ), _as_user("user:configured-default"):
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


class SignInMigrationTests(_SignedIn):
    def test_a_disk_holding_only_hidden_drafts_is_not_wiped_at_sign_in(self) -> None:
        """reconcile_stranded_foreign_disk_drafts (sign-in migration write-back) used to replace such
        a disk library with the empty session list and allow the next save to clear the cloud."""
        from fantasy_league_invites import reconcile_stranded_foreign_disk_drafts
        from workflow_persist_guard import WORKFLOW_PERSIST_ALLOW_CLEAR_KEY

        owner = signed_in("danny")
        self.legacy_ownerless(owner)
        disk = {k: copy.deepcopy(owner[k]) for k in ("draft_archive_teams", "fantasy_league_context_state")}
        session = signed_in("danny")  # a fresh sign-in: nothing in the session yet
        st = mock.MagicMock()
        st.session_state = session
        with self.acting(session), mock.patch(
            "workflow_persist_guard._load_disk_workflow_snapshot", return_value=copy.deepcopy(disk)
        ), mock.patch("suite_user_persistence._load_raw", return_value=(copy.deepcopy(disk), "x", "t")), mock.patch(
            "suite_user_persistence.save_user_state", return_value=True
        ) as disk_write, mock.patch("fantasy_league_invites.list_pending_invites_for_session", return_value=[]):
            out = reconcile_stranded_foreign_disk_drafts(st)
        self.assertTrue(out["stranded"])
        disk_write.assert_not_called()
        self.assertFalse(out["disk_sanitized"])
        self.assertNotIn(WORKFLOW_PERSIST_ALLOW_CLEAR_KEY, session)


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


def _room(teams: list[str], *, shared_code: str = "") -> dict:
    board = [{"Pick": i, "Round": 1, "Fantasy Team": t, "Team": t, "Player": f"Player {t}", "fullName": f"Player {t}",
              "playerID": f"p{i}", "Primary Position": "OF"} for i, t in enumerate(teams, start=1)]
    room = {
        "status": "complete",
        "teams": list(teams),
        "config": {"league_name": "Test League", "teams": list(teams), "num_teams": len(teams), "picks_per_team": 1,
                   "fantasy_format": "5x5 Roto", "slots": {"OF": 1}, "user_team": teams[0]},
        "pick_order": [{"Pick": i, "Round": 1, "Team": t} for i, t in enumerate(teams, start=1)],
        "draft_board": board,
        "rosters": {t: [{"fullName": f"Player {t}", "playerID": f"p{i}", "Primary Position": "OF"}]
                    for i, t in enumerate(teams, start=1)},
    }
    if shared_code:
        room["room_code"] = shared_code
    return room


class SaveButtonPathTests(_SignedIn):
    """Check 1: the real Save to Draft Library click path, Solo and Shared."""

    def click_save(self, session: dict, *, team_name: str = "") -> None:
        from draft_archive_ui import _execute_live_draft_save_click

        st = mock.MagicMock()
        st.session_state = session
        with self.acting(session), mock.patch("baseball_persistent_state.force_save_baseball_state", return_value=True):
            _execute_live_draft_save_click(st, session, team_name=team_name, key_prefix="t", defer_activation=True)

    def shared(self, account: str, team: str | None) -> dict:
        from draft_room_participant_state import MEMBERSHIP_KEY

        session = signed_in(account)
        session["live_draft_room"] = _room(["Danny", "Barry"], shared_code="ABC123")
        session["active_shared_draft_room_code"] = "ABC123"
        if team:
            pid = session["_suite_auth_user_id"]  # with sign-in on, the participant id is the Auth id
            session[MEMBERSHIP_KEY] = {"ABC123": {pid: {"participant_id": pid, "assigned_team": team}}}
        return session

    def owner_of(self, session: dict, team: str) -> str:
        entry = list_draft_archives(session)[0]
        ownership = get_team_ownership(get_league_context_for_archive(session, entry))
        return str((ownership.get(team) or {}).get("user_id") or "")

    def test_a_solo_save_records_the_account_and_its_team(self) -> None:
        session = signed_in("danny")
        session["live_draft_room"] = _room(["Danny", "CPU 1", "CPU 2"])
        self.click_save(session, team_name="Danny")
        self.assertEqual(list_draft_archives(session)[0]["team_name"], "Danny")
        self.assertEqual(self.owner_of(session, "Danny"), "cloud-danny")

    def test_a_shared_participant_save_uses_the_seat_even_if_the_button_names_another_team(self) -> None:
        session = self.shared("barry", "Barry")
        self.click_save(session, team_name="Danny")
        self.assertEqual(list_draft_archives(session)[0]["team_name"], "Barry")
        self.assertEqual(self.owner_of(session, "Barry"), "cloud-barry")
        self.assertEqual(self.owner_of(session, "Danny"), "")

    def test_a_shared_commissioner_save_records_the_commissioner_team(self) -> None:
        session = self.shared("danny", "Danny")
        self.click_save(session)
        self.assertEqual(self.owner_of(session, "Danny"), "cloud-danny")

    def test_a_shared_save_without_a_readable_seat_saves_nothing(self) -> None:
        session = self.shared("barry", None)  # seat not known: no first-team fallback
        self.click_save(session, team_name="")
        self.assertEqual(list_draft_archives(session), [])
        self.assertIn("Your seat in this Shared Draft couldn't be confirmed", str(session.get("_draft_save_ui_flash")))


class ContinuousUseTests(_SignedIn):
    """Checks 2, 3, 6, 7, 8: Library page, sign-in clean-up, refresh, navigation, deletes."""

    def library(self) -> tuple[dict, dict, dict]:
        session = signed_in("danny")
        legit = self.save(session)
        ownerless = self.old_ownerless(session)
        session[ACTIVE_DRAFT_ARCHIVE_KEY] = legit["draft_id"]
        ensure_fantasy_league_context_state(session)["active_league_context_id"] = legit["league_context_id"]
        session[DELETED_DRAFT_ARCHIVE_IDS_KEY] = ["deleted-long-ago"]
        return session, legit, ownerless

    def old_ownerless(self, session: dict) -> dict:
        """A second, different draft saved before the hotfix (no owner recorded)."""
        room = _room(["Team A", "Team B", "Team C"])
        with self.acting(session):
            entry, _ = save_live_draft_league_context(session, room, my_team_name="Team A",
                                                      draft_name="Old ownerless", save_only=True)
        ctx = ensure_fantasy_league_context_state(session)["contexts"][entry["league_context_id"]]
        meta = dict(ctx.get("metadata") or {})
        meta.pop("team_ownership", None)
        ctx["metadata"] = meta
        ctx.pop("team_ownership", None)
        self.assertEqual(get_team_ownership(ctx), {})
        return entry

    def test_the_real_library_page_changes_nothing_and_shows_only_the_legitimate_draft(self) -> None:
        from pathlib import Path

        from streamlit.testing.v1 import AppTest

        session, legit, _ownerless = self.library()
        before = stored(session)
        fixture = Path(__file__).resolve().parent / "fixtures" / "library_kept_app.py"
        at = AppTest.from_file(str(fixture), default_timeout=120)
        for key, value in session.items():
            at.session_state[key] = copy.deepcopy(value)
        for _ in range(2):  # a first visit, then a refresh (rerun)
            at.run()
            self.assertFalse(at.exception, [str(e.value)[:300] for e in at.exception])
        after = {k: at.session_state[k] for k in STORED if k in at.session_state}
        # The existing origin-label repair and migration index still run on a Library visit (as
        # deployed); everything else must be exactly as before.
        self.assertEqual(core(after), core(before))  # nothing deleted, marked, re-pointed or re-owned
        text = " ".join(str(getattr(el, "value", "")) for el in list(at.markdown) + list(at.caption) + list(at.info))
        self.assertIn(legit["draft_name"], text)
        self.assertNotIn("Old ownerless", text)
        self.assertNotIn("visible after shared-league membership filter", text)  # developer-only caption

    def test_sign_in_cleanup_with_saving_on_writes_and_removes_nothing(self) -> None:
        session, _legit, _ownerless = self.library()
        before = stored(session)
        st = mock.MagicMock()
        st.session_state = session
        with self.acting(session), mock.patch("baseball_persistent_state.force_save_baseball_state") as cloud, \
                mock.patch("suite_user_persistence.save_user_state") as disk:
            out = sanitize_workflow_library_for_account(session, st=st, persist_cleanup=True, app_id="baseball")
        self.assertEqual(out["total_removed"], 0)
        cloud.assert_not_called()
        disk.assert_not_called()
        self.assertEqual(stored(session), before)

    def test_a_refresh_restore_keeps_both_entries_and_still_blocks_marked_ones(self) -> None:
        from workflow_persist_guard import merge_protected_workflow_on_restore

        session, legit, ownerless = self.library()
        blob = {k: copy.deepcopy(session[k])
                for k in ("draft_archive_teams", "fantasy_league_context_state", DELETED_DRAFT_ARCHIVE_IDS_KEY)}
        blob["draft_archive_teams"].append({"draft_id": "deleted-long-ago", "draft_name": "Deleted draft"})
        fresh = signed_in("danny")
        with self.acting(fresh), mock.patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value=blob), \
                mock.patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value=blob):
            merge_protected_workflow_on_restore(fresh, copy.deepcopy(blob))
        ids = {e["draft_id"] for e in list_draft_archives(fresh)}
        self.assertTrue({legit["draft_id"], ownerless["draft_id"]} <= ids)
        self.assertNotIn("deleted-long-ago", ids)  # a deleted draft is not resurrected

    def test_navigation_keeps_the_active_draft_and_the_other_entries(self) -> None:
        from fantasy_league_context import schedule_active_context_resync

        session, legit, _ownerless = self.library()
        before = stored(session)
        with self.acting(session):
            schedule_active_context_resync(session)
            prune_invisible_shared_league_state(session)
        self.assertEqual(session[ACTIVE_DRAFT_ARCHIVE_KEY], legit["draft_id"])
        self.assertEqual(stored(session)["draft_archive_teams"], before["draft_archive_teams"])

    def test_a_deliberate_delete_still_deletes_and_stays_deleted(self) -> None:
        from draft_archive_state import delete_draft_archive
        from workflow_persist_guard import merge_protected_workflow_on_restore

        session, legit, _ownerless = self.library()
        snapshot = copy.deepcopy(legit)
        self.assertTrue(delete_draft_archive(session, legit["draft_id"]))
        self.assertIn(legit["draft_id"], session[DELETED_DRAFT_ARCHIVE_IDS_KEY])
        with self.acting(session), mock.patch(
            "workflow_persist_guard._load_disk_workflow_snapshot", return_value={"draft_archive_teams": [snapshot]}
        ), mock.patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value={}):
            prune_invisible_shared_league_state(session)
            merge_protected_workflow_on_restore(session, {})
        self.assertNotIn(legit["draft_id"], {e["draft_id"] for e in list_draft_archives(session)})
        self.assertIn(legit["draft_id"], session[DELETED_DRAFT_ARCHIVE_IDS_KEY])

    def test_another_account_cannot_see_or_change_these_drafts(self) -> None:
        danny, _legit, _ownerless = self.library()
        danny_before = stored(danny)
        barry = signed_in("barry")
        for key in ("draft_archive_teams", "fantasy_league_context_state"):
            barry[key] = copy.deepcopy(danny[key])  # even holding a copy
        with self.acting(barry):
            self.assertEqual(list_visible_draft_archives(barry), [])
            prune_invisible_shared_league_state(barry)
            sanitize_workflow_library_for_account(barry, persist_cleanup=False)
        self.assertEqual(stored(danny), danny_before)  # separate account state: Danny's is untouched


class NoUnverifiedLibraryEntriesTests(SaveButtonPathTests):
    """A signed-in Live Draft is never saved as a multi-team entry with missing or ambiguous
    ownership: the save is refused with a clear message, and no first team or fallback account is
    used. (Owner request 2026-11-02.)"""

    def assert_refused(self, session: dict, message: str) -> None:
        self.assertEqual(list_draft_archives(session), [])
        self.assertIn(message, str(session.get("_draft_save_ui_flash")))

    def test_a_signed_out_visitor_is_refused(self) -> None:
        session = {"live_draft_room": _room(["Danny", "CPU 1"])}
        with mock.patch("suite_auth.is_authenticated", return_value=False):
            self.click_save_plain(session, team_name="Danny")
        self.assert_refused(session, "Sign in to save this draft")

    def test_a_session_without_a_confirmed_account_id_is_refused(self) -> None:
        session = {"_suite_auth_session": True, "live_draft_room": _room(["Danny", "CPU 1"])}
        self.click_save_plain(session, team_name="Danny")
        self.assert_refused(session, "Your account couldn't be confirmed")

    def test_a_solo_draft_with_no_known_team_is_refused_not_given_the_first_team(self) -> None:
        session = signed_in("danny")
        room = _room(["Danny", "CPU 1"])
        room["config"].pop("user_team")
        session["live_draft_room"] = room
        self.click_save(session, team_name="")
        self.assert_refused(session, "Your team in this draft couldn't be determined")

    def test_a_team_that_is_not_in_the_draft_is_refused(self) -> None:
        session = signed_in("danny")
        session["live_draft_room"] = _room(["Danny", "CPU 1"])
        self.click_save(session, team_name="Somebody else")
        self.assert_refused(session, "isn't a team in this draft")

    def test_a_shared_draft_without_a_readable_seat_is_refused(self) -> None:
        session = self.shared("barry", None)
        self.click_save(session, team_name="Danny")  # the button's team is not trusted without a seat
        self.assert_refused(session, "Your seat in this Shared Draft couldn't be confirmed")

    def test_the_save_function_itself_never_creates_an_unowned_entry(self) -> None:
        session = {"_suite_auth_session": True}  # signed in, but no account id in the session
        with self.assertRaises(ValueError):
            save_live_draft_league_context(session, _room(["Danny", "Barry"]), my_team_name="Danny", save_only=True)
        self.assertEqual(list_draft_archives(session), [])
        session = signed_in("danny")
        with self.assertRaises(ValueError):
            save_live_draft_league_context(session, _room(["Danny", "Barry"]), my_team_name="", save_only=True)
        self.assertEqual(list_draft_archives(session), [])

    def click_save_plain(self, session: dict, *, team_name: str = "") -> None:
        from draft_archive_ui import _execute_live_draft_save_click

        st = mock.MagicMock()
        st.session_state = session
        with _as_user(""), mock.patch("baseball_persistent_state.force_save_baseball_state", return_value=True):
            _execute_live_draft_save_click(st, session, team_name=team_name, key_prefix="t", defer_activation=True)


class CreateSharedLeagueTests(SaveButtonPathTests):
    """The Create Shared League path writes nothing without a verified account and seat, and leaves
    nothing behind when creation fails part-way."""

    def run_create(self, session: dict, team: str, **patches) -> mock.MagicMock:
        from draft_archive_ui import SHARED_LEAGUE_CREATE_REQUEST_KEY, _process_live_draft_shared_league_create_request

        session[SHARED_LEAGUE_CREATE_REQUEST_KEY] = {"status": "pending", "request_id": "req-1", "my_team_name": team}
        st = mock.MagicMock()
        st.session_state = session
        with self.acting(session), mock.patch("baseball_persistent_state.force_save_baseball_state", return_value=True), \
                contextlib.ExitStack() as stack:
            for target, value in patches.items():
                stack.enter_context(mock.patch(target.replace("__", "."), **value))
            _process_live_draft_shared_league_create_request(st, session, session["live_draft_room"])
        return st

    def test_no_readable_seat_writes_nothing(self) -> None:
        session = self.shared("barry", None)
        before = core(stored(session))
        st = self.run_create(session, "Barry")
        self.assertEqual(core(stored(session)), before)
        self.assertIn("Your seat in this Shared Draft couldn't be confirmed", str(st.error.call_args))

    def test_a_failure_part_way_leaves_no_partial_entry(self) -> None:
        session = self.shared("danny", "Danny")
        before = core(stored(session))

        def half_then_fail(sess, room, **kw):
            sess.setdefault("draft_archive_teams", []).append({"draft_id": "partial", "draft_name": "Half-made"})
            raise ValueError("assignment failed")

        self.run_create(session, "Danny", live_draft_shared_league__save_live_draft_shared_league_context={"side_effect": half_then_fail})
        self.assertEqual(core(stored(session)), before)
        self.assertNotIn("partial", str(session.get("draft_archive_teams")))


if __name__ == "__main__":
    unittest.main()
