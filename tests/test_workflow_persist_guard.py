"""Tests for workflow partial-save protection."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from workflow_persist_guard import (
    DRAFT_ARCHIVE_KEY,
    LEAGUE_CONTEXT_STATE_KEY,
    WORKFLOW_PERSIST_ALLOW_CLEAR_KEY,
    build_saved_draft_library_diagnostics,
    merge_protected_workflow_into_save,
    probe_cloud_workflow_for_workspace,
)


class WorkflowPersistGuardTests(unittest.TestCase):
    def test_partial_save_merges_draft_archives_from_disk(self) -> None:
        persisted = {
            DRAFT_ARCHIVE_KEY: [
                {"draft_id": "abc123", "draft_name": "Home League", "players": [{"player_name": "Judge"}]},
            ],
            LEAGUE_CONTEXT_STATE_KEY: {
                "contexts": {"ctx:abc123": {"league_context_id": "ctx:abc123", "display_name": "Home"}},
                "active_league_context_id": "ctx:abc123",
            },
        }
        session: dict = {"use_active_league_context_waiver_filter": True}
        state: dict = {"page_filter_state": {}}

        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value=persisted):
            with patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value={}):
                out = merge_protected_workflow_into_save(
                    state,
                    session,
                    save_reason="waiver_pending_pair",
                )

        self.assertEqual(len(out[DRAFT_ARCHIVE_KEY]), 1)
        self.assertEqual(out[DRAFT_ARCHIVE_KEY][0]["draft_id"], "abc123")
        self.assertEqual(len(out[LEAGUE_CONTEXT_STATE_KEY]["contexts"]), 1)
        self.assertIn(DRAFT_ARCHIVE_KEY, session)
        merged = session.get("_suite_workflow_persist_merged_keys") or []
        self.assertIn(DRAFT_ARCHIVE_KEY, merged)
        self.assertIn(LEAGUE_CONTEXT_STATE_KEY, merged)

    def test_intentional_empty_archive_not_merged_when_authoritative(self) -> None:
        persisted = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "abc123", "draft_name": "Old"}],
        }
        session = {DRAFT_ARCHIVE_KEY: [], WORKFLOW_PERSIST_ALLOW_CLEAR_KEY: True}
        state = {DRAFT_ARCHIVE_KEY: []}

        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value=persisted):
            out = merge_protected_workflow_into_save(state, session, save_reason="waiver_pending_pair")

        self.assertEqual(out[DRAFT_ARCHIVE_KEY], [])
        self.assertNotIn(WORKFLOW_PERSIST_ALLOW_CLEAR_KEY, session)

    def test_explicit_clear_reason_skips_merge(self) -> None:
        persisted = {DRAFT_ARCHIVE_KEY: [{"draft_id": "abc123"}]}
        session: dict = {}
        state: dict = {}

        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value=persisted):
            out = merge_protected_workflow_into_save(state, session, save_reason="draft_archive_cleared")

        self.assertNotIn(DRAFT_ARCHIVE_KEY, out)

    def test_empty_lazy_league_context_merges_from_disk(self) -> None:
        persisted = {
            LEAGUE_CONTEXT_STATE_KEY: {
                "contexts": {"ctx:1": {"league_context_id": "ctx:1"}},
                "active_league_context_id": "ctx:1",
            },
        }
        session = {
            LEAGUE_CONTEXT_STATE_KEY: {"contexts": {}, "active_league_context_id": "", "schema_version": 1},
        }
        state = {LEAGUE_CONTEXT_STATE_KEY: session[LEAGUE_CONTEXT_STATE_KEY]}

        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value=persisted):
            out = merge_protected_workflow_into_save(state, session, save_reason="waiver_filter_changed")

        self.assertEqual(len(out[LEAGUE_CONTEXT_STATE_KEY]["contexts"]), 1)

    def test_build_saved_draft_library_diagnostics(self) -> None:
        session = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "x1"}],
            LEAGUE_CONTEXT_STATE_KEY: {"contexts": {"ctx:1": {}}},
            "_suite_persist_last_restore_source": "cloud",
            "_suite_persist_last_restore_at": "2026-07-05T00:00:00+00:00",
        }
        diag = build_saved_draft_library_diagnostics(session)
        self.assertEqual(diag["draft_archive_count"], 1)
        self.assertEqual(diag["league_context_count"], 1)
        self.assertEqual(diag["restore_source"], "cloud")
        self.assertIn("cloud", diag["restore_source_label"].lower())

    def test_build_disk_state_applies_merge(self) -> None:
        from baseball_persistent_state import build_baseball_disk_state

        persisted = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "keep01", "draft_name": "Keep"}],
        }
        st = MagicMock()
        st.session_state = {"page_filter_state": {}, "_suite_pending_save_reason": "waiver_pending_pair"}

        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value=persisted):
            with patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value={}):
                blob = build_baseball_disk_state(st)

        self.assertEqual(len(blob.get(DRAFT_ARCHIVE_KEY) or []), 1)


class WorkflowPersistGuardDiskRoundtripTests(unittest.TestCase):
    def test_save_after_partial_session_preserves_disk_archives(self) -> None:
        from baseball_persistent_state import build_baseball_disk_state

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            ws_dir = data / "workspaces" / "daniel"
            ws_dir.mkdir(parents=True)
            payload = {
                "version": 1,
                "app": "baseball",
                "saved_at": "2026-07-01T00:00:00+00:00",
                "state": {
                    DRAFT_ARCHIVE_KEY: [{"draft_id": "disk01", "draft_name": "Disk Draft"}],
                    LEAGUE_CONTEXT_STATE_KEY: {
                        "contexts": {"ctx:disk01": {"league_context_id": "ctx:disk01"}},
                    },
                },
            }
            (ws_dir / "baseball_user_state.json").write_text(json.dumps(payload), encoding="utf-8")

            st = MagicMock()
            st.session_state = {
                "page_filter_state": {},
                "_suite_pending_save_reason": "waiver_filter_changed",
            }

            with patch("suite_workspace.DATA_DIR", data), patch("suite_user_persistence.DATA_DIR", data):
                with patch("suite_workspace.load_persisted_workspace_id", return_value="daniel"):
                    blob = build_baseball_disk_state(st)

            self.assertEqual(len(blob.get(DRAFT_ARCHIVE_KEY) or []), 1)
            self.assertEqual(blob[DRAFT_ARCHIVE_KEY][0]["draft_id"], "disk01")


if __name__ == "__main__":
    unittest.main()
