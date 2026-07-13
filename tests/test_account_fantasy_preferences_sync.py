"""Tests for account-scoped cross-device fantasy preferences."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from account_fantasy_preferences import (
    PREFS_DOC_KEY,
    SESSION_APPLIED_REV_KEY,
    build_preference_document,
    invalidate_preference_dependent_caches,
    sync_account_fantasy_preferences,
    write_account_fantasy_preferences,
)
from fantasy_context_ui import FANTASY_RESEARCH_SYNC_KEY
from fantasy_context_source import USE_LIVE_DRAFT_AS_FANTASY_CONTEXT_KEY


class AccountFantasyPreferencesSyncTests(unittest.TestCase):
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

    @patch("account_fantasy_preferences._signed_in", return_value=True)
    @patch("account_fantasy_preferences._cloud_sync_available", return_value=True)
    @patch("account_fantasy_preferences._save_cloud_prefs", return_value=True)
    @patch("account_fantasy_preferences._load_cloud_prefs")
    def test_phone_sets_active_league_dell_receives(
        self,
        load_cloud,
        _save,
        _cloud,
        _signed,
    ) -> None:
        phone = self._session()
        dell = self._session()

        with patch("account_fantasy_preferences._load_cloud_prefs", return_value={}):
            write_account_fantasy_preferences(phone, reason="test")

        phone_doc = build_preference_document(phone, revision=1)
        phone_doc["active_draft_id"] = "3ce50b4f2e8b"
        phone_doc["active_league_context_id"] = "archive:3ce50b4f2e8b"
        phone_doc["revision"] = 2

        with patch(
            "fantasy_league_context.activate_archive_league_context",
            return_value=({"draft_id": "3ce50b4f2e8b"}, {"league_context_id": "archive:3ce50b4f2e8b"}),
        ):
            applied = sync_account_fantasy_preferences(dell, force=True)
            with patch("account_fantasy_preferences._load_cloud_prefs", return_value=phone_doc):
                applied = sync_account_fantasy_preferences(dell, force=True)

        self.assertTrue(applied.get("applied") or applied.get("changed"))
        self.assertEqual(dell.get(SESSION_APPLIED_REV_KEY), 2)

    @patch("account_fantasy_preferences._signed_in", return_value=True)
    @patch("account_fantasy_preferences._cloud_sync_available", return_value=True)
    def test_research_mode_syncs_across_devices(self, _cloud, _signed) -> None:
        phone = self._session()
        dell = self._session()
        doc = build_preference_document(phone, revision=5)
        doc["research_mode_enabled"] = True
        doc["revision"] = 5

        with patch("account_fantasy_preferences._load_cloud_prefs", return_value=doc):
            sync_account_fantasy_preferences(dell, force=True)

        self.assertTrue(dell.get(FANTASY_RESEARCH_SYNC_KEY))

    @patch("account_fantasy_preferences._signed_in", return_value=True)
    @patch("account_fantasy_preferences._cloud_sync_available", return_value=True)
    def test_older_local_cannot_overwrite_newer_cloud(self, _cloud, _signed) -> None:
        session = self._session()
        session[SESSION_APPLIED_REV_KEY] = 1
        cloud_doc = build_preference_document(session, revision=9)
        cloud_doc["active_draft_id"] = "3ce50b4f2e8b"

        with patch("account_fantasy_preferences._load_cloud_prefs", return_value=cloud_doc):
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
