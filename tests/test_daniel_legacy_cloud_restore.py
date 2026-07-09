"""Daniel admin identity + legacy / alternate-user cloud draft migration on restore."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from workflow_persist_guard import (
    DRAFT_ARCHIVE_KEY,
    _load_cloud_workflow_snapshot,
    enrich_cloud_restore_state,
)


def _auth_session(*, user_id: str, email: str, external_id: str) -> dict:
    return {
        "_suite_auth_session": True,
        "_suite_auth_user_id": user_id,
        "_suite_auth_user_email": email,
        "_suite_auth_external_id": external_id,
    }


class _FakeSt:
    def __init__(self, session: dict) -> None:
        self.session_state = session


class TestDanielLegacyCloudRestore(unittest.TestCase):
    def test_enrich_restore_merges_migration_blob_when_signed_in(self) -> None:
        session = _auth_session(
            user_id="uuid-daniel",
            email="daniel.cohen11@example.com",
            external_id="daniel",
        )
        st = _FakeSt(session)
        migration_blob = {
            DRAFT_ARCHIVE_KEY: [
                {"draft_id": "draft_uploaded_trial", "draft_name": "Uploaded trial League"},
                {"draft_id": "draft_two", "draft_name": "Second draft"},
            ],
            "active_page": "Saved Draft Library",
        }
        with patch("suite_auth.is_auth_enabled", return_value=True), patch(
            "suite_auth.is_authenticated", return_value=True
        ), patch(
            "workflow_persist_guard._load_cloud_workflow_snapshot", return_value=migration_blob
        ):
            out = enrich_cloud_restore_state("baseball", st, {})
            archives = out.get(DRAFT_ARCHIVE_KEY) or []
            self.assertEqual(len(archives), 2)
            self.assertEqual(out.get("active_page"), "Saved Draft Library")

    def test_authenticated_snapshot_merges_alternate_user_id_cloud_rows(self) -> None:
        session = _auth_session(
            user_id="f66b85aa-1192-4f93-a669-d238bcd6858b",
            email="daniel.cohen11@yahoo.com",
            external_id="daniel",
        )
        st = _FakeSt(session)
        current_blob = {DRAFT_ARCHIVE_KEY: []}
        legacy_blob = {
            DRAFT_ARCHIVE_KEY: [
                {"draft_id": "draft_uploaded_trial", "draft_name": "Uploaded trial League"},
            ],
        }
        old_user_blob = {
            DRAFT_ARCHIVE_KEY: [
                {"draft_id": "draft_two", "draft_name": "Second draft"},
            ],
        }

        def _fake_migration_blobs(_app_id: str, _session: dict) -> list[dict]:
            return [legacy_blob, old_user_blob]

        with patch("suite_auth.is_auth_enabled", return_value=True), patch(
            "suite_auth.is_authenticated", return_value=True
        ), patch("suite_workspace_registry.is_admin_account", return_value=True), patch(
            "suite_cloud_state.load_cloud_full_session", return_value=(current_blob, {})
        ), patch(
            "workflow_persist_guard._load_authenticated_migration_cloud_blobs",
            side_effect=_fake_migration_blobs,
        ), patch(
            "workflow_persist_guard._load_disk_workflow_at_workspace", return_value={}
        ):
            out = _load_cloud_workflow_snapshot("baseball", st)
            archives = out.get(DRAFT_ARCHIVE_KEY) or []
            self.assertEqual(len(archives), 2)
            names = {str(a.get("draft_name")) for a in archives if isinstance(a, dict)}
            self.assertIn("Uploaded trial League", names)
            self.assertIn("Second draft", names)


class TestMigrationAdminOnly(unittest.TestCase):
    def test_coakley11_not_eligible_for_cross_user_migration(self) -> None:
        from workflow_persist_guard import _authenticated_cloud_migration_eligible

        session = _auth_session(
            user_id="961df5e0-cdde-48d7-80dd-95a8ba3f46e5",
            email="coakley11@aol.com",
            external_id="coakley11",
        )
        with patch("suite_auth.is_auth_enabled", return_value=True), patch(
            "suite_auth.is_authenticated", return_value=True
        ), patch("suite_workspace_registry.is_admin_account", return_value=False):
            self.assertFalse(_authenticated_cloud_migration_eligible(session))

    def test_daniel_eligible_for_cross_user_migration(self) -> None:
        from workflow_persist_guard import _authenticated_cloud_migration_eligible

        session = _auth_session(
            user_id="f66b85aa-1192-4f93-a669-d238bcd6858b",
            email="daniel.cohen11@yahoo.com",
            external_id="daniel",
        )
        with patch("suite_auth.is_auth_enabled", return_value=True), patch(
            "suite_auth.is_authenticated", return_value=True
        ), patch("suite_workspace_registry.is_admin_account", return_value=True):
            self.assertTrue(_authenticated_cloud_migration_eligible(session))


if __name__ == "__main__":
    unittest.main()
