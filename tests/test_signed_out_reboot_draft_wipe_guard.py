"""Reboot signed-out empty session must not wipe durable draft_archive_teams."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from workflow_persist_guard import (
    AUTH_RESTORE_CYCLE_COMPLETE_KEY,
    DRAFT_ARCHIVE_KEY,
    WORKFLOW_DRAFT_ARCHIVE_BACKUP_KEY,
    merge_protected_workflow_into_save,
    summarize_durable_draft_sources,
    workflow_empty_save_blocked_reason,
)


def _st(session: dict) -> SimpleNamespace:
    return SimpleNamespace(session_state=session)


class SignedOutRebootDraftWipeGuardTests(unittest.TestCase):
    def test_signed_out_page_change_blocked_when_disk_has_drafts(self) -> None:
        session: dict = {}
        state = {DRAFT_ARCHIVE_KEY: []}
        st = _st(session)
        disk = {DRAFT_ARCHIVE_KEY: [{"draft_id": "keep01", "draft_name": "Keep"}]}
        with patch("workflow_persist_guard._disk_migration_candidate_workspace_ids", return_value=["daniel"]):
            with patch("workflow_persist_guard._load_disk_workflow_at_workspace", return_value=disk):
                with patch("workflow_persist_guard.discover_workflow_migration_sources", return_value={"recoverable_draft_count": 0}):
                    with patch("workflow_persist_guard.probe_cloud_workflow_for_workspace", return_value={"draft_archive_count": 0}):
                        with patch("suite_auth.is_auth_enabled", return_value=True):
                            with patch("suite_auth.auth_session_complete", return_value=False):
                                reason = workflow_empty_save_blocked_reason(
                                    st, "baseball", state, save_reason="page_change", scope="all"
                                )
        self.assertEqual(reason, "signed_out_page_change_would_erase_durable_drafts")

    def test_page_change_merge_from_durable_disk_paths(self) -> None:
        persisted = {DRAFT_ARCHIVE_KEY: [{"draft_id": "disk01", "draft_name": "Disk Draft"}]}
        session = {DRAFT_ARCHIVE_KEY: []}
        state = {DRAFT_ARCHIVE_KEY: []}
        st = _st(session)
        with patch("workflow_persist_guard._disk_migration_candidate_workspace_ids", return_value=["daniel", "default"]):
            with patch("workflow_persist_guard._load_disk_workflow_at_workspace", return_value=persisted):
                with patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value={}):
                    out = merge_protected_workflow_into_save(
                        state, session, app_id="baseball", st=st, save_reason="page_change"
                    )
        self.assertEqual(len(out[DRAFT_ARCHIVE_KEY]), 1)
        self.assertEqual(out[DRAFT_ARCHIVE_KEY][0]["draft_id"], "disk01")

    def test_auth_restore_gate_blocks_cloud_page_change(self) -> None:
        session = {}
        state = {DRAFT_ARCHIVE_KEY: []}
        st = _st(session)
        with patch("workflow_persist_guard.summarize_durable_draft_sources", return_value={"max_draft_count": 1}):
            with patch("suite_auth.is_auth_enabled", return_value=True):
                with patch("suite_auth.auth_session_complete", return_value=True):
                    reason = workflow_empty_save_blocked_reason(
                        st, "baseball", state, save_reason="page_change", scope="cloud"
                    )
        self.assertEqual(reason, "auth_restore_incomplete_page_change_cloud_blocked")
        session[AUTH_RESTORE_CYCLE_COMPLETE_KEY] = True
        with patch("workflow_persist_guard.summarize_durable_draft_sources", return_value={"max_draft_count": 1}):
            with patch("suite_auth.is_auth_enabled", return_value=True):
                with patch("suite_auth.auth_session_complete", return_value=True):
                    reason = workflow_empty_save_blocked_reason(
                        st, "baseball", state, save_reason="page_change", scope="cloud"
                    )
        self.assertEqual(reason, "empty_workflow_would_erase_durable_drafts")

    def test_force_autosave_skips_disk_when_would_erase(self) -> None:
        from suite_user_persistence import force_autosave

        session: dict = {}
        st = _st(session)
        empty_state = {DRAFT_ARCHIVE_KEY: [], "comparison_state": {"players": []}}
        disk = {DRAFT_ARCHIVE_KEY: [{"draft_id": "keep01"}]}
        with patch("workflow_persist_guard._disk_migration_candidate_workspace_ids", return_value=["daniel"]):
            with patch("workflow_persist_guard._load_disk_workflow_at_workspace", return_value=disk):
                with patch("workflow_persist_guard.discover_workflow_migration_sources", return_value={"recoverable_draft_count": 0}):
                    with patch("workflow_persist_guard.probe_cloud_workflow_for_workspace", return_value={"draft_archive_count": 0}):
                        with patch("suite_auth.is_auth_enabled", return_value=True):
                            with patch("suite_auth.auth_session_complete", return_value=False):
                                with patch("suite_user_persistence.save_user_state") as mock_disk:
                                    saved = force_autosave(
                                        st,
                                        "baseball",
                                        build_state=lambda _st: empty_state,
                                        reason="page_change",
                                    )
        self.assertFalse(saved)
        mock_disk.assert_not_called()
        self.assertEqual(
            session.get("_suite_empty_startup_write_blocked"),
            "signed_out_page_change_would_erase_durable_drafts",
        )

    def test_disk_backup_written_before_erase(self) -> None:
        from suite_user_persistence import save_user_state, state_file_path

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            with patch("suite_user_persistence.DATA_DIR", data_dir):
                with patch("suite_workspace.workspace_dir", lambda ws: data_dir / "workspaces" / ws):
                    with patch("suite_workspace.resolve_workspace_id", return_value="daniel"):
                        with patch("suite_workspace.normalize_workspace_id", side_effect=lambda x: str(x)):
                            path = state_file_path("baseball", "daniel")
                            path.parent.mkdir(parents=True, exist_ok=True)
                            prior = {
                                "version": 1,
                                "app": "baseball",
                                "saved_at": "2026-01-01T00:00:00+00:00",
                                "state": {DRAFT_ARCHIVE_KEY: [{"draft_id": "old01", "draft_name": "Old"}]},
                            }
                            path.write_text(json.dumps(prior), encoding="utf-8")
                            save_user_state("baseball", {DRAFT_ARCHIVE_KEY: []}, workspace_id="daniel")
                            backup = path.with_name("baseball_user_state.draft_archive_backup.json")
                            self.assertTrue(backup.is_file())
                            backup_payload = json.loads(backup.read_text(encoding="utf-8"))
                            self.assertEqual(len(backup_payload["state"][DRAFT_ARCHIVE_KEY]), 1)

    def test_summarize_durable_includes_disk_migration_paths(self) -> None:
        session: dict = {}
        disk = {DRAFT_ARCHIVE_KEY: [{"draft_id": "d1"}, {"draft_id": "d2"}]}
        with patch("workflow_persist_guard._disk_migration_candidate_workspace_ids", return_value=["daniel"]):
            with patch("workflow_persist_guard._load_disk_workflow_at_workspace", return_value=disk):
                with patch("workflow_persist_guard.discover_workflow_migration_sources", return_value={"recoverable_draft_count": 2}):
                    with patch("workflow_persist_guard.probe_cloud_workflow_for_workspace", return_value={"draft_archive_count": 0}):
                        summary = summarize_durable_draft_sources(session, "baseball", st=_st(session))
        self.assertEqual(int(summary["disk_max"]), 2)
        self.assertEqual(int(summary["max_draft_count"]), 2)

    def test_backup_recorded_when_outbound_empty_and_durable_present(self) -> None:
        from workflow_persist_guard import WORKFLOW_DRAFT_ARCHIVE_BACKUP_KEY, maybe_backup_draft_archive_prewrite

        persisted = {DRAFT_ARCHIVE_KEY: [{"draft_id": "bak01", "draft_name": "Backup"}]}
        session = {DRAFT_ARCHIVE_KEY: []}
        state = {DRAFT_ARCHIVE_KEY: []}
        st = _st(session)
        with patch("workflow_persist_guard._disk_migration_candidate_workspace_ids", return_value=["daniel"]):
            with patch("workflow_persist_guard._load_disk_workflow_at_workspace", return_value=persisted):
                maybe_backup_draft_archive_prewrite(
                    session, state, app_id="baseball", st=st, save_reason="page_change"
                )
        self.assertEqual(len(session.get(WORKFLOW_DRAFT_ARCHIVE_BACKUP_KEY) or []), 1)


if __name__ == "__main__":
    unittest.main()
