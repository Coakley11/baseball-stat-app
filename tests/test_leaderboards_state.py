"""Tests for canonical Leaderboards page state (Sprint 6 acceptance A–E)."""

from __future__ import annotations

import py_compile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

_REPO_ROOT = Path(__file__).resolve().parents[1]

from applied_math_context import apply_source_state_to_session, build_source_state
from baseball_persistent_state import build_baseball_disk_state
from leaderboards_state import (
    LEADERBOARDS_DIRTY_KEY,
    apply_cloud_leaderboards_state_if_allowed,
    apply_leaderboards_source_state_from_ami,
    flush_leaderboards_filter_edits,
    is_leaderboards_locally_dirty,
    mark_leaderboards_filter_pending_sync,
    mark_leaderboards_local_edit,
    prepare_leaderboards_filters,
    prepare_leaderboards_page,
    restore_leaderboards_page_filters,
    write_canonical_leaderboards_state,
)

_SAMPLE = {
    "leaders_year_range_filter": (2018, 2024),
    "leaders_top_n_filter": 30,
    "leaders_sort_stat_filter": "HR",
    "leaders_HR_min": 10,
    "leaders_w_HR": 2.0,
}


class TestLeaderboardsState(unittest.TestCase):
    def test_a_local_persist_prepare_preserves_filters(self) -> None:
        session: dict = {}
        write_canonical_leaderboards_state(session, filters=_SAMPLE, reason="user_edit", local_edit=True)
        session["leaders_top_n_filter"] = 40
        mark_leaderboards_filter_pending_sync(session)
        flush_leaderboards_filter_edits(session, reason="widget_change")
        prepare_leaderboards_page(session)
        self.assertEqual(session["leaders_top_n_filter"], 40)
        self.assertEqual(session["leaderboards_state"]["filters"]["leaders_top_n_filter"], 40)
        self.assertTrue(is_leaderboards_locally_dirty(session))

    def test_a_prepare_filters_seeds_from_canonical(self) -> None:
        session = {
            "leaderboards_state": {"filters": dict(_SAMPLE)},
            "page_filter_state": {"Leaderboards": {"leaders_top_n_filter": 10}},
        }
        prepare_leaderboards_filters(session)
        self.assertEqual(session["leaders_top_n_filter"], 30)

    def test_b_cross_device_cloud_restore(self) -> None:
        session: dict = {"active_page": "Comparison Tool"}
        cloud = {
            "leaderboards_state": {"filters": dict(_SAMPLE)},
            "page_filter_state": {"Leaderboards": {"leaderboards_state": {"filters": dict(_SAMPLE)}}},
            "baseball_workspace_state": {"leaderboards_filters": dict(_SAMPLE)},
        }
        self.assertTrue(apply_cloud_leaderboards_state_if_allowed(session, cloud))
        self.assertEqual(session["leaders_top_n_filter"], 30)
        self.assertFalse(is_leaderboards_locally_dirty(session))

    def test_c_local_dirty_blocks_cloud_restore(self) -> None:
        session = {"leaders_top_n_filter": 10, "leaderboards_state": {"filters": {"leaders_top_n_filter": 10}}}
        mark_leaderboards_local_edit(session)
        cloud = {"leaderboards_state": {"filters": _SAMPLE}}
        self.assertFalse(apply_cloud_leaderboards_state_if_allowed(session, cloud))
        self.assertEqual(session["leaders_top_n_filter"], 10)

    def test_c_local_dirty_blocks_page_filter_restore(self) -> None:
        session = {"leaders_top_n_filter": 10}
        mark_leaderboards_local_edit(session)
        store = {"Leaderboards": {"leaders_top_n_filter": 50}}
        self.assertFalse(restore_leaderboards_page_filters(session, store))

    def test_d_prepare_preserves_local_widget_drift(self) -> None:
        session = {
            "leaderboards_state": {"filters": dict(_SAMPLE)},
            "leaders_sort_stat_filter": "RBI",
        }
        mark_leaderboards_local_edit(session)
        prepare_leaderboards_page(session)
        self.assertEqual(session["leaders_sort_stat_filter"], "RBI")

    def test_e_ami_return_restores_filters(self) -> None:
        session: dict = {}
        source = {"source_page": "Leaderboards", "filter_params": dict(_SAMPLE)}
        apply_leaderboards_source_state_from_ami(session, source)
        self.assertEqual(session["leaders_top_n_filter"], 30)
        self.assertFalse(is_leaderboards_locally_dirty(session))

    def test_e_build_and_apply_source_state_roundtrip(self) -> None:
        session = {"active_page": "Leaderboards", "leaderboards_state": {"filters": dict(_SAMPLE)}, **dict(_SAMPLE)}
        built = build_source_state("Leaderboards", session)
        self.assertEqual(built["filter_params"]["leaders_top_n_filter"], 30)
        target: dict = {}
        apply_source_state_to_session(target, built, schedule_navigation=False)
        self.assertEqual(target["leaders_top_n_filter"], 30)

    def test_disk_blob_includes_leaderboards_state(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Leaderboards",
            "leaderboards_state": {"filters": dict(_SAMPLE)},
            **dict(_SAMPLE),
            "page_filter_state": {},
        }
        blob = build_baseball_disk_state(st)
        self.assertEqual(blob["leaderboards_state"]["filters"]["leaders_top_n_filter"], 30)
        meta = blob.get("baseball_workspace_state") or {}
        self.assertEqual(meta.get("leaderboards_filters", {}).get("leaders_HR_min"), 10)

    def test_leaderboards_edit_bypasses_blank_comparison_cloud_block(self) -> None:
        from suite_user_persistence import _cloud_autosave_blocked_reason

        st = MagicMock()
        st.session_state = {"comparison_state": {"players": []}, "compare_players": []}
        state = {"leaderboards_state": {"filters": dict(_SAMPLE)}}
        self.assertIsNone(_cloud_autosave_blocked_reason(st, "baseball", state, save_reason="leaderboards_edit"))

    def test_streamlit_app_defines_leaderboards_handler_before_use(self) -> None:
        streamlit_app = _REPO_ROOT / "streamlit_app.py"
        py_compile.compile(str(streamlit_app), doraise=True)
        py_compile.compile(_REPO_ROOT / "leaderboards_state.py", doraise=True)
        text = streamlit_app.read_text(encoding="utf-8")
        def_pos = text.find("def leaderboards_filter_changed")
        page_pos = text.find('if active_page == "Leaderboards"')
        use_pos = text.find("on_change=leaderboards_filter_changed")
        self.assertNotEqual(def_pos, -1)
        self.assertLess(def_pos, page_pos)
        self.assertLess(def_pos, use_pos)


if __name__ == "__main__":
    unittest.main()
