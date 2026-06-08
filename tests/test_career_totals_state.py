"""Tests for canonical Career Totals page state (Sprint 2 acceptance A–E)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from applied_math_context import apply_source_state_to_session, build_source_state
from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state
from career_totals_state import (
    CAREER_DIRTY_KEY,
    apply_career_source_state_from_ami,
    apply_cloud_career_state_if_allowed,
    commit_career_filters_from_session,
    is_career_locally_dirty,
    mark_career_local_edit,
    prepare_career_totals_filters,
    prepare_career_totals_page,
    restore_career_totals_page_filters,
    write_canonical_career_state,
)

_SAMPLE_FILTERS = {
    "career_year_range_filter": (2015, 2024),
    "career_sort_stat_filter": "OPS",
    "career_batting_hand_filter": ["L"],
    "career_position_filter_mode": "Career Primary Position",
    "career_position_filter": ["OF"],
    "career_team_filter": ["All Teams"],
    "career_by_team_toggle_filter": True,
}


class TestCareerTotalsState(unittest.TestCase):
    def test_a_local_persist_prepare_preserves_filters(self) -> None:
        """A. Local persistence — edit filters, rerun prepare, values remain."""
        session: dict = {}
        write_canonical_career_state(session, filters=_SAMPLE_FILTERS, reason="user_edit", local_edit=True)
        session["career_sort_stat_filter"] = "HR"
        commit_career_filters_from_session(session, reason="widget_change")
        prepare_career_totals_page(session)
        self.assertEqual(session["career_sort_stat_filter"], "HR")
        self.assertEqual(session["career_state"]["filters"]["career_sort_stat_filter"], "HR")
        self.assertTrue(is_career_locally_dirty(session))

    def test_a_prepare_filters_seeds_from_canonical(self) -> None:
        session = {
            "career_state": {"filters": dict(_SAMPLE_FILTERS)},
            "page_filter_state": {
                "Career Totals": {"career_sort_stat_filter": "RBI"},
            },
        }
        prepare_career_totals_filters(session)
        self.assertEqual(session["career_year_range_filter"], (2015, 2024))
        self.assertEqual(session["career_sort_stat_filter"], "OPS")

    def test_b_cross_device_cloud_restore(self) -> None:
        """B. Phone↔Dell — cloud workspace restores career filters."""
        session: dict = {"active_page": "Historical Explorer"}
        cloud = {
            "career_state": {"filters": dict(_SAMPLE_FILTERS)},
            "page_filter_state": {
                "Career Totals": {
                    "career_state": {"filters": dict(_SAMPLE_FILTERS)},
                    "career_sort_stat_filter": "OPS",
                }
            },
            "baseball_workspace_state": {"career_filters": dict(_SAMPLE_FILTERS)},
        }
        self.assertTrue(apply_cloud_career_state_if_allowed(session, cloud))
        self.assertEqual(session["career_sort_stat_filter"], "OPS")
        self.assertEqual(session["career_by_team_toggle_filter"], True)
        self.assertFalse(is_career_locally_dirty(session))

    def test_b_disk_blob_round_trip(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Career Totals",
            "career_state": {"filters": dict(_SAMPLE_FILTERS)},
            **dict(_SAMPLE_FILTERS),
            "page_filter_state": {},
        }
        blob = build_baseball_disk_state(st)
        self.assertIn("career_state", blob)
        meta = blob.get("baseball_workspace_state") or {}
        self.assertEqual(meta.get("career_filters", {}).get("career_sort_stat_filter"), "OPS")

        st2 = MagicMock()
        st2.session_state = {"active_page": "Career Totals", "page_filter_state": {}}
        apply_baseball_disk_state(st2, blob)
        ss = st2.session_state
        self.assertEqual(ss.get("career_sort_stat_filter"), "OPS")
        self.assertEqual(ss.get("career_state", {}).get("filters", {}).get("career_by_team_toggle_filter"), True)

    def test_c_stale_cloud_blocked_when_locally_dirty(self) -> None:
        """C. Stale cloud/disk protection — local edit wins over restore."""
        session = {
            "career_sort_stat_filter": "HR",
            "career_year_range_filter": (2020, 2024),
        }
        mark_career_local_edit(session)
        cloud = {"career_state": {"filters": dict(_SAMPLE_FILTERS)}}
        self.assertFalse(apply_cloud_career_state_if_allowed(session, cloud))
        self.assertEqual(session["career_sort_stat_filter"], "HR")

        store = {"Career Totals": {"career_sort_stat_filter": "RBI", "career_by_team_toggle_filter": False}}
        self.assertFalse(restore_career_totals_page_filters(session, store))
        self.assertEqual(session["career_sort_stat_filter"], "HR")

    def test_d_navigation_active_page_preserved_on_restore(self) -> None:
        """D. Navigation — user-owned page is not overwritten by stale blob page."""
        st = MagicMock()
        st.session_state = {
            "active_page": "Career Totals",
            "main_sidebar_page": "Career Totals",
            "_suite_page_user_nav": True,
            "page_filter_state": {},
        }
        blob = {
            "active_page": "Trend Value",
            "career_state": {"filters": dict(_SAMPLE_FILTERS)},
            "page_filter_state": {"Career Totals": dict(_SAMPLE_FILTERS)},
        }
        apply_baseball_disk_state(st, blob)
        ss = st.session_state
        self.assertEqual(ss["active_page"], "Career Totals")
        self.assertEqual(ss.get("career_sort_stat_filter"), "OPS")

    def test_e_ami_return_restores_career_filters(self) -> None:
        """E. AMI return preserves Career Totals state."""
        session: dict = {}
        source = {
            "source_page": "Career Totals",
            "filter_params": dict(_SAMPLE_FILTERS),
        }
        apply_career_source_state_from_ami(session, source)
        self.assertEqual(session["career_sort_stat_filter"], "OPS")
        self.assertEqual(session["career_by_team_toggle_filter"], True)
        self.assertFalse(session.get(CAREER_DIRTY_KEY))

    def test_e_build_and_apply_source_state_round_trip(self) -> None:
        session = dict(_SAMPLE_FILTERS)
        write_canonical_career_state(session, filters=_SAMPLE_FILTERS, reason="setup")
        built = build_source_state("Career Totals", session)
        self.assertEqual(built["filter_params"]["career_sort_stat_filter"], "OPS")

        target: dict = {"career_sort_stat_filter": "RBI"}
        apply_source_state_to_session(target, built, schedule_navigation=False)
        self.assertEqual(target["career_sort_stat_filter"], "OPS")
        self.assertEqual(target["career_state"]["filters"]["career_sort_stat_filter"], "OPS")

    def test_write_canonical_syncs_page_filter_block(self) -> None:
        session: dict = {}
        write_canonical_career_state(session, filters=_SAMPLE_FILTERS, reason="test")
        block = session["page_filter_state"]["Career Totals"]
        self.assertEqual(block["career_sort_stat_filter"], "OPS")
        self.assertEqual(block["career_state"]["filters"]["career_sort_stat_filter"], "OPS")


if __name__ == "__main__":
    unittest.main()
