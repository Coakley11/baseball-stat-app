"""Daniel admin identity + legacy null cloud draft migration on authenticated restore."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from workflow_persist_guard import DRAFT_ARCHIVE_KEY, enrich_cloud_restore_state


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
    def test_enrich_restore_merges_legacy_null_blob_when_signed_in(self) -> None:
        session = _auth_session(
            user_id="uuid-daniel",
            email="daniel.cohen11@example.com",
            external_id="daniel",
        )
        st = _FakeSt(session)
        legacy_blob = {
            DRAFT_ARCHIVE_KEY: [
                {"draft_id": "draft_uploaded_trial", "draft_name": "Uploaded trial League"},
                {"draft_id": "draft_two", "draft_name": "Second draft"},
            ],
            "active_page": "Saved Draft Library",
        }
        with patch("suite_auth.is_auth_enabled", return_value=True), patch(
            "suite_auth.is_authenticated", return_value=True
        ), patch(
            "workflow_persist_guard._load_cloud_workflow_snapshot", return_value={}
        ), patch(
            "workflow_persist_guard._load_legacy_null_migration_blob", return_value=legacy_blob
        ):
            out = enrich_cloud_restore_state("baseball", st, {})
            archives = out.get(DRAFT_ARCHIVE_KEY) or []
            self.assertEqual(len(archives), 2)
            self.assertEqual(out.get("active_page"), "Saved Draft Library")


if __name__ == "__main__":
    unittest.main()
