"""Tests for canonical Fantasy cluster page state (Sprint 6 acceptance A–E)."""

from __future__ import annotations

import py_compile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

_REPO_ROOT = Path(__file__).resolve().parents[1]

from applied_math_context import apply_source_state_to_session, build_source_state
from baseball_persistent_state import build_baseball_disk_state
from fantasy_state import (
    FANTASY_DIRTY_KEY,
    apply_cloud_fantasy_state_if_allowed,
    apply_fantasy_source_state_from_ami,
    flush_fantasy_section_edits,
    is_fantasy_locally_dirty,
    mark_fantasy_filter_pending_sync,
    mark_fantasy_local_edit,
    prepare_fantasy_sleepers_filters,
    prepare_fantasy_sleepers_page,
    prepare_fantasy_standings_filters,
    restore_fantasy_page_filters,
    write_canonical_fantasy_section,
)

_SLEEPERS = {
    "fantasy_market_window": 4,
    "fantasy_market_format": "Points League",
    "fantasy_market_min_g": 60,
    "fantasy_market_top_n": 20,
    "fantasy_market_selected_player": "Juan Soto",
}

_STANDINGS = {
    "standings_scoring_format": "Points League",
    "standings_stats_source": "MLB API Auto-Fetch",
    "standings_api_season": 2025,
}

_LINEUP = {
    "lineup_format": "Head-to-Head Categories",
    "lineup_bench_rows": 15,
    "lineup_include_util": False,
}


