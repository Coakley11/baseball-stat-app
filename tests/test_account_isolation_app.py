"""Through the real app: another account's leftovers on the server disk never reach a signed-in account.

The shared server ``data/`` holds the owner's workspace (``workspaces/daniel``), the old global
``suite_active_workspace.json`` pointer naming it, and a Live Draft room, a Saved Draft Library,
a queue and page settings. A different account then signs in on a Dell and a fresh phone. The app
resolves the workspace itself (no harness patch), in a private data directory seeded with copies.
"""

from __future__ import annotations

import json
import unittest

from tests.cloud_restore_harness import CloudRestoreHarness

HIST = "Historical Explorer"
OWNER_MARKERS = ("NU0BKB", "OWNER_ROOM_1", "Owner's league", "Owner Queue Guy", "Owner Favorite")
OWNER_STATE = {
    "live_draft_state": {"draft_room_id": "OWNER_ROOM_1", "room_code": "NU0BKB", "share_code": "NU0BKB",
                         "status": "not_started", "config": {}, "teams": [], "pick_order": [], "draft_board": [],
                         "meta": {"owner_external_id": "daniel", "owner_auth_user_id": "uuid-daniel",
                                  "owner_workspace_id": "daniel"}},
    "page_filter_state": {HIST: {"hist_HR_min": 77}},
    "draft_archive_teams": [{"draft_id": "owner_draft", "draft_name": "Owner's league", "teams": []}],
    "draft_queue": ["Owner Queue Guy"],
    "workflow_favorite_targets": ["Owner Favorite"],
}


