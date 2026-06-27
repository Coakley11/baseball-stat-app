"""Insight dismiss persistence and restore guards."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from applied_math_return_insight import (
    SESSION_DISMISSED_KEY,
    SESSION_PENDING_KEY,
    _pending_insight_valid,
    dismiss_applied_math_insight,
    ensure_baseball_pending_insight_for_render,
    resolve_pending_insight_for_render,
)
from baseball_persistent_state import apply_baseball_disk_state
from hall_of_fame_data import CAREER_HOF_CASE_MODE_KEY, CAREER_HOF_CASE_TARGET_KEY


class _FakeSt:
    def __init__(self) -> None:
        self.session_state: dict = {}


class TestInsightDismiss(unittest.TestCase):
    def test_dismiss_clears_pending_and_blocks_valid(self) -> None:
        st = _FakeSt()
        st.session_state[SESSION_PENDING_KEY] = {
            "insight_id": "abc123",
            "question_id": "qid-456",
            "conclusion": "Test conclusion",
            "question": "Why draft now?",
            "source_app": "baseball",
        }
        st.session_state["_hof_case_insight_staged_for_resume"] = "qid-456"
        with patch("applied_math_return_insight.persist_insight_dismissal_to_cloud"), patch(
            "baseball_persistent_state.force_save_baseball_state", return_value=True
        ):
            dismiss_applied_math_insight(st)
        self.assertIsNone(st.session_state.get(SESSION_PENDING_KEY))
        self.assertIn("abc123", st.session_state.get(SESSION_DISMISSED_KEY) or [])
        self.assertIn("qid-456", st.session_state.get("_ami_dismissed_question_ids") or [])
        self.assertEqual(st.session_state.get("_hof_case_insight_staged_for_resume"), "qid-456")
        self.assertFalse(_pending_insight_valid(st))

    def test_dismiss_preserves_hof_case_mode(self) -> None:
        st = _FakeSt()
        st.session_state[CAREER_HOF_CASE_MODE_KEY] = True
        st.session_state[CAREER_HOF_CASE_TARGET_KEY] = "Albert Pujols"
        st.session_state[SESSION_PENDING_KEY] = {
            "insight_id": "hof123",
            "question_id": "q-hof",
            "conclusion": "HOF case summary",
            "source_app": "baseball",
        }
        with patch("applied_math_return_insight.persist_insight_dismissal_to_cloud"), patch(
            "baseball_persistent_state.force_save_baseball_state", return_value=True
        ):
            dismiss_applied_math_insight(st, app_key="baseball")
        self.assertTrue(st.session_state.get(CAREER_HOF_CASE_MODE_KEY))
        self.assertEqual(st.session_state.get(CAREER_HOF_CASE_TARGET_KEY), "Albert Pujols")

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

    def test_ensure_baseball_does_not_restore_dismissed_submit_snapshot(self) -> None:
        st = _FakeSt()
        dismissed = {
            "insight_id": "hof-dismissed",
            "question_id": "q-dismissed",
            "conclusion": "HOF summary line",
            "short_answer": "HOF summary line",
            "source_app": "baseball",
        }
        st.session_state["_ami_dismissed_insight_ids"] = ["hof-dismissed"]
        st.session_state["_ami_dismissed_question_ids"] = ["q-dismissed"]
        st.session_state["_hof_case_submit_pending_insight"] = dismissed
        st.session_state["_hof_case_last_submit_bundle"] = {"insight": dismissed}
        st.session_state["_ami_force_insight_render"] = True
        restored = ensure_baseball_pending_insight_for_render(st)
        self.assertFalse(restored)
        self.assertIsNone(st.session_state.get(SESSION_PENDING_KEY))

    def test_resolve_pending_insight_respects_dismiss_after_hydrate(self) -> None:
        st = _FakeSt()
        dismissed = {
            "insight_id": "hof-dismissed",
            "question_id": "q-dismissed",
            "conclusion": "Should stay hidden",
            "source_app": "baseball",
        }
        st.session_state["_ami_dismissed_question_ids"] = ["q-dismissed"]
        st.session_state["_ami_dismissed_insight_ids"] = ["hof-dismissed"]
        st.session_state["_hof_case_last_ami_blob"] = {"insight": dismissed}
        st.session_state["_ami_force_insight_render"] = True
        insight = resolve_pending_insight_for_render(st, app="baseball")
        self.assertFalse(insight)

    def test_new_hof_case_allowed_after_dismiss(self) -> None:
        st = _FakeSt()
        st.session_state["_ami_dismissed_insight_ids"] = ["old-id"]
        st.session_state["_ami_dismissed_question_ids"] = ["old-qid"]
        new_insight = {
            "insight_id": "new-id",
            "question_id": "new-qid",
            "conclusion": "New HOF case summary",
            "source_app": "baseball",
        }
        st.session_state["_hof_case_submit_pending_insight"] = new_insight
        restored = ensure_baseball_pending_insight_for_render(st)
        self.assertTrue(restored)
        self.assertEqual(st.session_state.get(SESSION_PENDING_KEY, {}).get("insight_id"), "new-id")


if __name__ == "__main__":
    unittest.main()