class TestFantasyState(unittest.TestCase):
    def test_a_sleepers_local_persist(self) -> None:
        session: dict = {}
        write_canonical_fantasy_section(session, "sleepers", filters=_SLEEPERS, reason="user_edit", local_edit=True)
        session["fantasy_market_top_n"] = 25
        mark_fantasy_filter_pending_sync(session, "sleepers")
        flush_fantasy_section_edits(session, "sleepers", reason="widget_change")
        prepare_fantasy_sleepers_page(session)
        self.assertEqual(session["fantasy_market_top_n"], 25)
        self.assertEqual(session["fantasy_state"]["sleepers"]["filters"]["fantasy_market_top_n"], 25)
        self.assertTrue(is_fantasy_locally_dirty(session))

    def test_a_prepare_filters_seeds_from_canonical(self) -> None:
        session = {
            "fantasy_state": {"sleepers": {"filters": dict(_SLEEPERS), "selected_player": "Juan Soto"}},
            "page_filter_state": {"Fantasy Sleepers & Busts": {"fantasy_market_top_n": 10}},
        }
        prepare_fantasy_sleepers_filters(session)
        self.assertEqual(session["fantasy_market_top_n"], 20)
        self.assertEqual(session["fantasy_market_selected_player"], "Juan Soto")

    def test_sleepers_position_filter_survives_prepare_when_widget_differs(self) -> None:
        session = {
            "fantasy_state": {
                "sleepers": {
                    "filters": {
                        "fantasy_market_window": 4,
                        "fantasy_market_positions": ["C", "1B", "2B", "3B", "SS", "OF", "DH", "P"],
                        "fantasy_market_age_range": (18, 45),
                    }
                }
            },
            "fantasy_market_positions": ["OF"],
            "fantasy_market_age_range": (25, 35),
        }
        prepare_fantasy_sleepers_page(session)
        prepare_fantasy_sleepers_filters(session)
        self.assertEqual(session["fantasy_market_positions"], ["OF"])
        self.assertEqual(session["fantasy_market_age_range"], (25, 35))

    def test_prepare_sleepers_does_not_sync_full_canonical_over_widget(self) -> None:
        session = {
            "fantasy_state": {
                "sleepers": {
                    "filters": {
                        "fantasy_market_positions": ["C", "1B", "2B", "3B", "SS", "OF", "DH", "P"],
                    }
                }
            },
        }
        prepare_fantasy_sleepers_page(session)
        self.assertNotIn("fantasy_market_positions", session)
        session["fantasy_market_positions"] = ["SS", "OF"]
        prepare_fantasy_sleepers_page(session)
        self.assertEqual(session["fantasy_market_positions"], ["SS", "OF"])

    def test_b_cross_device_cloud_restore(self) -> None:
        session: dict = {"active_page": "Comparison Tool"}
        cloud = {
            "fantasy_state": {
                "sleepers": {"filters": dict(_SLEEPERS), "selected_player": "Juan Soto"},
                "standings": {"filters": dict(_STANDINGS)},
                "lineup": {"filters": dict(_LINEUP)},
            },
            "baseball_workspace_state": {
                "fantasy_sleepers_filters": dict(_SLEEPERS),
                "fantasy_standings_filters": dict(_STANDINGS),
                "fantasy_lineup_filters": dict(_LINEUP),
            },
        }
        self.assertTrue(apply_cloud_fantasy_state_if_allowed(session, cloud))
        self.assertEqual(session["fantasy_market_top_n"], 20)
        self.assertEqual(session["standings_api_season"], 2025)
        self.assertEqual(session["lineup_bench_rows"], 15)
        self.assertFalse(is_fantasy_locally_dirty(session))

    def test_c_local_dirty_blocks_cloud_restore(self) -> None:
        session = {"fantasy_market_top_n": 10, "fantasy_state": {"sleepers": {"filters": {"fantasy_market_top_n": 10}}}}
        mark_fantasy_local_edit(session)
        cloud = {"fantasy_state": {"sleepers": {"filters": _SLEEPERS}}}
        self.assertFalse(apply_cloud_fantasy_state_if_allowed(session, cloud))
        self.assertEqual(session["fantasy_market_top_n"], 10)

    def test_c_local_dirty_blocks_page_filter_restore(self) -> None:
        session = {"standings_api_season": 2024}
        mark_fantasy_local_edit(session)
        store = {"Fantasy Standings Tracker": {"standings_api_season": 2026}}
        self.assertFalse(restore_fantasy_page_filters(session, store, "Fantasy Standings Tracker"))

    def test_d_prepare_preserves_local_widget_drift(self) -> None:
        session = {
            "fantasy_state": {"standings": {"filters": dict(_STANDINGS)}},
            "standings_scoring_format": "5x5 Roto",
        }
        mark_fantasy_local_edit(session)
        from fantasy_state import prepare_fantasy_standings_page

        prepare_fantasy_standings_page(session)
        self.assertEqual(session["standings_scoring_format"], "5x5 Roto")

    def test_e_ami_return_restores_sleepers(self) -> None:
        session: dict = {}
        source = {
            "source_page": "Fantasy Sleepers & Busts",
            "filter_params": dict(_SLEEPERS),
            "entity_params": {"fantasy_market_selected_player": "Juan Soto"},
        }
        apply_fantasy_source_state_from_ami(session, source)
        self.assertEqual(session["fantasy_market_window"], 4)
        self.assertEqual(session["fantasy_market_selected_player"], "Juan Soto")
        self.assertFalse(is_fantasy_locally_dirty(session))

    def test_e_build_and_apply_source_state_roundtrip(self) -> None:
        session = {
            "active_page": "Fantasy Standings Tracker",
            "fantasy_state": {"standings": {"filters": dict(_STANDINGS)}},
            **dict(_STANDINGS),
        }
        built = build_source_state("Fantasy Standings Tracker", session)
        self.assertEqual(built["filter_params"]["standings_api_season"], 2025)
        target: dict = {}
        apply_source_state_to_session(target, built, schedule_navigation=False)
        self.assertEqual(target["standings_api_season"], 2025)

    def test_disk_blob_includes_fantasy_state(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Fantasy Sleepers & Busts",
            "fantasy_state": {"sleepers": {"filters": dict(_SLEEPERS), "selected_player": "Juan Soto"}},
            **dict(_SLEEPERS),
            "page_filter_state": {},
        }
        blob = build_baseball_disk_state(st)
        self.assertEqual(blob["fantasy_state"]["sleepers"]["filters"]["fantasy_market_top_n"], 20)
        meta = blob.get("baseball_workspace_state") or {}
        self.assertEqual(meta.get("fantasy_sleepers_filters", {}).get("fantasy_market_window"), 4)

    def test_fantasy_edit_bypasses_blank_comparison_cloud_block(self) -> None:
        from suite_user_persistence import _cloud_autosave_blocked_reason

        st = MagicMock()
        st.session_state = {"comparison_state": {"players": []}, "compare_players": []}
        state = {"fantasy_state": {"sleepers": {"filters": dict(_SLEEPERS)}}}
        self.assertIsNone(_cloud_autosave_blocked_reason(st, "baseball", state, save_reason="fantasy_edit"))

    def test_standings_prepare_filters(self) -> None:
        session = {
            "fantasy_state": {"standings": {"filters": dict(_STANDINGS)}},
            "page_filter_state": {"Fantasy Standings Tracker": {"standings_api_season": 2020}},
        }
        prepare_fantasy_standings_filters(session)
        self.assertEqual(session["standings_api_season"], 2025)

    def test_streamlit_app_defines_fantasy_handler_before_use(self) -> None:
        streamlit_app = _REPO_ROOT / "streamlit_app.py"
        py_compile.compile(str(streamlit_app), doraise=True)
        py_compile.compile(_REPO_ROOT / "fantasy_state.py", doraise=True)
        text = streamlit_app.read_text(encoding="utf-8")
        def_pos = text.find("def fantasy_filter_changed")
        page_pos = text.find('if active_page == "Fantasy Sleepers & Busts"')
        use_pos = text.find("on_change=fantasy_filter_changed")
        self.assertNotEqual(def_pos, -1)
        self.assertLess(def_pos, page_pos)
        self.assertLess(def_pos, use_pos)


if __name__ == "__main__":
    unittest.main()
