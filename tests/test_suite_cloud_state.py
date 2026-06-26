"""Regression tests for suite cloud save helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from suite_cloud_state import save_cloud_full_session_with_result


class SaveCloudFullSessionWithResultTests(unittest.TestCase):
    def test_resolves_without_importerror(self) -> None:
        self.assertTrue(callable(save_cloud_full_session_with_result))

    @patch("suite_cloud_state.save_cloud_full_session", return_value=True)
    @patch("suite_cloud_state.load_cloud_full_session", return_value=({}, "2026-06-25T00:00:00"))
    @patch("draft_room_state.draft_room_restore_stats", return_value={"pick_count": 4})
    def test_readback_pick_count_ok(self, _stats, _load, _save) -> None:
        ok, err = save_cloud_full_session_with_result(
            "baseball",
            {"draft_room_state": {"board": []}},
            page="Live Draft Room",
            summary="test",
            min_draft_pick_count=4,
        )
        self.assertTrue(ok)
        self.assertEqual(err, "")

    @patch("suite_cloud_state.save_cloud_full_session", return_value=True)
    @patch("suite_cloud_state.load_cloud_full_session", return_value=({}, "2026-06-25T00:00:00"))
    @patch("draft_room_state.draft_room_restore_stats", return_value={"pick_count": 2})
    def test_readback_pick_count_mismatch(self, _stats, _load, _save) -> None:
        ok, err = save_cloud_full_session_with_result(
            "baseball",
            {"draft_room_state": {"board": []}},
            min_draft_pick_count=4,
        )
        self.assertFalse(ok)
        self.assertIn("readback_pick_mismatch", err)

    @patch("suite_cloud_state.save_cloud_full_session", return_value=False)
    def test_cloud_save_failed(self, _save) -> None:
        ok, err = save_cloud_full_session_with_result("baseball", {"active_page": "Home"})
        self.assertFalse(ok)
        self.assertEqual(err, "cloud_save_failed")


if __name__ == "__main__":
    unittest.main()
