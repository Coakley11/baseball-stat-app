"""Tests for authenticated disk/session → cloud draft migration writeback."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from workflow_persist_guard import (
    AUTH_MIGRATION_WRITEBACK_ATTEMPTED_KEY,
    AUTH_MIGRATION_WRITEBACK_OK_KEY,
    AUTH_MIGRATION_WRITEBACK_TRACE_KEY,
    DRAFT_ARCHIVE_KEY,
    _authenticated_migration_writeback_eligible,
    is_draft_library_mutation_save_reason,
    maybe_authenticated_workflow_cloud_writeback,
)


def _st(session: dict) -> SimpleNamespace:
    return SimpleNamespace(session_state=session)


class AuthenticatedMigrationWritebackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session: dict = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "d1", "draft_name": "Uploaded League"}],
            "_suite_auth_user_id": "f66b85aa-1192-4f93-a669-d238bcd6858b",
            "_suite_auth_signed_in": True,
            "_suite_auth_access_token": "tok",
            "_suite_auth_refresh_token": "ref",
        }
        self.st = _st(self.session)

    @patch("workflow_persist_guard.probe_cloud_workflow_for_workspace", return_value={"draft_archive_count": 0})
    @patch("workflow_persist_guard.discover_workflow_migration_sources", return_value={"recoverable_draft_count": 1})
    @patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value={DRAFT_ARCHIVE_KEY: [{"draft_id": "d1"}]})
    @patch("suite_storage_config.cloud_storage_enabled", return_value=True)
    @patch("suite_auth.auth_session_complete", return_value=True)
    @patch("suite_auth.is_auth_enabled", return_value=True)
    def test_eligible_when_signed_in_local_drafts_cloud_empty(
        self,
        _auth_enabled,
        _auth_complete,
        _cloud_enabled,
        _disk,
        _discovery,
        _cloud_probe,
    ) -> None:
        ok, skip = _authenticated_migration_writeback_eligible(self.session, st=self.st)
        self.assertTrue(ok)
        self.assertEqual(skip, "")

    @patch("workflow_persist_guard.probe_cloud_workflow_for_workspace", return_value={"draft_archive_count": 2})
    @patch("workflow_persist_guard.discover_workflow_migration_sources", return_value={"recoverable_draft_count": 1})
    @patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value={})
    @patch("suite_storage_config.cloud_storage_enabled", return_value=True)
    @patch("suite_auth.auth_session_complete", return_value=True)
    @patch("suite_auth.is_auth_enabled", return_value=True)
    def test_skipped_when_cloud_has_drafts(
        self,
        _auth_enabled,
        _auth_complete,
        _cloud_enabled,
        _disk,
        _discovery,
        _cloud_probe,
    ) -> None:
        ok, skip = _authenticated_migration_writeback_eligible(self.session, st=self.st)
        self.assertFalse(ok)
        self.assertEqual(skip, "cloud_already_has_drafts")

    @patch("workflow_persist_guard.record_draft_library_readback")
    @patch(
        "workflow_persist_guard.verify_cloud_draft_library_readback",
        return_value={"ok": True, "draft_count": 1, "draft_ids": ["d1"], "error": ""},
    )
    @patch("baseball_persistent_state.force_save_baseball_state", return_value=True)
    @patch("workflow_persist_guard.merge_protected_workflow_on_restore")
    @patch("workflow_persist_guard.probe_cloud_workflow_for_workspace", return_value={"draft_archive_count": 0})
    @patch("workflow_persist_guard.discover_workflow_migration_sources", return_value={"recoverable_draft_count": 1})
    @patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value={DRAFT_ARCHIVE_KEY: [{"draft_id": "d1"}]})
    @patch("suite_storage_config.cloud_storage_enabled", return_value=True)
    @patch("suite_auth.auth_session_complete", return_value=True)
    @patch("suite_auth.is_auth_enabled", return_value=True)
    def test_writeback_triggers_force_save_and_readback(
        self,
        _auth_enabled,
        _auth_complete,
        _cloud_enabled,
        _disk,
        _discovery,
        _cloud_probe,
        _merge,
        mock_force_save,
        mock_readback,
        _record,
    ) -> None:
        self.session["_suite_persist_last_save_cloud"] = True
        self.session["_suite_last_cloud_app_key"] = "baseball:daniel"

        trace = maybe_authenticated_workflow_cloud_writeback(self.st)

        self.assertTrue(trace["attempted"])
        self.assertTrue(trace["ok"])
        self.assertTrue(self.session.get(AUTH_MIGRATION_WRITEBACK_ATTEMPTED_KEY))
        self.assertTrue(self.session.get(AUTH_MIGRATION_WRITEBACK_OK_KEY))
        mock_force_save.assert_called_once()
        self.assertEqual(mock_force_save.call_args.kwargs.get("reason"), "authenticated_migration_writeback")
        mock_readback.assert_called_once()
        self.assertEqual(int(trace["cloud_readback_count"]), 1)
        stored = self.session.get(AUTH_MIGRATION_WRITEBACK_TRACE_KEY)
        self.assertIsInstance(stored, dict)
        self.assertTrue(stored.get("cloud_readback_ok"))

    def test_save_reason_is_draft_library_mutation(self) -> None:
        self.assertTrue(is_draft_library_mutation_save_reason("authenticated_migration_writeback"))


if __name__ == "__main__":
    unittest.main()
