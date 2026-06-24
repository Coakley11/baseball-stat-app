"""Regression tests for foreign blob restore guard and pool dedupe."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from live_draft_state import live_draft_get_available


class ApplyBaseballDiskStateForeignBlobTests(unittest.TestCase):
    def test_apply_state_does_not_crash_on_foreign_blob_check(self) -> None:
        from baseball_persistent_state import apply_baseball_disk_state

        ss: dict = {
            "_suite_auth_session": True,
            "_suite_auth_user_id": "uuid-coakley",
            "_suite_auth_user_email": "coakley11@aol.com",
        }
        state = {
            "room_your_team": "Daniel",
            "page_filter_state": {
                "Live Draft Room": {"live_draft_room": {"draft_room_id": "X1", "status": "in_progress"}},
            },
            "live_draft_state": {"draft_room_id": "X1", "status": "in_progress", "draft_board": []},
        }
        st = SimpleNamespace(session_state=ss)
        with patch("live_draft_state._current_auth_external_id", return_value="coakley11"):
            with patch("live_draft_state._current_workspace_id", return_value="daniel"):
                with patch("suite_auth.is_auth_enabled", return_value=True):
                    apply_baseball_disk_state(st, state)
        self.assertNotIn("room_your_team", ss)
        self.assertIn(
            ss.get("_live_draft_restore_blocked_reason"),
            ("foreign_daniel_workspace", "legacy_unowned_foreign_blob", "legacy_shared_cloud_blob"),
        )


class LiveDraftPoolDedupeTests(unittest.TestCase):
    def test_duplicate_fullname_columns_deduped_for_availability(self) -> None:
        base = pd.DataFrame(
            {
                "fullName": ["Shohei Ohtani", "Aaron Judge"],
                "playerID": ["1", "2"],
            }
        )
        pool = pd.concat([base["fullName"], base["fullName"], base["playerID"]], axis=1)
        pool.columns = ["fullName", "fullName", "playerID"]
        room = {"pool": pool}
        out = live_draft_get_available(room)
        self.assertFalse(out.empty)
        col_diag = room.get("_live_draft_pool_column_diag") or {}
        self.assertTrue(col_diag.get("deduped"))
        names = out["fullName"].astype(str).tolist()
        self.assertIn("Shohei Ohtani", names)


if __name__ == "__main__":
    unittest.main()
