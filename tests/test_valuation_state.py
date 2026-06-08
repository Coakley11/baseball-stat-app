"""Tests for canonical Valuation page state (Sprint 5 acceptance A–E)."""

from __future__ import annotations

import py_compile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

_REPO_ROOT = Path(__file__).resolve().parents[1]

from applied_math_context import apply_source_state_to_session, build_source_state
from baseball_persistent_state import build_baseball_disk_state
from valuation_state import (
    VALUATION_DIRTY_KEY,
    apply_cloud_valuation_state_if_allowed,
    apply_valuation_source_state_from_ami,
    flush_valuation_filter_edits,
    is_valuation_locally_dirty,
    mark_valuation_filter_pending_sync,
    mark_valuation_local_edit,
    prepare_valuation_filters,
    prepare_valuation_page,
    restore_valuation_page_filters,
    write_canonical_valuation_state,
)

_SAMPLE = {
    "value_lag": 4,
    "value_min_g": 75,
    "value_position_filter": "OF",
    "value_use_draft_room_sync": True,
    "value_sync_team_for_draft": "Team A",
    "value_w_current": 1.0,
    "value_w_trend": 0.8,
    "value_HR_min": 5,
    "valuation_selected_player": "Aaron Judge",
}


class TestValuationState(unittest.TestCase):
    def test_a_local_persist_prepare_preserves_filters(self) -> None:
        session: dict = {}
        write_canonical_valuation_state(session, filters=_SAMPLE, reason="user_edit", local_edit=True)
        session["value_lag"] = 5
        mark_valuation_filter_pending_sync(session)
        flush_valuation_filter_edits(session, reason="widget_change")
        prepare_valuation_page(session)
        self.assertEqual(session["value_lag"], 5)
        self.assertEqual(session["valuation_state"]["filters"]["value_lag"], 5)
        self.assertTrue(is_valuation_locally_dirty(session))

    def test_a_prepare_filters_seeds_from_canonical(self) -> None:
        session = {
            "valuation_state": {"filters": dict(_SAMPLE), "selected_player": "Aaron Judge"},
            "page_filter_state": {"Valuation": {"value_lag": 3}},
        }
        prepare_valuation_filters(session)
        self.assertEqual(session["value_lag"], 4)
        self.assertEqual(session["valuation_selected_player"], "Aaron Judge")

    def test_b_cross_device_cloud_restore(self) -> None:
        session: dict = {"active_page": "Historical Explorer"}
        cloud = {
            "valuation_state": {"filters": dict(_SAMPLE), "selected_player": "Aaron Judge"},
            "page_filter_state": {"Valuation": {"valuation_state": {"filters": dict(_SAMPLE)}}},
            "baseball_workspace_state": {"valuation_filters": dict(_SAMPLE)},
        }
        self.assertTrue(apply_cloud_valuation_state_if_allowed(session, cloud))
        self.assertEqual(session["value_lag"], 4)
        self.assertEqual(session["valuation_selected_player"], "Aaron Judge")
        self.assertFalse(is_valuation_locally_dirty(session))

    def test_c_local_dirty_blocks_cloud_restore(self) -> None:
        session = {"value_lag": 3, "valuation_state": {"filters": {"value_lag": 3}}}
        mark_valuation_local_edit(session)
        cloud = {"valuation_state": {"filters": _SAMPLE}}
        self.assertFalse(apply_cloud_valuation_state_if_allowed(session, cloud))
        self.assertEqual(session["value_lag"], 3)

    def test_c_local_dirty_blocks_page_filter_restore(self) -> None:
        session = {"value_lag": 3}
        mark_valuation_local_edit(session)
        store = {"Valuation": {"value_lag": 5}}
        self.assertFalse(restore_valuation_page_filters(session, store))

    def test_d_prepare_preserves_local_widget_drift(self) -> None:
        session = {
            "valuation_state": {"filters": dict(_SAMPLE)},
            "value_position_filter": "1B",
        }
        mark_valuation_local_edit(session)
        prepare_valuation_page(session)
        self.assertEqual(session["value_position_filter"], "1B")

    def test_e_ami_return_restores_filters(self) -> None:
        session: dict = {}
        source = {
            "source_page": "Valuation",
            "filter_params": dict(_SAMPLE),
            "entity_params": {"valuation_selected_player": "Aaron Judge"},
        }
        apply_valuation_source_state_from_ami(session, source)
        self.assertEqual(session["value_lag"], 4)
        self.assertEqual(session["valuation_selected_player"], "Aaron Judge")
        self.assertFalse(is_valuation_locally_dirty(session))

    def test_e_build_and_apply_source_state_roundtrip(self) -> None:
        session = {"active_page": "Valuation", "valuation_state": {"filters": dict(_SAMPLE)}, **dict(_SAMPLE)}
        built = build_source_state("Valuation", session)
        self.assertEqual(built["filter_params"]["value_lag"], 4)
        target: dict = {}
        apply_source_state_to_session(target, built, schedule_navigation=False)
        self.assertEqual(target["value_lag"], 4)
        self.assertEqual(target["valuation_selected_player"], "Aaron Judge")

    def test_disk_blob_includes_valuation_state(self) -> None:
        st = MagicMock()
        st.session_state = {
            "active_page": "Valuation",
            "valuation_state": {"filters": dict(_SAMPLE), "selected_player": "Aaron Judge"},
            **dict(_SAMPLE),
            "page_filter_state": {},
        }
        blob = build_baseball_disk_state(st)
        self.assertEqual(blob["valuation_state"]["filters"]["value_lag"], 4)
        meta = blob.get("baseball_workspace_state") or {}
        self.assertEqual(meta.get("valuation_filters", {}).get("value_HR_min"), 5)

    def test_valuation_edit_bypasses_blank_comparison_cloud_block(self) -> None:
        from suite_user_persistence import _cloud_autosave_blocked_reason

        st = MagicMock()
        st.session_state = {"comparison_state": {"players": []}, "compare_players": []}
        state = {"valuation_state": {"filters": dict(_SAMPLE)}}
        self.assertIsNone(_cloud_autosave_blocked_reason(st, "baseball", state, save_reason="valuation_edit"))

    def test_streamlit_app_defines_valuation_handler_before_use(self) -> None:
        streamlit_app = _REPO_ROOT / "streamlit_app.py"
        py_compile.compile(str(streamlit_app), doraise=True)
        py_compile.compile(_REPO_ROOT / "valuation_state.py", doraise=True)
        text = streamlit_app.read_text(encoding="utf-8")
        def_pos = text.find("def valuation_filter_changed")
        page_pos = text.find('if active_page == "Valuation"')
        use_pos = text.find("on_change=valuation_filter_changed")
        self.assertNotEqual(def_pos, -1)
        self.assertLess(def_pos, page_pos)
        self.assertLess(def_pos, use_pos)


if __name__ == "__main__":
    unittest.main()
