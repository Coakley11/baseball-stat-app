"""Insight dismiss persistence and restore guards."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from applied_math_return_insight import (
    SESSION_DISMISSED_KEY,
    SESSION_PENDING_KEY,
    _candidate_insight_allowed,
    _candidate_insight_block_reason,
    _insight_payload_is_dismissed,
    _pending_insight_valid,
    clear_insight_dismiss_markers,
    dismiss_applied_math_insight,
    ensure_baseball_pending_insight_for_render,
    prepare_fresh_submit_insight,
    resolve_pending_insight_for_render,
    stage_hof_submit_pending_insight,
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

    def test_same_question_id_new_insight_id_allowed_after_dismiss(self) -> None:
        st = _FakeSt()
        st.session_state["_ami_dismissed_insight_ids"] = ["old-insight"]
        st.session_state["_ami_dismissed_question_ids"] = ["shared-qid"]
        fresh = {
            "insight_id": "fresh-insight",
            "question_id": "shared-qid",
            "conclusion": "Fresh HOF card",
            "source_app": "baseball",
        }
        self.assertFalse(_insight_payload_is_dismissed(st, fresh))
        self.assertTrue(_candidate_insight_allowed(st, fresh))
        st.session_state["_hof_case_submit_pending_insight"] = fresh
        restored = ensure_baseball_pending_insight_for_render(st)
        self.assertTrue(restored)
        self.assertEqual(st.session_state.get(SESSION_PENDING_KEY, {}).get("insight_id"), "fresh-insight")

    def test_missing_ids_not_treated_as_dismissed(self) -> None:
        st = _FakeSt()
        st.session_state["_ami_dismissed_insight_ids"] = ["some-id"]
        payload = {"conclusion": "No ids on payload", "source_app": "baseball"}
        self.assertFalse(_insight_payload_is_dismissed(st, payload))
        self.assertEqual(_candidate_insight_block_reason(st, payload), "")

    def test_prepare_fresh_submit_clears_question_dismiss_marker(self) -> None:
        st = _FakeSt()
        st.session_state["_ami_dismissed_question_ids"] = ["palmeiro-qid"]
        st.session_state["_hof_case_insight_staged_for_resume"] = "palmeiro-qid"
        prepare_fresh_submit_insight(st, question_id="palmeiro-qid")
        self.assertNotIn("palmeiro-qid", st.session_state.get("_ami_dismissed_question_ids") or [])
        self.assertIsNone(st.session_state.get("_hof_case_insight_staged_for_resume"))

    def test_stage_hof_submit_clears_dismiss_for_fresh_card(self) -> None:
        st = _FakeSt()
        st.session_state["_ami_dismissed_insight_ids"] = ["old-iid"]
        st.session_state["_ami_dismissed_question_ids"] = ["shared-qid"]
        stage_hof_submit_pending_insight(
            st,
            {
                "insight_id": "brand-new-iid",
                "question_id": "shared-qid",
                "conclusion": "New card after re-run",
                "source_app": "baseball",
            },
        )
        self.assertNotIn("brand-new-iid", st.session_state.get("_ami_dismissed_insight_ids") or [])
        self.assertNotIn("shared-qid", st.session_state.get("_ami_dismissed_question_ids") or [])
        self.assertEqual(
            st.session_state.get(SESSION_PENDING_KEY, {}).get("insight_id"),
            "brand-new-iid",
        )

    def test_disk_restore_allows_fresh_submit_snapshot_with_same_question_id(self) -> None:
        st = _FakeSt()
        st.session_state["_ami_dismissed_insight_ids"] = ["old-insight"]
        st.session_state["_ami_dismissed_question_ids"] = ["shared-qid"]
        apply_baseball_disk_state(
            st,
            {
                "_hof_case_submit_pending_insight": {
                    "insight_id": "fresh-insight",
                    "question_id": "shared-qid",
                    "conclusion": "Fresh snapshot",
                },
                "_ami_dismissed_insight_ids": ["old-insight"],
                "_ami_dismissed_question_ids": ["shared-qid"],
            },
        )
        snap = st.session_state.get("_hof_case_submit_pending_insight")
        self.assertIsInstance(snap, dict)
        self.assertEqual(snap.get("insight_id"), "fresh-insight")


if __name__ == "__main__":
    unittest.main()
