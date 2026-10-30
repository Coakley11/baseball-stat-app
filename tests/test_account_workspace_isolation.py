"""Two signed-in accounts on one server never read, inherit, modify or overwrite each other's workspace.

Server-local ``data/`` is shared by every session on a Streamlit host. These tests pass the
session the way Streamlit does — a mapping that is *not* a ``dict`` (``SessionStateProxy``) —
because the ownership code used to check ``isinstance(session_state, dict)`` and, for the real
session, fell back to the shared ``suite_active_workspace.json`` pointer and to "daniel".
Each test runs against its own temporary data directory, seeded with another account's files.
"""

from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any
from unittest import mock

import suite_auth
import suite_user_persistence as sup
import suite_workspace
import suite_workspace_registry as reg
import workflow_persist_guard as wpg

OWNER_ROOM = {"draft_room_id": "OWNER_ROOM_1", "room_code": "NU0BKB", "status": "not_started",
              "meta": {"owner_external_id": "daniel", "owner_auth_user_id": "uuid-daniel"}}
OWNER_STATE = {
    "live_draft_state": OWNER_ROOM,
    "page_filter_state": {"Trend Value": {"trend_min_g": 50}},
    "draft_archive_teams": [{"draft_id": "owner_draft", "draft_name": "Owner's league"}],
}


class ProxySession(MutableMapping):
    """Mapping-like like Streamlit's SessionStateProxy, and deliberately not a dict."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._d = dict(data or {})

    def __getitem__(self, key):
        return self._d[key]

    def __setitem__(self, key, value):
        self._d[key] = value

    def __delitem__(self, key):
        del self._d[key]

    def __iter__(self):
        return iter(self._d)

    def __len__(self):
        return len(self._d)


def signed_in(external_id: str) -> ProxySession:
    return ProxySession({
        "_suite_auth_session": True,
        "_suite_auth_user_id": f"uuid-{external_id}",
        "_suite_auth_user_email": f"{external_id}@example.com",
        "_suite_auth_external_id": external_id,
    })


def start(st) -> None:
    """App startup once the sign-in is restored (``bootstrap_suite_workspace`` minus the token check)."""
    suite_auth.enforce_workspace_ownership(st.session_state)
    suite_workspace.init_suite_workspace(st)


class _Isolated(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        self.pointer = self.data / "suite_active_workspace.json"
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for target, value in (
            ("suite_workspace.DATA_DIR", self.data),
            ("suite_workspace._PERSISTED_FILE", self.pointer),
            ("suite_workspace_registry.DATA_DIR", self.data),
            ("suite_workspace_registry.REGISTRY_FILE", self.data / "workspaces" / "_ownership_registry.json"),
            ("suite_workspace_registry.ACTIVE_DIR", self.data / "workspaces" / "_active"),
            ("suite_user_persistence.DATA_DIR", self.data),
            ("suite_user_persistence._LEGACY_COMBINED_FILE", self.data / "app_state.json"),
        ):
            stack.enter_context(mock.patch(target, value))
        stack.enter_context(mock.patch.dict("os.environ", {"SUITE_AUTH_ENABLED": "1"}))
        stack.enter_context(mock.patch.object(suite_auth, "is_auth_enabled", return_value=True))
        stack.enter_context(mock.patch.object(suite_auth, "_configured_profile_emails", return_value={}))
        # The owner's leftovers on the shared server disk.
        self.pointer.write_text(json.dumps({"workspace_id": "daniel", "label": "Daniel"}), encoding="utf-8")
        self.owner_file = self.data / "workspaces" / "daniel" / "baseball_user_state.json"
        self.owner_file.parent.mkdir(parents=True)
        self.owner_file.write_text(json.dumps({"version": 1, "app": "baseball", "saved_at": "2026-10-29T13:40:07+00:00",
                                               "state": OWNER_STATE}), encoding="utf-8")
        self.owner_bytes = self.owner_file.read_bytes()
        self.pointer_bytes = self.pointer.read_bytes()

    def acting(self, session: ProxySession):
        """Run as the script session of this account (what Streamlit's st.session_state is)."""
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(sup, "_signed_in_script_session", return_value=session))
        stack.enter_context(mock.patch.object(sup, "_anonymous_guest", return_value=False))
        return stack

    def assert_owner_untouched(self) -> None:
        self.assertEqual(self.owner_file.read_bytes(), self.owner_bytes, "the owner's workspace file changed")
        self.assertEqual(self.pointer.read_bytes(), self.pointer_bytes, "the shared pointer changed")


