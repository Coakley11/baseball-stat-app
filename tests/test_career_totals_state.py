"""Tests for canonical Career Totals page state (Sprint 2 acceptance A–E)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from applied_math_context import apply_source_state_to_session, build_source_state
from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state
from career_totals_state import (
    CAREER_DIRTY_KEY,
    CAREER_FILTER_KEYS,
    CAREER_STAT_MIN_KEYS,
    apply_career_source_state_from_ami,
    apply_cloud_career_state_if_allowed,
    commit_career_filters_from_session,
    flush_career_filter_edits,
    is_career_locally_dirty,
    mark_career_filter_pending_sync,
    mark_career_local_edit,
    normalize_career_year_range,
    prepare_career_multiselect_filter,
    prepare_career_totals_filters,
    prepare_career_totals_page,
    prepare_career_year_range,
    restore_career_totals_page_filters,
    sync_career_filter_change,
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
        mark_career_filter_pending_sync(session)
        flush_career_filter_edits(session, reason="widget_change")
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

    def test_commit_after_render_does_not_mutate_widget_keys(self) -> None:
        """Regression: post-render commit must not assign widget-backed session keys."""
        session = dict(_SAMPLE_FILTERS)
        session["career_sort_stat_filter"] = "HR"
        before = {k: session[k] for k in CAREER_FILTER_KEYS if k in session}
        commit_career_filters_from_session(session, reason="page_rerun")
        after = {k: session[k] for k in CAREER_FILTER_KEYS if k in session}
        self.assertEqual(before, after)
        self.assertEqual(session["career_state"]["filters"]["career_sort_stat_filter"], "HR")

    def test_sync_career_filter_change_marks_pending_then_flush(self) -> None:
        session = dict(_SAMPLE_FILTERS)
        write_canonical_career_state(session, filters=_SAMPLE_FILTERS, reason="setup")
        session["career_sort_stat_filter"] = "RBI"
        sync_career_filter_change(session, reason="filter_change")
        self.assertTrue(session.get("_career_filters_pending_sync"))
        flush_career_filter_edits(session, reason="filter_change")
        self.assertEqual(session["career_sort_stat_filter"], "RBI")
        self.assertEqual(session["career_state"]["filters"]["career_sort_stat_filter"], "RBI")
        self.assertTrue(is_career_locally_dirty(session))

    def test_year_range_change_persists(self) -> None:
        session = dict(_SAMPLE_FILTERS)
        session["career_year_range_filter"] = (2000, 2018)
        mark_career_filter_pending_sync(session)
        flush_career_filter_edits(session, reason="filter_change")
        self.assertEqual(session["career_state"]["filters"]["career_year_range_filter"], (2000, 2018))
        prepare_career_totals_page(session)
        self.assertEqual(session["career_year_range_filter"], (2000, 2018))

    def test_year_range_list_normalizes_to_tuple(self) -> None:
        self.assertEqual(normalize_career_year_range([2005, 2020]), (2005, 2020))
        self.assertEqual(normalize_career_year_range((2005, 2020)), (2005, 2020))

    def test_valid_year_range_not_reset_to_default(self) -> None:
        session = {"career_year_range_filter": (2005, 2020)}
        prepare_career_year_range(session, 1871, 2024, (2010, 2024))
        self.assertEqual(session["career_year_range_filter"], (2005, 2020))

    def test_phone_year_range_beats_stale_cloud(self) -> None:
        session = {**_SAMPLE_FILTERS, "career_year_range_filter": (2005, 2020)}
        mark_career_filter_pending_sync(session)
        flush_career_filter_edits(session, reason="filter_change")
        stale = {
            "career_state": {
                "filters": {**_SAMPLE_FILTERS, "career_year_range_filter": (2010, 2024)},
            }
        }
        self.assertFalse(apply_cloud_career_state_if_allowed(session, stale))
        self.assertEqual(session["career_year_range_filter"], (2005, 2020))

    def test_dell_restores_newer_cloud_year_range(self) -> None:
        session: dict = {"active_page": "Career Totals"}
        cloud = {
            "career_state": {
                "filters": {**_SAMPLE_FILTERS, "career_year_range_filter": (1998, 2016)},
            },
            "baseball_workspace_state": {
                "career_filters": {**_SAMPLE_FILTERS, "career_year_range_filter": (1998, 2016)},
            },
        }
        self.assertTrue(apply_cloud_career_state_if_allowed(session, cloud))
        self.assertEqual(session["career_year_range_filter"], (1998, 2016))

    def test_franchise_league_phone_edit_syncs_canonical(self) -> None:
        session = dict(_SAMPLE_FILTERS)
        session["career_team_filter"] = ["American League"]
        mark_career_filter_pending_sync(session)
        flush_career_filter_edits(session, reason="filter_change")
        self.assertEqual(session["career_state"]["filters"]["career_team_filter"], ["American League"])

    def test_all_teams_valid_and_preserved(self) -> None:
        session = {"career_team_filter": ["All Teams"]}
        options = ["All Teams", "American League", "National League", "New York Yankees"]
        prepare_career_multiselect_filter(session, "career_team_filter", options, ["All Teams"])
        self.assertEqual(session["career_team_filter"], ["All Teams"])
        write_canonical_career_state(
            session,
            filters={"career_team_filter": ["All Teams"]},
            reason="test",
        )
        self.assertEqual(session["career_state"]["filters"]["career_team_filter"], ["All Teams"])

    def test_team_filter_preserved_when_options_rebuilt(self) -> None:
        session = {"career_team_filter": ["New York Yankees"]}
        mark_career_local_edit(session)
        options = ["All Teams", "American League", "National League"]
        merged = prepare_career_multiselect_filter(
            session,
            "career_team_filter",
            options,
            ["All Teams"],
        )
        self.assertIn("New York Yankees", merged)
        self.assertEqual(session["career_team_filter"], ["New York Yankees"])

    def test_position_filter_change_does_not_erase_team_filter(self) -> None:
        session = {
            "career_team_filter": ["American League"],
            "career_position_filter": ["OF"],
        }
        mark_career_local_edit(session)
        flush_career_filter_edits(session, reason="filter_change")
        session["career_position_filter"] = ["SS"]
        mark_career_filter_pending_sync(session)
        flush_career_filter_edits(session, reason="filter_change")
        self.assertEqual(session["career_state"]["filters"]["career_team_filter"], ["American League"])
        self.assertEqual(session["career_state"]["filters"]["career_position_filter"], ["SS"])

    def test_phone_team_filter_beats_stale_cloud(self) -> None:
        session = {**_SAMPLE_FILTERS, "career_team_filter": ["American League"]}
        mark_career_filter_pending_sync(session)
        flush_career_filter_edits(session, reason="filter_change")
        stale = {
            "career_state": {
                "filters": {**_SAMPLE_FILTERS, "career_team_filter": ["All Teams"]},
            }
        }
        self.assertFalse(apply_cloud_career_state_if_allowed(session, stale))
        self.assertEqual(session["career_team_filter"], ["American League"])

    def test_triples_min_zero_to_two_persists(self) -> None:
        session = dict(_SAMPLE_FILTERS)
        session["career_3B_min"] = 0
        write_canonical_career_state(session, filters={**_SAMPLE_FILTERS, "career_3B_min": 0}, reason="setup")
        session["career_3B_min"] = 2
        mark_career_filter_pending_sync(session)
        flush_career_filter_edits(session, reason="filter_change")
        self.assertEqual(session["career_state"]["filters"]["career_3B_min"], 2)
        self.assertTrue(is_career_locally_dirty(session))
        prepare_career_totals_page(session)
        self.assertEqual(session["career_3B_min"], 2)

    def test_zero_stat_min_is_valid_not_missing(self) -> None:
        session = dict(_SAMPLE_FILTERS)
        session["career_HR_min"] = 0
        session["career_3B_min"] = 0
        mark_career_filter_pending_sync(session)
        flush_career_filter_edits(session, reason="filter_change")
        self.assertIn("career_HR_min", session["career_state"]["filters"])
        self.assertIn("career_3B_min", session["career_state"]["filters"])
        self.assertEqual(session["career_state"]["filters"]["career_HR_min"], 0)
        self.assertEqual(session["career_state"]["filters"]["career_3B_min"], 0)

    def test_phone_edit_beats_stale_cloud_default(self) -> None:
        session = {
            **_SAMPLE_FILTERS,
            "career_3B_min": 2,
            "career_year_range_filter": (2005, 2020),
        }
        mark_career_filter_pending_sync(session)
        flush_career_filter_edits(session, reason="filter_change")
        stale_cloud = {
            "career_state": {
                "filters": {**_SAMPLE_FILTERS, "career_3B_min": 0, "career_year_range_filter": (2010, 2024)},
            }
        }
        self.assertFalse(apply_cloud_career_state_if_allowed(session, stale_cloud))
        self.assertEqual(session["career_3B_min"], 2)
        self.assertEqual(session["career_year_range_filter"], (2005, 2020))

    def test_all_stat_min_keys_in_canonical_state(self) -> None:
        session = dict(_SAMPLE_FILTERS)
        for key in CAREER_STAT_MIN_KEYS:
            session[key] = 1 if key == "career_3B_min" else 0
        mark_career_filter_pending_sync(session)
        flush_career_filter_edits(session, reason="filter_change")
        canonical = session["career_state"]["filters"]
        for key in CAREER_STAT_MIN_KEYS:
            self.assertIn(key, canonical)
        self.assertEqual(canonical["career_3B_min"], 1)

    def test_build_source_state_includes_stat_mins(self) -> None:
        session = dict(_SAMPLE_FILTERS)
        session["career_3B_min"] = 2
        write_canonical_career_state(
            session,
            filters={**_SAMPLE_FILTERS, "career_3B_min": 2},
            reason="setup",
        )
        built = build_source_state("Career Totals", session)
        self.assertEqual(built["filter_params"]["career_3B_min"], 2)

    def test_disk_blob_includes_stat_mins(self) -> None:
        st = MagicMock()
        filters = {**_SAMPLE_FILTERS, "career_3B_min": 2}
        st.session_state = {
            "active_page": "Career Totals",
            "career_state": {"filters": filters},
            **filters,
            "page_filter_state": {},
        }
        blob = build_baseball_disk_state(st)
        self.assertEqual(blob["career_state"]["filters"]["career_3B_min"], 2)
        meta = blob.get("baseball_workspace_state") or {}
        self.assertEqual(meta.get("career_filters", {}).get("career_3B_min"), 2)


if __name__ == "__main__":
    unittest.main()