class AccountIsolationThroughTheApp(CloudRestoreHarness, unittest.TestCase):
    def setUp(self) -> None:
        self.start_cloud(real_workspace=True)
        owner_dir = self.data / "workspaces" / "daniel"
        owner_dir.mkdir(parents=True)
        self.owner_file = owner_dir / "baseball_user_state.json"
        self.owner_file.write_text(json.dumps({"version": 1, "app": "baseball", "saved_at": "2026-10-29T13:40:07+00:00",
                                               "state": OWNER_STATE}), encoding="utf-8")
        self.pointer = self.data / "suite_active_workspace.json"
        self.pointer.write_text(json.dumps({"workspace_id": "daniel", "label": "Daniel"}), encoding="utf-8")
        self.before = (self.owner_file.read_bytes(), self.pointer.read_bytes())

    def on_hist(self, name: str, **kw):
        dev = self.device(name, **kw)
        dev.at.session_state["active_page"] = HIST
        dev.at.session_state["main_sidebar_page"] = HIST
        return dev.run()

    def assert_clean(self, dev, label: str) -> None:
        state = dev.state()
        self.assertEqual(state.get("_suite_active_workspace_id"), self._current_account(), label)
        blob = json.dumps({k: state.get(k) for k in (
            "live_draft_state", "live_draft_room", "draft_archive_teams", "draft_queue",
            "workflow_favorite_targets", "page_filter_state")}, default=str)
        for marker in OWNER_MARKERS:
            self.assertNotIn(marker, blob, f"{label}: the owner's {marker!r} reached this account's session")
        self.assertNotEqual(state.get("hist_HR_min"), 77, label)
        self.assertIsNone(state.get("_suite_workspace_access_refused"), label)

    def assert_cloud_clean(self, account: str) -> None:
        row = json.dumps(self.store.row(f"baseball@{account}") or {}, default=str)
        for marker in OWNER_MARKERS:
            self.assertNotIn(marker, row, f"the owner's {marker!r} was uploaded into {account}'s cloud row")

    def assert_owner_untouched(self) -> None:
        self.assertEqual((self.owner_file.read_bytes(), self.pointer.read_bytes()), self.before,
                         "another account's session changed the owner's files on the server")

    def test_owner_leftovers_never_reach_another_account_on_any_device(self) -> None:
        dell = self.on_hist("dell")
        self.assert_clean(dell, "dell sign-in")
        dell.at.number_input(key="hist_HR_min").set_value(40).run()
        dell.go("Trend Value")
        dell.go("Historical")
        self.assert_clean(dell, "dell after navigation")
        self.assert_cloud_clean(self.account)
        self.assertEqual(((self.store.row(f"baseball@{self.account}") or {}).get("metrics") or {})
                         .get("full_session", {}).get("page_filter_state", {}).get(HIST, {}).get("hist_HR_min"), 40)

        self.wipe_local_disk()
        phone = self.on_hist("phone")
        self.assert_clean(phone, "phone")
        self.assertEqual(phone.state().get("hist_HR_min"), 40)       # its own work still comes back
        self.assert_cloud_clean(self.account)
        self.assert_owner_untouched()

    def test_two_accounts_on_one_server_keep_their_own_work(self) -> None:
        other = f"{self.account}_b"
        a = self.on_hist("a-dell")
        a.at.number_input(key="hist_HR_min").set_value(41).run()
        b = self.on_hist("b-dell", account=other)
        self.assert_clean(b, "b sign-in")
        self.assertNotEqual(b.state().get("hist_HR_min"), 41)
        b.at.number_input(key="hist_HR_min").set_value(12).run()
        self.acting_as(self.account)
        a_again = self.on_hist("a-refresh")
        self.assertEqual(a_again.state().get("hist_HR_min"), 41)
        rows = {acct: ((self.store.row(f"baseball@{acct}") or {}).get("metrics") or {}).get("full_session", {})
                for acct in (self.account, other)}
        self.assertEqual(rows[self.account]["page_filter_state"][HIST]["hist_HR_min"], 41)
        self.assertEqual(rows[other]["page_filter_state"][HIST]["hist_HR_min"], 12)
        for acct in (self.account, other):
            self.assert_cloud_clean(acct)
            disk = self.data / "workspaces" / acct / "baseball_user_state.json"
            if disk.is_file():
                mine = json.loads(disk.read_text(encoding="utf-8"))["state"]
                self.assertEqual(mine["page_filter_state"][HIST]["hist_HR_min"], 41 if acct == self.account else 12)
        self.assert_owner_untouched()

    def log_out(self, dev) -> None:
        """Press the sidebar's Log out button (suite_auth.logout runs inside the app's own run)."""
        buttons = [b for b in dev.at.button if b.key in ("suite_account_workspace_logout_btn", "suite_auth_logout_btn")]
        self.assertTrue(buttons, "no Log out button rendered")
        self.store.who = dev.name
        buttons[0].click().run()
        dev.run()

    def test_signing_out_and_in_as_another_account_in_one_browser_inherits_nothing(self) -> None:
        from tests.cloud_restore_harness import auth_for

        from tests.test_page_settings_sync import _Base

        a = self.on_hist("shared-browser")
        a.at.number_input(key="hist_HR_min").set_value(41).run()
        _Base.add_to_queue(self, a, "Owner Queue Guy")
        a.go("Trend Value")
        self.assertEqual(((self.store.row(f"baseball@{self.account}") or {}).get("metrics") or {})
                         .get("full_session", {}).get("page_filter_state", {}).get(HIST, {}).get("hist_HR_min"), 41)
        self.log_out(a)
        other = f"{self.account}_next"
        self._extra_accounts = {other}
        self.acting_as(other)
        for key, value in auth_for(other).items():                     # B signs in on the same tab
            a.at.session_state[key] = value
        a.at.session_state["active_page"] = HIST
        a.at.session_state["main_sidebar_page"] = HIST
        a.run()
        a.run()
        self.assertEqual(a.state().get("_suite_active_workspace_id"), other)
        self.assertNotEqual(a.state().get("hist_HR_min"), 41, "B's session shows A's filter")
        self.assert_clean(a, "B on the shared browser")                   # nor A's queue, Library or room
        a.go("Trend Value")
        row = (self.store.row(f"baseball@{other}") or {}).get("metrics", {}).get("full_session", {})
        self.assertNotEqual(row.get("page_filter_state", {}).get(HIST, {}).get("hist_HR_min"), 41,
                            "A's filter was saved into B's account")
        self.acting_as(self.account)
        mine = (self.store.row(f"baseball@{self.account}") or {}).get("metrics", {}).get("full_session", {})
        self.assertEqual(mine["page_filter_state"][HIST]["hist_HR_min"], 41)     # A's account untouched

    def test_signing_out_and_back_in_as_the_same_account_brings_its_work_back_from_the_cloud(self) -> None:
        from tests.cloud_restore_harness import auth_for
        from tests.test_page_settings_sync import _Base

        a = self.on_hist("shared-browser")
        a.at.number_input(key="hist_HR_min").set_value(41).run()
        _Base.add_to_queue(self, a, "Aaron Judge")
        a.go("Trend Value")
        self.log_out(a)
        self.assertNotEqual(a.state().get("hist_HR_min"), 41, "the signed-out tab still shows the account's filter")
        self.assertFalse(a.state().get("draft_queue"), "the signed-out tab still holds the account's queue")
        for key, value in auth_for(self.account).items():               # the same account signs back in
            a.at.session_state[key] = value
        a.at.session_state["active_page"] = HIST
        a.at.session_state["main_sidebar_page"] = HIST
        a.run()
        a.run()
        self.assertEqual(a.state().get("_suite_active_workspace_id"), self.account)
        self.assertEqual(a.state().get("hist_HR_min"), 41)
        self.assertEqual(list(a.state().get("draft_queue") or []), ["Aaron Judge"])
        mine = (self.store.row(f"baseball@{self.account}") or {}).get("metrics", {}).get("full_session", {})
        self.assertEqual(mine["page_filter_state"][HIST]["hist_HR_min"], 41)
        self.assertEqual(mine.get("draft_queue"), ["Aaron Judge"])
        self.assertEqual((mine.get("draft_state") or {}).get("queue"), ["Aaron Judge"])  # never saved empty


if __name__ == "__main__":
    unittest.main()
