"""Insight dismiss persistence and restore guards."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from applied_math_return_insight import (
    SESSION_DISMISSED_KEY,
    SESSION_PENDING_KEY,
    _pending_insight_valid,
    dismiss_applied_math_insight,
)
from baseball_persistent_state import apply_baseball_disk_state


class _FakeSt:
    def __init__(self) -> None:
        self.session_state: dict = {}


class TestInsightDismiss(unittest.TestCase):
    def test_dismiss_clears_pending_and_blocks_valid(self) -> None:
        st = _FakeSt()
        st.session_state[SESSION_PENDING_KEY] = {
            "insight_id": "abc123",
            "conclusion": "Test conclusion",
            "question": "Why draft now?",
            "source_app": "baseball",
        }
        with patch("applied_math_return_insight.persist_insight_dismissal_to_cloud"), patch(
            "baseball_persistent_state.force_save_baseball_state", return_value=True
        ):
            dismiss_applied_math_insight(st)
        self.assertIsNone(st.session_state.get(SESSION_PENDING_KEY))
        self.assertIn("abc123", st.session_state.get(SESSION_DISMISSED_KEY) or [])
        self.assertFalse(_pending_insight_valid(st))

    def test_disk_restore_skips_dismissed_pending(self) -> None:
        st = _FakeSt()
        st.session_state[SESSION_DISMISSED_KEY] = ["keep-dismissed"]
        apply_baseball_disk_state(
            st,
            {
                "_ami_pending_insight": {
                    "insight_id": "keep-dismissed",
                    "conclusion": "Should not restore",
                },
                "_ami_dismissed_insight_ids": ["keep-dismissed"],
            },
        )
        self.assertNotIn(SESSION_PENDING_KEY, st.session_state)


if __name__ == "__main__":
    unittest.main()
