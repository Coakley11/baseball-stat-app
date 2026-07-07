"""Draft library uses compact cloud payload, not full 28MB session."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from suite_cloud_state import (
    _draft_library_slice_from_state,
    is_draft_library_cloud_save_reason,
    save_cloud_draft_library_with_details,
)


class DraftLibraryCloudSaveTests(unittest.TestCase):
    def test_is_draft_library_cloud_save_reason(self) -> None:
        self.assertTrue(is_draft_library_cloud_save_reason("draft_archive_saved"))
        self.assertTrue(is_draft_library_cloud_save_reason("draft_archive_saved_retry"))
        self.assertFalse(is_draft_library_cloud_save_reason("page_change"))

    def test_draft_library_slice_omits_league_context(self) -> None:
        state = {
            "draft_archive_teams": [{"draft_id": "d1", "draft_name": "Test"}],
            "active_draft_archive_id": "d1",
            "fantasy_league_context_state": {"contexts": {"x": {"name": "big"}}},
            "draft_room_state": {"table_records": ["huge"] * 1000},
            "active_page": "Saved Draft Library",
        }
        slim = _draft_library_slice_from_state(state)
        self.assertIn("draft_archive_teams", slim)
        self.assertEqual(slim.get("active_draft_archive_id"), "d1")
        self.assertNotIn("fantasy_league_context_state", slim)
        self.assertNotIn("draft_room_state", slim)

    @patch("suite_storage_config.cloud_storage_enabled", return_value=True)
    @patch("suite_cloud_state._import_storage")
    def test_save_cloud_draft_library_merges_and_readbacks(self, mock_import: MagicMock, _enabled: object) -> None:
        storage = MagicMock()
        storage.normalize_app_key.return_value = "baseball"
        storage.estimate_metrics_payload_bytes.return_value = 1200
        storage.save_current_state_with_result.return_value = {
            "ok": True,
            "write_mode": "patch",
            "payload_bytes": 1200,
        }
        storage.load_current_state_for_app.return_value = {
            "metrics": {
                "full_session": {
                    "draft_archive_teams": [{"draft_id": "d1", "draft_name": "A"}],
                    "active_draft_archive_id": "d1",
                }
            }
        }
        mock_import.return_value = (storage, None)

        state = {
            "draft_archive_teams": [{"draft_id": "d1", "draft_name": "A"}],
            "active_draft_archive_id": "d1",
        }
        ok, err, app_key = save_cloud_draft_library_with_details("baseball", state, summary="Saved Draft Library")
        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.assertEqual(app_key, "baseball")
        kwargs = storage.save_current_state_with_result.call_args.kwargs
        self.assertFalse(kwargs.get("direct_upsert"))
        self.assertFalse(kwargs.get("skip_metrics_merge"))
        self.assertEqual(kwargs.get("request_timeout_sec"), 25.0)
        self.assertEqual(kwargs.get("write_attempts"), 2)
        metrics = kwargs.get("metrics") or {}
        blob = metrics.get("full_session") or {}
        self.assertIn("draft_archive_teams", blob)
        self.assertNotIn("draft_room_state", blob)
        storage.load_current_state_for_app.assert_called()

    @patch("suite_storage_config.cloud_storage_enabled", return_value=True)
    @patch("suite_cloud_state._import_storage")
    def test_save_cloud_draft_library_fails_when_readback_empty(self, mock_import: MagicMock, _enabled: object) -> None:
        storage = MagicMock()
        storage.normalize_app_key.return_value = "baseball"
        storage.estimate_metrics_payload_bytes.return_value = 1200
        storage.save_current_state_with_result.return_value = {
            "ok": True,
            "write_mode": "patch",
            "payload_bytes": 1200,
        }
        storage.load_current_state_for_app.return_value = {
            "metrics": {"full_session": {"draft_archive_teams": [], "active_page": "Historical Explorer"}}
        }
        mock_import.return_value = (storage, None)

        state = {
            "draft_archive_teams": [{"draft_id": "d1", "draft_name": "A"}],
            "active_draft_archive_id": "d1",
        }
        ok, err, _app_key = save_cloud_draft_library_with_details("baseball", state)
        self.assertFalse(ok)
        self.assertIn("readback", err)

    @patch("suite_user_persistence.save_user_state", return_value=True)
    @patch("suite_cloud_state.session_page_summary", return_value=("Saved Draft Library", "Saved Draft Library"))
    @patch("suite_cloud_state.save_cloud_draft_library_with_details", return_value=(True, "", "baseball"))
    @patch("suite_cloud_state.save_cloud_full_session_with_details", return_value=(False, "should_not_call", "baseball"))
    def test_force_autosave_routes_draft_archive_to_compact_cloud(
        self,
        mock_full: MagicMock,
        mock_draft: MagicMock,
        _summary: MagicMock,
        _disk: MagicMock,
    ) -> None:
        from suite_user_persistence import force_autosave

        st = MagicMock()
        st.session_state = {}
        ok = force_autosave(
            st,
            "baseball",
            build_state=lambda _st: {
                "draft_archive_teams": [{"draft_id": "d1"}],
                "active_draft_archive_id": "d1",
            },
            reason="draft_archive_saved",
        )
        self.assertTrue(ok)
        mock_draft.assert_called_once()
        mock_full.assert_not_called()


if __name__ == "__main__":
    unittest.main()
