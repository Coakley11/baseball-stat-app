"""Tests for Baseball cross-device persistence snapshot."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from baseball_persistent_state import apply_baseball_disk_state, build_baseball_disk_state


class TestBaseballPersistence(unittest.TestCase):
    def test_build_disk_state_snapshots_active_page_filters(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Comparison Tool",
            "page_filter_state": {},
            "sig_player_a_clean": "Juan Soto (NYY)",
            "sig_player_b_clean": "Francisco Lindor (NYM)",
            "compare_players": ["Juan Soto (NYY)", "Francisco Lindor (NYM)"],
            "compare_stat": "OPS",
            "comparison_state": {
                "players": ["Juan Soto (NYY)", "Francisco Lindor (NYM)"],
                "player_a": "Juan Soto (NYY)",
                "player_b": "Francisco Lindor (NYM)",
            },
        }
        blob = build_baseball_disk_state(st)
        self.assertEqual(blob.get("active_page"), "Comparison Tool")
        meta = blob.get("baseball_workspace_state") or {}
        self.assertEqual(meta.get("page"), "Comparison Tool")
        self.assertEqual(meta.get("schema_version"), 1)
        self.assertTrue(meta.get("device_id"))
        top_cs = blob.get("comparison_state") or {}
        self.assertEqual(top_cs.get("players"), ["Juan Soto (NYY)", "Francisco Lindor (NYM)"])
        pf = blob.get("page_filter_state") or {}
        cmp = pf.get("Comparison Tool") or {}
        self.assertEqual(cmp.get("sig_player_a_clean"), "Juan Soto (NYY)")
        self.assertEqual(
            cmp.get("compare_players"),
            ["Juan Soto (NYY)", "Francisco Lindor (NYM)"],
        )

    def test_build_disk_state_includes_career_state(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Career Totals",
            "page_filter_state": {},
            "career_state": {
                "filters": {
                    "career_year_range_filter": (2010, 2024),
                    "career_sort_stat_filter": "HR",
                }
            },
            "career_year_range_filter": (2010, 2024),
            "career_sort_stat_filter": "HR",
        }
        blob = build_baseball_disk_state(st)
        self.assertEqual(blob.get("career_state", {}).get("filters", {}).get("career_sort_stat_filter"), "HR")
        meta = blob.get("baseball_workspace_state") or {}
        self.assertEqual(meta.get("career_filters", {}).get("career_sort_stat_filter"), "HR")

    def test_apply_disk_state_sets_navigation_and_players(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Trend Value",
            "main_sidebar_page": "Trend Value",
            "page_filter_state": {"Trend Value": {"trend_players_multi": ["Aaron Judge"]}},
            "trend_players_multi": ["Aaron Judge"],
            "_page_state_last_active": "Trend Value",
        }
        cloud_state = {
            "active_page": "Comparison Tool",
            "page_filter_state": {
                "Comparison Tool": {
                    "sig_player_a_clean": "Juan Soto (NYY)",
                    "sig_player_b_clean": "Francisco Lindor (NYM)",
                    "compare_players": ["Juan Soto (NYY)", "Francisco Lindor (NYM)"],
                }
            },
        }
        apply_baseball_disk_state(st, cloud_state)
        ss = st.session_state
        self.assertEqual(ss["active_page"], "Comparison Tool")
        self.assertEqual(ss["main_sidebar_page"], "Comparison Tool")
        self.assertEqual(ss["_navigate_to_page"], "Comparison Tool")
        self.assertEqual(ss["sig_player_a_clean"], "Juan Soto (NYY)")
        self.assertEqual(ss["sig_player_b_clean"], "Francisco Lindor (NYM)")
        self.assertTrue(ss.get("_suite_cloud_workspace_applied"))


if __name__ == "__main__":
    unittest.main()
