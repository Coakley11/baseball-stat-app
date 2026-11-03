"""Stage B account saves, end to end through save_cloud_full_session against a compare-and-set fake.

11. A genuinely stale save (another device saved first) is rebased and written, both changes kept.
12. A successful write whose revision re-read failed: the next save recovers (the 2026-11-02 hosted
    Library failure, cause B), instead of being refused for the rest of the session.
13. Overlapping edits of the same saved draft are not silently overwritten.
14. Two accounts saving from the same Shared Draft don't interfere: separate records, and a revision
    seen for one record is never used to write another.
Also: an unhydrated session is still refused; refusals get plain messages and, when they repeat, a
visible warning that is cleared by the next successful save.
"""

from __future__ import annotations

import contextlib
import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import suite_cloud_state as scs
import workspace_merge as wm
from tests.cloud_restore_harness import FileStore
from workspace_cloud_guard import note_cloud_revision_seen, seen_cloud_revision


def _session(account: str) -> dict:
    return {
        "_suite_auth_session": True,
        "_suite_auth_user_id": f"uuid-{account}",
        "_suite_cloud_user_id": f"uuid-{account}",
        "_suite_auth_external_id": account,
        "_suite_owned_workspace_id": account,
        "_suite_active_workspace_id": account,
    }


def _draft(draft_id: str, name: str) -> dict:
    return {"draft_id": draft_id, "draft_name": name, "team_name": "Danny"}


class _CloudCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.account = "danny"
        self.store = FileStore(Path(self.tmp.name) / "cloud.json", account_fn=lambda: self.account)
        self.current: dict = {}
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for p in (
            mock.patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1", "SUITE_STORAGE_ISOLATED": "1"}),
            mock.patch("suite_storage_config.cloud_storage_enabled", return_value=True),
            mock.patch.object(scs, "_import_storage", return_value=(self.store, "fake")),
            mock.patch.object(scs, "_cloud_storage_app_id", side_effect=lambda app: f"{app}@{self.account}"),
            mock.patch.object(scs, "_anonymous_guest", return_value=False),
            mock.patch.object(scs, "_streamlit_session", side_effect=lambda: self.current),
        ):
            stack.enter_context(p)

    def as_(self, session: dict, account: str) -> dict:
        self.current, self.account = session, account
        return session

    def hydrate(self, session: dict, account: str) -> dict:
        """What sign-in does: load the account's row, remember its revision and the base."""
        self.as_(session, account)
        fresh = scs.load_cloud_full_session_status("baseball", force=True)
        note_cloud_revision_seen(session, fresh.updated_at, confirmed_empty=fresh.status == scs.CLOUD_READ_NOT_FOUND)
        wm.record_base(session, "baseball", copy.deepcopy(fresh.state))
        session["_local"] = copy.deepcopy(fresh.state)
        return session

    def save(self, session: dict, account: str, **changes) -> bool:
        self.as_(session, account)
        local = session.setdefault("_local", {})
        for key, value in changes.items():
            local[key] = copy.deepcopy(value)
        return scs.save_cloud_full_session("baseball", copy.deepcopy(local), save_reason="test_save")

    def cloud(self, account: str) -> dict:
        row = self.store.row(f"baseball@{account}") or {}
        return (row.get("metrics") or {}).get("full_session") or {}