class OwnershipResolutionTests(_Isolated):
    def test_a_signed_in_proxy_session_resolves_its_own_workspace(self) -> None:
        ss = signed_in("qa_iso_b")
        reg.ensure_owned_workspace_for_session(ss)
        self.assertEqual(reg.get_owned_workspace_id(ss), "qa_iso_b")
        self.assertEqual(reg.list_owned_workspace_ids(session_state=ss), ("qa_iso_b",))
        self.assertFalse(reg.workspace_access_allowed("daniel", session_state=ss))
        self.assertEqual(suite_workspace.load_persisted_workspace_id(session_state=ss), "qa_iso_b")

    def test_startup_never_clamps_an_account_onto_the_owners_workspace(self) -> None:
        ss = signed_in("qa_iso_b")
        st = type("St", (), {"session_state": ss, "query_params": {}})()
        start(st)
        self.assertEqual(ss["_suite_active_workspace_id"], "qa_iso_b")
        trace = ss.get("_suite_workspace_ownership_trace") or {}
        self.assertNotEqual(trace.get("owned"), "daniel", trace)
        self.assertNotEqual(trace.get("active_after"), "daniel", trace)
        self.assertNotIn("daniel", str(ss.get("_suite_workspace_last_clamp") or "").split("->")[-1])

    def test_unresolved_owner_is_not_the_default_profile(self) -> None:
        ss = signed_in("qa_iso_b")
        with mock.patch("suite_workspace_registry.resolve_owned_workspace_id", return_value=""):
            active = suite_auth.hard_clamp_owned_workspace_before_scoped_load(ss)
        self.assertEqual(active, "qa_iso_b")

    def test_a_signed_in_account_never_reads_or_writes_the_shared_pointer(self) -> None:
        ss = signed_in("qa_iso_b")
        st = type("St", (), {"session_state": ss, "query_params": {}})()
        suite_workspace.set_active_workspace_id(st, "qa_iso_b")
        self.assert_owner_untouched()
        self.assertTrue((self.data / "workspaces" / "_active" / "uuid-qa_iso_b.json").is_file())
        # And the owner's pointer value never becomes this account's workspace.
        self.assertEqual(suite_workspace.load_persisted_workspace_id(session_state=signed_in("qa_iso_c")), "qa_iso_c")

    def test_a_url_naming_another_workspace_is_refused(self) -> None:
        ss = signed_in("qa_iso_b")
        st = type("St", (), {"session_state": ss, "query_params": {"suite_workspace": "daniel"}})()
        start(st)
        self.assertEqual(suite_workspace.get_active_workspace_id(st), "qa_iso_b")


class DiskChokepointTests(_Isolated):
    def test_another_accounts_workspace_cannot_be_read(self) -> None:
        ss = signed_in("qa_iso_b")
        ss["_suite_active_workspace_id"] = "qa_iso_b"
        with self.acting(ss):
            state, _, _ = sup._load_raw("baseball", "daniel")
        self.assertEqual(state, {})
        self.assertEqual(ss[sup.WORKSPACE_ACCESS_REFUSED_KEY]["workspace_id"], "daniel")

    def test_a_session_key_pointing_elsewhere_still_cannot_read_it(self) -> None:
        ss = signed_in("qa_iso_b")
        ss["_suite_active_workspace_id"] = "daniel"  # a stale or forged key
        with self.acting(ss):
            state, _, _ = sup._load_raw("baseball")
        self.assertNotIn("live_draft_state", state)

    def test_another_accounts_workspace_cannot_be_overwritten_or_reset(self) -> None:
        ss = signed_in("qa_iso_b")
        ss["_suite_active_workspace_id"] = "qa_iso_b"
        with self.acting(ss):
            self.assertFalse(sup.save_user_state("baseball", {"draft_queue": ["Mallory"]}, workspace_id="daniel"))
            self.assertFalse(sup.reset_user_state("baseball", workspace_id="daniel"))
            self.assertTrue(sup.save_user_state("baseball", {"draft_queue": ["Own"]}, workspace_id="qa_iso_b"))
            own, _, _ = sup._load_raw("baseball", "qa_iso_b")
        self.assertEqual(own, {"draft_queue": ["Own"]})
        self.assert_owner_untouched()

    def test_the_owner_still_reaches_their_own_workspace(self) -> None:
        ss = signed_in("daniel")
        ss["_suite_active_workspace_id"] = "daniel"
        with self.acting(ss):
            state, _, _ = sup._load_raw("baseball", "daniel")
        self.assertEqual(state.get("live_draft_state", {}).get("room_code"), "NU0BKB")

    def test_the_legacy_single_user_file_is_never_given_to_a_new_account(self) -> None:
        (self.data / "app_state.json").write_text(json.dumps({"baseball": {"state": OWNER_STATE}}), encoding="utf-8")
        ss = signed_in("qa_iso_b")
        ss["_suite_active_workspace_id"] = "qa_iso_b"
        with self.acting(ss), mock.patch("suite_workspace.resolve_workspace_id",
                                         side_effect=lambda **k: k.get("explicit") or "qa_iso_b"):
            state, _, _ = sup._load_raw("baseball")
        self.assertEqual(state, {})


