"""Tests for canonical Historical Explorer page state (Sprint 4 acceptance A–E)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from applied_math_context import apply_source_state_to_session, build_source_state
from baseball_persistent_state import build_baseball_disk_state
from historical_state import (
    HISTORICAL_DIRTY_KEY,
    apply_cloud_historical_state_if_allowed,
    apply_historical_source_state_from_ami,
    flush_historical_filter_edits,
    is_historical_locally_dirty,
    mark_historical_filter_pending_sync,
    mark_historical_local_edit,
    prepare_historical_explorer_filters,
    prepare_historical_explorer_page,
    restore_historical_explorer_page_filters,
    write_canonical_historical_state,
)

_SAMPLE_FILTERS = {
    "historical_year_range_filter": (2015, 2024),
    "historical_sort_stat_filter": "HR",
    "historical_sort_order_filter": "Descending",
    "historical_batting_hand_filter": ["L"],
    "historical_position_filter_mode": "Season Primary Position",
    "historical_position_filter": ["OF"],
    "historical_team_filter": ["All Teams"],
    "historical_combine_split_seasons_filter": False,
    "hist_HR_min": 2,
}


class TestHistoricalState(unittest.TestCase):
    def test_a_local_persist_prepare_preserves_filters(self) -> None:
        session: dict = {}
        write_canonical_historical_state(session, filters=_SAMPLE_FILTERS, reason="user_edit", local_edit=True)
        session["historical_sort_stat_filter"] = "OPS"
        mark_historical_filter_pending_sync(session)
        flush_historical_filter_edits(session, reason="widget_change")
        prepare_historical_explorer_page(session)
        self.assertEqual(session["historical_sort_stat_filter"], "OPS")
        self.assertEqual(session["historical_state"]["filters"]["historical_sort_stat_filter"], "OPS")
        self.assertTrue(is_historical_locally_dirty(session))

    def test_a_prepare_filters_seeds_from_canonical(self) -> None:
        session = {
            "historical_state": {"filters": dict(_SAMPLE_FILTERS)},
            "page_filter_state": {
                "Historical Explorer": {"historical_sort_stat_filter": "RBI"},
            },
        }
        prepare_historical_explorer_filters(session)
        self.assertEqual(session["historical_year_range_filter"], (2015, 2024))
        self.assertEqual(session["historical_sort_stat_filter"], "HR")

    def test_b_cross_device_cloud_restore(self) -> None:
        session: dict = {"active_page": "Career Totals"}
        cloud = {
            "historical_state": {"filters": dict(_SAMPLE_FILTERS)},
            "page_filter_state": {
                "Historical Explorer": {
                    "historical_state": {"filters": dict(_SAMPLE_FILTERS)},
                    "historical_sort_stat_filter": "HR",
                }
            },
            "baseball_workspace_state": {"historical_filters": dict(_SAMPLE_FILTERS)},
        }
        self.assertTrue(apply_cloud_historical_state_if_allowed(session, cloud))
        self.assertEqual(session["historical_sort_stat_filter"], "HR")
        self.assertEqual(session["hist_HR_min"], 2)
        self.assertFalse(is_historical_locally_dirty(session))

    def test_c_local_dirty_blocks_cloud_restore(self) -> None:
        session = {
            "historical_year_range_filter": (2000, 2010),
            "historical_state": {"filters": {"historical_year_range_filter": (2000, 2010)}},
        }
        mark_historical_local_edit(session)
        cloud = {"historical_state": {"filters": _SAMPLE_FILTERS}}
        self.assertFalse(apply_cloud_historical_state_if_allowed(session, cloud))
        self.assertEqual(session["historical_year_range_filter"], (2000, 2010))

    def test_c_local_dirty_blocks_page_filter_restore(self) -> None:
        session = {"historical_year_range_filter": (2000, 2010)}
        mark_historical_local_edit(session)
        store = {"Historical Explorer": {"historical_year_range_filter": (2015, 2024)}}
        self.assertFalse(restore_historical_explorer_page_filters(session, store))

    def test_d_prepare_preserves_local_widget_drift(self) -> None:
        session = {
            "historical_state": {"filters": dict(_SAMPLE_FILTERS)},
            "historical_team_filter": ["New York Yankees"],
        }
        mark_historical_local_edit(session)
        prepare_historical_explorer_page(session)
        self.assertEqual(session["historical_team_filter"], ["New York Yankees"])

    def test_e_ami_return_restores_filters_and_snapshot(self) -> None:
        session: dict = {}
        source = {
            "source_page": "Historical Explorer",
            "filter_params": dict(_SAMPLE_FILTERS),
            "chart_params": {
                "historical_snapshot": {
                    "sort_stat": "HR",
                    "year_range": "2015–2024",
                    "row_count": 100,
                    "top_players": ["Mike Trout"],
                }
            },
        }
        apply_historical_source_state_from_ami(session, source)
        self.assertEqual(session["historical_sort_stat_filter"], "HR")
        self.assertEqual(session["hist_HR_min"], 2)
        self.assertFalse(is_historical_locally_dirty(session))
        self.assertEqual(session["_ami_historical_snapshot"]["sort_stat"], "HR")

    def test_e_build_and_apply_source_state_roundtrip(self) -> None:
        session = {
            "active_page": "Historical Explorer",
            "historical_state": {"filters": dict(_SAMPLE_FILTERS)},
            **dict(_SAMPLE_FILTERS),
        }
        built = build_source_state("Historical Explorer", session)
        self.assertEqual(built["filter_params"]["historical_sort_stat_filter"], "HR")
        self.assertEqual(built["filter_params"]["hist_HR_min"], 2)
        target: dict = {}
        apply_source_state_to_session(target, built, schedule_navigation=False)
        self.assertEqual(target["historical_sort_stat_filter"], "HR")
        self.assertEqual(target["hist_HR_min"], 2)

    def test_disk_blob_includes_historical_state(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Historical Explorer",
            "historical_state": {"filters": dict(_SAMPLE_FILTERS)},
            **dict(_SAMPLE_FILTERS),
            "page_filter_state": {},
        }
        blob = build_baseball_disk_state(st)
        self.assertEqual(blob["historical_state"]["filters"]["historical_sort_stat_filter"], "HR")
        meta = blob.get("baseball_workspace_state") or {}
        self.assertEqual(meta.get("historical_filters", {}).get("hist_HR_min"), 2)

    def test_historical_edit_bypasses_blank_comparison_cloud_block(self) -> None:
        from suite_user_persistence import _cloud_autosave_blocked_reason

        st = MagicMock()
        st.session_state = {"comparison_state": {"players": []}, "compare_players": []}
        state = {"historical_state": {"filters": dict(_SAMPLE_FILTERS)}}
        self.assertIsNone(_cloud_autosave_blocked_reason(st, "baseball", state, save_reason="historical_edit"))


if __name__ == "__main__":
    unittest.main()
