"""Round-trip tests for saved draft library persistence (P0 gate)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from draft_archive_state import DRAFT_ARCHIVE_KEY, get_draft_archive, list_draft_archives
from draft_archive_ui import _persist_archive
from fantasy_league_context import (
    FANTASY_LEAGUE_CONTEXT_STATE_KEY,
    save_live_draft_league_context,
)
from tests.test_fantasy_league_context import _live_room_fixture
from workflow_persist_guard import merge_protected_workflow_on_restore


class DraftLibraryPersistRoundtripTests(unittest.TestCase):
    @patch("baseball_persistent_state.force_save_baseball_state", return_value=True)
    def test_live_save_persist_roundtrip(self, _mock_force: MagicMock) -> None:
        session: dict = {}
        entry, _context = save_live_draft_league_context(
            session,
            _live_room_fixture(),
            my_team_name="Daniel",
            draft_name="David vs Barry",
            defer_activation=True,
        )
        st = MagicMock()
        st.session_state = session
        self.assertTrue(_persist_archive(session, st, reason="live_draft_league_context_saved", entry=entry))
        self.assertEqual(len(list_draft_archives(session)), 1)

        from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state

        blob = build_baseball_disk_state(st)
        restored_st = MagicMock()
        restored_st.session_state = {}
        apply_baseball_disk_state(restored_st, blob)
        restored = get_draft_archive(restored_st.session_state, str(entry["draft_id"]))
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored.get("draft_name"), "David vs Barry")
        self.assertEqual(len(restored.get("draft_board") or []), 2)

    def test_union_restore_keeps_disk_drafts_when_cloud_blob_is_stale(self) -> None:
        session = {
            DRAFT_ARCHIVE_KEY: [{"draft_id": "cloud_only", "draft_name": "Cloud Draft"}],
        }
        incoming = {DRAFT_ARCHIVE_KEY: [{"draft_id": "cloud_only", "draft_name": "Cloud Draft"}]}
        disk = {
            DRAFT_ARCHIVE_KEY: [
                {"draft_id": "cloud_only", "draft_name": "Cloud Draft"},
                {"draft_id": "disk_only", "draft_name": "Disk Draft"},
            ],
        }
        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value=disk):
            with patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value={}):
                merge_protected_workflow_on_restore(session, incoming)

        ids = {str(e.get("draft_id")) for e in session[DRAFT_ARCHIVE_KEY]}
        self.assertEqual(ids, {"cloud_only", "disk_only"})

    def test_union_restore_merges_league_contexts(self) -> None:
        session: dict = {}
        incoming = {
            FANTASY_LEAGUE_CONTEXT_STATE_KEY: {
                "schema_version": 1,
                "contexts": {"ctx:a": {"league_context_id": "ctx:a"}},
                "active_league_context_id": "ctx:a",
            },
        }
        disk = {
            FANTASY_LEAGUE_CONTEXT_STATE_KEY: {
                "schema_version": 1,
                "contexts": {
                    "ctx:a": {"league_context_id": "ctx:a"},
                    "ctx:b": {"league_context_id": "ctx:b"},
                },
                "active_league_context_id": "ctx:a",
            },
        }
        with patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value=disk):
            with patch("workflow_persist_guard._load_cloud_workflow_snapshot", return_value={}):
                merge_protected_workflow_on_restore(session, incoming)

        contexts = session[FANTASY_LEAGUE_CONTEXT_STATE_KEY]["contexts"]
        self.assertEqual(set(contexts.keys()), {"ctx:a", "ctx:b"})


class CloudSaveOutcomeTests(unittest.TestCase):
    """Hosted 2026-10-26: every Live Draft and Simulator save showed "Couldn't save changes".

    The cloud host in Secrets did not resolve, so the cloud write was refused; the message hid why.
    Locally (no cloud) the same saves failed because the cloud read-back ran anyway.
    """

    def _saved(self) -> tuple[dict, dict]:
        session: dict = {}
        entry, _context = save_live_draft_league_context(
            session, _live_room_fixture(), my_team_name="Daniel", draft_name="Trial", defer_activation=True,
        )
        return session, entry

    def _persist(self, session: dict, entry: dict) -> bool:
        st = MagicMock()
        st.session_state = session
        with patch("suite_cloud_state._streamlit_session", return_value=session):
            return _persist_archive(session, st, reason="live_draft_league_context_saved", entry=entry)

    def test_unreachable_cloud_fails_and_names_the_cause(self) -> None:
        from draft_archive_ui import _persist_failure_message

        session, entry = self._saved()

        class _Storage:
            normalize_app_key = staticmethod(lambda k: k)

            @staticmethod
            def save_current_state(*_a, **_k):
                raise OSError(-2, "Name or service not known https://nm-x.supabase.co/rest/v1")

        with patch("suite_storage_config.cloud_storage_enabled", return_value=True), \
                patch("suite_cloud_state._import_storage", return_value=(_Storage, "fake")), \
                patch("suite_cloud_state.cloud_read_failure", return_value=None), \
                patch("suite_user_persistence._cloud_autosave_blocked_reason", return_value=None):
            self.assertFalse(self._persist(session, entry))
        message = _persist_failure_message(session)
        self.assertIn("Name or service not known", message)
        self.assertNotIn("supabase.co", message)
        self.assertNotIn("Try again.", message)

    def test_healthy_cloud_save_reads_back(self) -> None:
        session, entry = self._saved()
        rows: dict = {}

        class _Storage:
            normalize_app_key = staticmethod(lambda k: k)

            @staticmethod
            def save_current_state(app_key, page="", summary="", metrics=None, **_k):
                rows[app_key] = {"app": app_key, "metrics": dict(metrics or {})}

            @staticmethod
            def load_current_state_for_app(app_key, *_a, **_k):
                return rows.get(app_key)

        with patch("suite_storage_config.cloud_storage_enabled", return_value=True), \
                patch("suite_cloud_state._import_storage", return_value=(_Storage, "fake")), \
                patch("suite_cloud_state.cloud_read_failure", return_value=None), \
                patch("suite_user_persistence._cloud_autosave_blocked_reason", return_value=None):
            self.assertTrue(self._persist(session, entry))
        self.assertEqual(session["_suite_last_draft_save_readback"]["draft_ids"], [entry["draft_id"]])


if __name__ == "__main__":
    unittest.main()
