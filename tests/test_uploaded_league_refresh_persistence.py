"""Uploaded 4-team league must survive disk restore + visibility sanitize (refresh sim)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from draft_archive_state import list_draft_archives
from draft_archive_visibility import (
    list_visible_draft_archives,
    prune_invisible_shared_league_state,
    sanitize_workflow_library_for_account,
)
from fantasy_league_context import (
    archive_card_team_count,
    save_imported_league_context,
)
from fantasy_league_team_ownership import account_user_ids_match
from tests.test_fantasy_trade_proposals import _as_user
from tests.test_imported_shared_league import _sample_board


def _four_team_board() -> pd.DataFrame:
    return _sample_board()
from workflow_persist_guard import (
    DRAFT_ARCHIVE_KEY,
    ensure_session_workflow_hydrated,
    merge_protected_workflow_on_restore,
)

_DANIEL_UUID = "f66b85aa-1192-4f93-a669-d238bcd6858b"


def _daniel_auth_session(*, cloud_user_id: str = _DANIEL_UUID) -> dict:
    return {
        "_suite_auth_session": True,
        "_suite_auth_user_id": cloud_user_id,
        "_suite_auth_user_email": "daniel.cohen11@yahoo.com",
        "_suite_auth_external_id": "daniel",
        "_suite_cloud_user_id": cloud_user_id,
        "_suite_active_workspace_id": "daniel",
        "_suite_owned_workspace_id": "daniel",
        "draft_shared_settings": {"fantasy_format": "5x5 Roto"},
    }


class UploadedLeagueRefreshPersistenceTests(unittest.TestCase):
    def test_local_owner_id_survives_cloud_uuid_restore(self) -> None:
        """Save with local:daniel ownership; refresh as signed-in cloud UUID — still visible."""
        session = _daniel_auth_session()
        with _as_user("local:daniel"):
            entry, context = save_imported_league_context(
                session,
                _four_team_board(),
                my_team_name="Daniel",
                draft_name="Office League 2026",
                save_only=True,
                assign_team=True,
            )
        ownership = (context.get("metadata") or {}).get("team_ownership") or {}
        daniel_rec = ownership.get("Daniel") or {}
        self.assertTrue(str(daniel_rec.get("user_id") or "").startswith("local:"))

        refreshed = _daniel_auth_session()
        refreshed[DRAFT_ARCHIVE_KEY] = list(session.get(DRAFT_ARCHIVE_KEY) or [])
        refreshed["fantasy_league_context_state"] = dict(session.get("fantasy_league_context_state") or {})
        st = MagicMock()
        st.session_state = refreshed

        with _as_user(_DANIEL_UUID), patch(
            "fantasy_league_team_ownership._resolve_user_id", return_value=_DANIEL_UUID
        ), patch("suite_user.get_account_user_id", return_value=_DANIEL_UUID), patch(
            "suite_user.get_external_user_id", return_value="daniel"
        ):
            self.assertTrue(
                account_user_ids_match(str(daniel_rec.get("user_id") or ""), _DANIEL_UUID)
            )
            removed = prune_invisible_shared_league_state(refreshed)
            self.assertEqual(removed.get("archives_removed"), 0)
            self.assertEqual(len(list_visible_draft_archives(refreshed)), 1)
            self.assertEqual(archive_card_team_count(entry), 4)

    def test_disk_blob_roundtrip_keeps_four_teams_and_library_page(self) -> None:
        session = _daniel_auth_session()
        with _as_user(_DANIEL_UUID), patch(
            "fantasy_league_team_ownership._resolve_user_id", return_value=_DANIEL_UUID
        ):
            entry, _context = save_imported_league_context(
                session,
                _four_team_board(),
                my_team_name="Daniel",
                draft_name="Office League 2026",
                save_only=True,
                assign_team=True,
            )
        session["active_page"] = "Saved Draft Library"
        session["main_sidebar_page"] = "Saved Draft Library"
        session["_suite_last_persisted_page"] = "Saved Draft Library"

        from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state

        st = MagicMock()
        st.session_state = session
        blob = build_baseball_disk_state(st)

        refreshed_st = MagicMock()
        refreshed_st.session_state = _daniel_auth_session()
        with _as_user(_DANIEL_UUID), patch(
            "fantasy_league_team_ownership._resolve_user_id", return_value=_DANIEL_UUID
        ), patch("suite_user.get_account_user_id", return_value=_DANIEL_UUID), patch(
            "suite_user.get_external_user_id", return_value="daniel"
        ), patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value={}), patch(
            "workflow_persist_guard._load_cloud_workflow_snapshot", return_value={}
        ):
            apply_baseball_disk_state(refreshed_st, blob)
            ss = refreshed_st.session_state
            self.assertEqual(ss.get("active_page"), "Saved Draft Library")
            self.assertEqual(len(list_draft_archives(ss)), 1)
            restored = list_draft_archives(ss)[0]
            self.assertEqual(str(restored.get("draft_id")), str(entry.get("draft_id")))
            self.assertEqual(archive_card_team_count(restored), 4)
            removed = prune_invisible_shared_league_state(ss)
            self.assertEqual(removed.get("archives_removed"), 0)

    def test_empty_session_hydrates_uploaded_league_from_cloud(self) -> None:
        session = _daniel_auth_session()
        with _as_user(_DANIEL_UUID), patch(
            "fantasy_league_team_ownership._resolve_user_id", return_value=_DANIEL_UUID
        ):
            entry, _context = save_imported_league_context(
                session,
                _four_team_board(),
                my_team_name="Daniel",
                draft_name="Office League 2026",
                save_only=True,
                assign_team=True,
            )
        cloud_blob = {
            DRAFT_ARCHIVE_KEY: list(session.get(DRAFT_ARCHIVE_KEY) or []),
            "fantasy_league_context_state": dict(session.get("fantasy_league_context_state") or {}),
            "active_page": "Saved Draft Library",
            "main_sidebar_page": "Saved Draft Library",
        }
        empty = _daniel_auth_session()
        st = MagicMock()
        st.session_state = empty
        with _as_user(_DANIEL_UUID), patch(
            "fantasy_league_team_ownership._resolve_user_id", return_value=_DANIEL_UUID
        ), patch("suite_user.get_account_user_id", return_value=_DANIEL_UUID), patch(
            "suite_user.get_external_user_id", return_value="daniel"
        ), patch(
            "workflow_persist_guard._load_cloud_workflow_snapshot", return_value=cloud_blob
        ), patch("workflow_persist_guard._load_disk_workflow_snapshot", return_value={}):
            out = ensure_session_workflow_hydrated(st, "baseball", cloud_state=cloud_blob)
            self.assertTrue(out.get("hydrated"))
            self.assertEqual(len(list_draft_archives(empty)), 1)
            self.assertEqual(str(list_draft_archives(empty)[0].get("draft_id")), str(entry.get("draft_id")))
            self.assertEqual(empty.get("active_page"), "Saved Draft Library")

    def test_sanitize_does_not_persist_empty_library_for_upload_owner(self) -> None:
        session = _daniel_auth_session()
        with _as_user("local:daniel"):
            save_imported_league_context(
                session,
                _four_team_board(),
                my_team_name="Daniel",
                draft_name="Office League 2026",
                save_only=True,
                assign_team=True,
            )
        st = MagicMock()
        st.session_state = session
        with _as_user(_DANIEL_UUID), patch(
            "suite_user.get_external_user_id", return_value="daniel"
        ), patch(
            "baseball_persistent_state.force_save_baseball_state", return_value=True
        ) as cloud_save, patch(
            "suite_user_persistence.save_user_state", return_value=True
        ) as disk_save:
            out = sanitize_workflow_library_for_account(session, st=st, persist_cleanup=True)
            self.assertEqual(out.get("total_removed"), 0)
            cloud_save.assert_not_called()
            disk_save.assert_not_called()
            self.assertEqual(len(list_visible_draft_archives(session)), 1)


if __name__ == "__main__":
    unittest.main()
