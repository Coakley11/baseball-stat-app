"""Tests for account-scoped fantasy preferences (unit + write verification)."""

from __future__ import annotations

import unittest

from account_fantasy_preferences import (
    SESSION_APPLIED_REV_KEY,
    install_test_cloud_store,
    invalidate_preference_dependent_caches,
    sync_account_fantasy_preferences,
    write_account_fantasy_preferences,
)
from fantasy_context_ui import FANTASY_RESEARCH_SYNC_KEY
from fantasy_context_source import USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY


class AccountFantasyPreferencesSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store: dict = {}
        install_test_cloud_store(self.store)

    def tearDown(self) -> None:
        install_test_cloud_store(None)

    def _session(self) -> dict:
        return {
            "_suite_auth_user_id": "daniel",
            "_suite_active_workspace_id": "daniel",
            "active_draft_archive_id": "c6810611c73e",
            "fantasy_league_context_state": {
                "active_league_context_id": "archive:c6810611c73e",
                "contexts": {},
            },
            FANTASY_RESEARCH_SYNC_KEY: False,
            USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY: False,
            "use_simulator_board_as_fantasy_context": False,
        }

    def test_write_verified_readback(self) -> None:
        session = self._session()
        trace = write_account_fantasy_preferences(session, reason="test")
        self.assertTrue(trace.get("cloud_saved"))
        self.assertTrue(trace.get("write_verified"))
        self.assertEqual(trace.get("doc_active_draft_id"), "c6810611c73e")

    def test_research_mode_syncs_across_devices(self) -> None:
        phone = self._session()
        dell = self._session()
        phone[FANTASY_RESEARCH_SYNC_KEY] = True
        write_account_fantasy_preferences(phone, reason="research")
        sync_account_fantasy_preferences(dell, force=True)
        self.assertTrue(dell.get(FANTASY_RESEARCH_SYNC_KEY))

    def test_older_local_cannot_overwrite_newer_cloud(self) -> None:
        session = self._session()
        write_account_fantasy_preferences(session, reason="first")
        session[FANTASY_RESEARCH_SYNC_KEY] = True
        write_account_fantasy_preferences(session, reason="second")
        cloud_rev = int(session.get(SESSION_APPLIED_REV_KEY) or 0)
        self.assertGreaterEqual(cloud_rev, 2)
        session[SESSION_APPLIED_REV_KEY] = 1
        session["active_draft_archive_id"] = "3ce50b4f2e8b"
        session["fantasy_league_context_state"]["active_league_context_id"] = "archive:3ce50b4f2e8b"
        trace = write_account_fantasy_preferences(session, reason="stale_write", expected_revision=1)
        self.assertEqual(trace.get("conflict"), "cloud_newer")

    def test_preference_revision_invalidates_library_cache(self) -> None:
        session = self._session()
        session["_library_selection_fp"] = "old"
        session["_library_selection_cached"] = {"coherent": True}
        session["_workflow_descriptor_fp"] = "old"
        invalidate_preference_dependent_caches(session)
        self.assertNotIn("_library_selection_fp", session)
        self.assertNotIn("_workflow_descriptor_fp", session)


if __name__ == "__main__":
    unittest.main()