class RecoveryScanTests(_Isolated):
    def test_draft_recovery_never_scans_another_accounts_workspaces(self) -> None:
        ss = signed_in("qa_iso_b")
        ss["_suite_active_workspace_id"] = "qa_iso_b"
        disk = wpg._disk_migration_candidate_workspace_ids(ss)
        cloud = [ws for ws, _key in wpg._cloud_app_keys_to_scan_for_migration("baseball", ss)]
        self.assertEqual(disk, ["qa_iso_b"])
        self.assertEqual(cloud, ["qa_iso_b"])
        with self.acting(ss):
            found = wpg.discover_workflow_migration_sources(ss)
        self.assertNotIn("owner_draft", json.dumps(found, default=str))

    def test_the_owner_keeps_their_legacy_recovery_sources(self) -> None:
        ss = signed_in("daniel")
        ss["_suite_active_workspace_id"] = "daniel"
        self.assertIn("daniel", wpg._disk_migration_candidate_workspace_ids(ss))

    def test_live_draft_save_never_injects_another_accounts_room(self) -> None:
        import live_draft_state

        ss = signed_in("qa_iso_b")
        ss["_suite_active_workspace_id"] = "daniel"  # the old bootstrap clamp left exactly this
        with self.acting(ss):
            out, _diag = live_draft_state.enrich_save_payload_with_live_draft(ss, {"draft_queue": []})
        self.assertNotIn("live_draft_state", out)
        self.assertNotIn("NU0BKB", json.dumps(out, default=str))
        self.assert_owner_untouched()



class AccountChangeInOneBrowserTests(unittest.TestCase):
    def test_logging_out_leaves_nothing_of_the_account_in_the_browser_session(self) -> None:
        import baseball_persistent_state  # noqa: F401  (registers the baseball workspace clearer)

        ss = signed_in("qa_iso_a")
        ss.update({
            "active_page": "Historical Explorer",
            "hist_HR_min": 41,
            "page_filter_state": {"Historical Explorer": {"hist_HR_min": 41, "historical_year_range_filter": (2006, 2012)}},
            "historical_year_range_filter": (2006, 2012),
            "draft_queue": ["Aaron Judge"],
            "draft_archive_teams": [{"draft_id": "a1", "draft_name": "A's league"}],
            "fantasy_league_context_state": {"active_league_context_id": "archive:a1", "contexts": {}},
            "_ami_assistant_conversation": [{"q": "A's question"}],
            "_suite_workspace_base::baseball": {"draft_queue": ["Aaron Judge"]},
            "_suite_cloud_revision_seen": "2026-10-29T10:00:00+00:00",
            "_account_fantasy_prefs_base_document": {"active_draft_id": "a1"},
            # Copies outside the saved keys, as a real session holds them (the queue came back from these)
            "_live_draft_queue_last_good": ["Aaron Judge"],
            "_live_draft_queue_sidebar_mirror": ["Aaron Judge"],
            "draft_state": {"queue": ["Aaron Judge"]},
            "_draft_new_draft_workflow": {"queue": ["Aaron Judge"]},
            "_suite_full_session_blob_baseball@qa_iso_a": {"draft_queue": ["Aaron Judge"]},
            "_suite_full_session_ts_baseball@qa_iso_a": "2026-10-29T10:00:00+00:00",
            "_suite_draft_archive_prewrite_backup": [{"draft_id": "a1", "draft_name": "A's league"}],
            "_ami_context_by_page": {"Historical Explorer": {"question": "A's question"}},
            # Unsaved-edit markers: left behind, the next restore keeps the empty queue and saves it
            "_draft_queue_persist_dirty": True,
            "_draft_queue_persist_dirty_ts": 1.0,
            "draft_state_dirty": True,
            "_draft_workflow_pending_sync": True,
            "historical_state_last_local_edit_ts": 1.0,
            "_suite_persist_local_dirty::baseball": True,
        })
        with mock.patch.object(suite_auth, "_auth_api", side_effect=RuntimeError("offline")):
            suite_auth.logout(ss)
        for key, value in ss.items():
            text = json.dumps(value, default=str)
            for marker in ("Aaron Judge", "A's league", "A's question"):
                self.assertNotIn(marker, f"{key} {text}", f"{key} still holds the signed-out account's {marker!r}")
        self.assertFalse([k for k in ss if str(k).startswith("_suite_full_session_")])
        self.assertFalse([k for k in ss if str(k).endswith(("_dirty", "_dirty_ts", "_pending_sync", "_last_local_edit_ts"))
                          or str(k).startswith("_suite_persist_local_dirty")])
        for key in ("hist_HR_min", "page_filter_state", "historical_year_range_filter", "draft_queue",
                    "draft_archive_teams", "fantasy_league_context_state", "_ami_assistant_conversation",
                    "_suite_workspace_base::baseball", "_suite_cloud_revision_seen",
                    "_account_fantasy_prefs_base_document"):
            self.assertNotIn(key, ss, key)
        self.assertEqual(ss.get("active_page"), "Historical Explorer")   # where the browser was stays
        self.assertNotIn("_suite_auth_session", ss)


if __name__ == "__main__":
    unittest.main()