class StaleRevisionRecoveryTests(_CloudCase):
    def test_11_a_genuinely_stale_save_is_rebased_and_both_changes_kept(self) -> None:
        a = self.hydrate(_session("danny"), "danny")
        self.assertTrue(self.save(a, "danny", draft_archive_teams=[_draft("d1", "First")]))
        b = self.hydrate(_session("danny"), "danny")  # second tab of the same account
        self.assertTrue(self.save(a, "danny", draft_queue=["Aaron Judge"]))  # A saves again: B is now stale
        self.assertTrue(self.save(b, "danny", draft_archive_teams=[_draft("d1", "First"), _draft("d2", "Second")]))
        cloud = self.cloud("danny")
        self.assertEqual(cloud.get("draft_queue"), ["Aaron Judge"])
        self.assertEqual({d["draft_id"] for d in cloud["draft_archive_teams"]}, {"d1", "d2"})

    def test_12_a_failed_re_read_after_a_successful_write_does_not_block_the_session(self) -> None:
        a = self.hydrate(_session("danny"), "danny")
        self.assertTrue(self.save(a, "danny", draft_queue=["Aaron Judge"]))
        real = scs.load_cloud_full_session_status
        calls = {"n": 0}

        def flaky(app_id, *, force=False):
            calls["n"] += 1
            if calls["n"] == 2:  # the re-read right after the write
                return scs.CloudRead({}, None, scs.CLOUD_READ_ERROR, "timeout")
            return real(app_id, force=force)

        seen_before = seen_cloud_revision(a)
        with mock.patch.object(scs, "load_cloud_full_session_status", side_effect=flaky):
            self.assertTrue(self.save(a, "danny", draft_archive_teams=[_draft("d1", "Live draft")]))
        self.assertEqual(seen_cloud_revision(a), seen_before)  # the session still holds the older revision
        # This is the save that was refused for 2.5 hours on 2026-11-02; now it rebases and goes through.
        self.assertTrue(self.save(a, "danny", draft_archive_teams=[_draft("d1", "Live draft"), _draft("d2", "Shared draft")]))
        self.assertEqual({d["draft_id"] for d in self.cloud("danny")["draft_archive_teams"]}, {"d1", "d2"})
        self.assertEqual(self.cloud("danny").get("draft_queue"), ["Aaron Judge"])

    def test_13_overlapping_edits_of_one_saved_draft_are_not_silently_overwritten(self) -> None:
        a = self.hydrate(_session("danny"), "danny")
        self.assertTrue(self.save(a, "danny", draft_archive_teams=[_draft("d1", "Original")]))
        b = self.hydrate(_session("danny"), "danny")
        self.assertTrue(self.save(a, "danny", draft_archive_teams=[_draft("d1", "Renamed on the phone")]))
        self.save(b, "danny", draft_archive_teams=[_draft("d1", "Renamed on the laptop")])
        names = [d["draft_name"] for d in self.cloud("danny")["draft_archive_teams"] if d["draft_id"] == "d1"]
        self.assertEqual(names, ["Renamed on the phone"])  # the laptop's stale edit did not replace it
        self.assertTrue(wm.open_conflicts(b, "baseball"))  # and the laptop is told there is a conflict

    def test_an_unhydrated_session_is_still_refused_with_a_plain_reason(self) -> None:
        a = self.hydrate(_session("danny"), "danny")
        self.assertTrue(self.save(a, "danny", draft_archive_teams=[_draft("d1", "Kept")]))
        fresh = self.as_(_session("danny"), "danny")  # never loaded the account
        self.assertFalse(self.save(fresh, "danny", draft_archive_teams=[]))
        self.assertEqual(fresh[scs.CLOUD_WRITE_BLOCKED_KEY]["detail"], "unhydrated")
        self.assertIn("hasn't finished loading", scs.cloud_write_refusal_message(fresh))
        self.assertEqual([d["draft_id"] for d in self.cloud("danny")["draft_archive_teams"]], ["d1"])

    def test_repeated_refusals_show_a_warning_that_a_successful_save_clears(self) -> None:
        a = self.hydrate(_session("danny"), "danny")
        self.assertTrue(self.save(a, "danny", draft_queue=["A"]))
        fresh = self.as_(_session("danny"), "danny")
        self.save(fresh, "danny", draft_queue=["B"])
        self.assertEqual(scs.autosave_refusal_warning(fresh), "")  # one refusal: no warning yet
        self.save(fresh, "danny", draft_queue=["C"])
        self.assertIn("aren't being saved", scs.autosave_refusal_warning(fresh))
        self.hydrate(fresh, "danny")
        self.assertTrue(self.save(fresh, "danny", draft_queue=["D"]))
        self.assertEqual(scs.autosave_refusal_warning(fresh), "")


class TwoAccountsTests(_CloudCase):
    def test_14_two_accounts_saving_from_one_shared_draft_do_not_interfere(self) -> None:
        danny = self.hydrate(_session("danny"), "danny")
        barry = self.hydrate(_session("barry"), "barry")
        for _ in range(2):  # interleaved saves, as both browsers autosave during the draft
            self.assertTrue(self.save(danny, "danny", draft_archive_teams=[_draft("dd", "Danny's copy")]))
            self.assertTrue(self.save(barry, "barry", draft_archive_teams=[_draft("bb", "Barry's copy")]))
        self.assertEqual([d["draft_id"] for d in self.cloud("danny")["draft_archive_teams"]], ["dd"])
        self.assertEqual([d["draft_id"] for d in self.cloud("barry")["draft_archive_teams"]], ["bb"])
        self.assertNotIn(scs.CLOUD_WRITE_BLOCKED_KEY, danny)
        self.assertNotIn(scs.CLOUD_WRITE_BLOCKED_KEY, barry)

    def test_a_revision_seen_for_one_account_record_is_not_used_for_another(self) -> None:
        session = self.hydrate(_session("danny"), "danny")
        self.assertTrue(self.save(session, "danny", draft_queue=["A"]))
        self.hydrate(_session("barry"), "barry")
        self.assertTrue(self.save(self.current, "barry", draft_queue=["Barry"]))
        # Same browser session, now signed in as Barry without loading Barry's record:
        session.update({k: v for k, v in _session("barry").items()})
        self.assertEqual(seen_cloud_revision(session), "")
        self.assertFalse(self.save(session, "barry", draft_queue=["Danny's leftovers"]))
        self.assertEqual(self.cloud("barry").get("draft_queue"), ["Barry"])


if __name__ == "__main__":
    unittest.main()
