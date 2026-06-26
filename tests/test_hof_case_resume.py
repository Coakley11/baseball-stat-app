"""Hall of Fame Case Mode Command Center resume / deep-link tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from hall_of_fame_data import (
    hof_case_target_player_options,
    hof_case_target_slug,
    resolve_hof_case_target_slug,
    target_player_is_hall_of_famer,
)
from suite_deep_links import build_resume_action_url, resume_metrics_from_item_key
from suite_resume_launch import _apply_baseball


class _ST:
    def __init__(self, query: dict | None = None):
        self.query_params = dict(query or {})
        self.session_state: dict = {}


class HofCaseDeepLinkTests(unittest.TestCase):
    def test_resume_metrics_routes_hof_case_to_career_totals(self) -> None:
        page, metrics = resume_metrics_from_item_key(
            "baseball",
            "bb:hof_case:albert-pujols",
            subtitle="Albert Pujols",
        )
        self.assertEqual(page, "Career Totals")
        self.assertTrue(metrics.get("hof_case_mode"))
        self.assertEqual(metrics.get("target_player"), "Albert Pujols")

    def test_build_resume_action_url_includes_career_totals_and_target(self) -> None:
        url = build_resume_action_url(
            "baseball",
            resume_key="bb:hof_case:albert-pujols",
            page="Career Totals",
            metrics={
                "target_player": "Albert Pujols",
                "hof_case_mode": True,
                "question_id": "q-abc123",
            },
        )
        self.assertIn("suite_page=Career+Totals", url)
        self.assertIn("suite_resume=bb%3Ahof_case%3Aalbert-pujols", url)
        self.assertIn("suite_hof_target=Albert+Pujols", url)
        self.assertIn("suite_hof_case=1", url)
        self.assertIn("suite_ai_question_id=q-abc123", url)

    def test_apply_baseball_schedules_career_totals_for_hof_resume(self) -> None:
        st = _ST(
            {
                "suite_resume": "bb:hof_case:mike-trout",
                "suite_page": "Career Totals",
                "suite_hof_target": "Mike Trout",
                "suite_hof_case": "1",
            }
        )
        _apply_baseball(st, "bb:hof_case:mike-trout", "Career Totals")
        self.assertEqual(st.session_state.get("active_page"), "Career Totals")
        self.assertEqual(st.session_state.get("_navigate_to_page"), "Career Totals")
        self.assertTrue(st.session_state.get("career_hof_case_mode"))
        self.assertEqual(st.session_state.get("career_hof_case_target_player"), "Mike Trout")


class HofCaseTargetSelectionTests(unittest.TestCase):
    def test_target_options_exclude_hof_players(self) -> None:
        df = pd.DataFrame(
            [
                {"fullName": "Babe Ruth", "isHallOfFamer": True},
                {"fullName": "Mike Trout", "isHallOfFamer": False},
            ]
        )
        options = hof_case_target_player_options(df)
        self.assertEqual(options, ["Mike Trout"])
        self.assertTrue(target_player_is_hall_of_famer("Babe Ruth", df))
        self.assertFalse(target_player_is_hall_of_famer("Mike Trout", df))

    def test_slug_roundtrip(self) -> None:
        slug = hof_case_target_slug("Albert Pujols")
        self.assertEqual(slug, "albert-pujols")
        self.assertEqual(
            resolve_hof_case_target_slug(slug, ["Albert Pujols", "Mike Trout"]),
            "Albert Pujols",
        )


class HofCaseResumeHydrationTests(unittest.TestCase):
    def test_apply_hof_case_resume_restores_mode_and_target(self) -> None:
        from hof_case_resume import apply_hof_case_resume, finalize_hof_case_resume_if_ready

        st = _ST(
            {
                "suite_resume": "bb:hof_case:mike-trout",
                "suite_page": "Career Totals",
                "suite_hof_target": "Mike Trout",
            }
        )
        diag = apply_hof_case_resume(st)
        self.assertEqual(diag.get("hof_case_resume_status"), "overlay_queued")
        self.assertTrue(st.session_state.get("career_hof_case_mode"))
        self.assertEqual(st.session_state.get("career_hof_case_target_player"), "Mike Trout")
        self.assertEqual(st.session_state.get("active_page"), "Career Totals")
        self.assertIsInstance(st.session_state.get("_hof_case_pending_overlay"), dict)

    def test_apply_pending_overlay_restores_filters(self) -> None:
        from hof_case_resume import (
            apply_hof_case_resume,
            apply_pending_hof_case_overlay,
            finalize_hof_case_resume_if_ready,
        )

        st = _ST(
            {
                "suite_resume": "bb:hof_case:mike-trout",
                "suite_page": "Career Totals",
                "suite_hof_target": "Mike Trout",
            }
        )
        st.session_state["live_draft_room"] = {"status": "in_progress", "draft_room_id": "r1", "draft_board": [1, 2]}
        apply_hof_case_resume(st)
        st.session_state["career_HR_min"] = 0
        overlay_diag = apply_pending_hof_case_overlay(st)
        self.assertTrue(overlay_diag.get("overlay_applied"))
        self.assertEqual(st.session_state.get("live_draft_room", {}).get("draft_room_id"), "r1")
        finalize_hof_case_resume_if_ready(st)
        self.assertTrue(st.session_state.get("_hof_case_resume_completed"))


class HofCaseResumeHydrationTestsContinued(unittest.TestCase):
    def test_finalize_waits_for_overlay(self) -> None:
        from hof_case_resume import apply_hof_case_resume, finalize_hof_case_resume_if_ready

        st = _ST(
            {
                "suite_resume": "bb:hof_case:mike-trout",
                "suite_page": "Career Totals",
                "suite_hof_target": "Mike Trout",
            }
        )
        apply_hof_case_resume(st)
        st.session_state["active_page"] = "Career Totals"
        self.assertFalse(finalize_hof_case_resume_if_ready(st))
        self.assertFalse(st.session_state.get("_hof_case_resume_completed"))


    def test_apply_career_source_state_restores_hof_case(self) -> None:
        from career_totals_state import apply_career_source_state_from_ami
        from hall_of_fame_data import (
            CAREER_HOF_CASE_MODE_KEY,
            CAREER_HOF_CASE_TARGET_KEY,
            HOF_CASE_PACKET_KEY,
        )

        session: dict = {}
        packet = {"mode": "hall_of_fame_case", "target_player": "Mike Trout"}
        source_state = {
            "source_page": "Career Totals",
            "filter_params": {"career_sort_stat_filter": "HR"},
            "entity_params": {
                "hof_case_mode": True,
                "hof_case_target": "Mike Trout",
                "hof_case_packet": packet,
            },
        }
        apply_career_source_state_from_ami(session, source_state)
        self.assertTrue(session.get(CAREER_HOF_CASE_MODE_KEY))
        self.assertEqual(session.get(CAREER_HOF_CASE_TARGET_KEY), "Mike Trout")
        self.assertEqual(session.get(HOF_CASE_PACKET_KEY), packet)
        self.assertEqual(session.get("career_sort_stat_filter"), "HR")

    def test_enforce_hof_case_page_after_workspace(self) -> None:
        from hof_case_resume import apply_hof_case_resume, enforce_hof_case_page_after_workspace

        st = _ST(
            {
                "suite_resume": "bb:hof_case:mike-trout",
                "suite_page": "Career Totals",
                "suite_hof_target": "Mike Trout",
            }
        )
        apply_hof_case_resume(st)
        st.session_state["active_page"] = "Historical Explorer"
        st.session_state["main_sidebar_page"] = "Historical Explorer"
        self.assertTrue(enforce_hof_case_page_after_workspace(st))
        self.assertEqual(st.session_state.get("active_page"), "Career Totals")


if __name__ == "__main__":
    unittest.main()
