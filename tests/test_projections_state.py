"""Tests for canonical ML Predictions page state (Sprint 5 acceptance A–E)."""

from __future__ import annotations

import py_compile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

_REPO_ROOT = Path(__file__).resolve().parents[1]

from applied_math_context import apply_source_state_to_session, build_source_state
from baseball_persistent_state import build_baseball_disk_state
from projections_state import (
    PROJECTIONS_DIRTY_KEY,
    apply_cloud_projections_state_if_allowed,
    apply_projections_source_state_from_ami,
    flush_projections_filter_edits,
    is_projections_locally_dirty,
    mark_projections_filter_pending_sync,
    mark_projections_local_edit,
    mark_projections_pipeline_refresh,
    prepare_projections_filters,
    prepare_projections_page,
    restore_projections_page_filters,
    write_canonical_projections_state,
)

_SAMPLE = {
    "ml_lookback": 4,
    "ml_min_games": 80,
    "ml_min_ab": 250,
    "ml_max_players": 150,
    "ml_projection_style": "Aggressive",
    "ml_regression_strength": 0.15,
    "ml_age_strength": 0.55,
    "ml_comp_weight": 0.12,
    "ml_k_neighbors": 15,
    "ml_auto_apply_tuning": False,
    "ml_position_filter": "OF",
    "ml_sort_by": "Predicted HR",
    "ml_projection_insight_player": "Aaron Judge",
    "ml_age_curve_stat": "HR",
    "ml_importance_stat": "HR",
    "ml_predictions_have_run": True,
}


class TestProjectionsState(unittest.TestCase):
    def test_a_local_persist_prepare_preserves_filters(self) -> None:
        session: dict = {}
        write_canonical_projections_state(session, filters=_SAMPLE, reason="user_edit", local_edit=True)
        session["ml_lookback"] = 5
        mark_projections_filter_pending_sync(session)
        flush_projections_filter_edits(session, reason="widget_change")
        prepare_projections_page(session)
        self.assertEqual(session["ml_lookback"], 5)
        self.assertEqual(session["projections_state"]["scope"]["ml_lookback"], 5)
        self.assertTrue(is_projections_locally_dirty(session))

    def test_a_prepare_filters_seeds_from_canonical(self) -> None:
        session = {
            "projections_state": {
                "scope": {"ml_lookback": 4},
                "tuning": {"ml_projection_style": "Aggressive"},
                "display": {"ml_sort_by": "Predicted HR"},
                "pipeline": {"has_run": True},
            },
            "page_filter_state": {"ML Predictions": {"ml_lookback": 3}},
        }
        prepare_projections_filters(session)
        self.assertEqual(session["ml_lookback"], 4)
        self.assertEqual(session["ml_projection_style"], "Aggressive")

    def test_b_cross_device_cloud_restore(self) -> None:
        session: dict = {"active_page": "Valuation"}
        cloud = {
            "projections_state": {
                "scope": {"ml_lookback": 4, "ml_min_games": 80, "ml_min_ab": 250, "ml_max_players": 150},
                "tuning": {
                    "ml_projection_style": "Aggressive",
                    "ml_regression_strength": 0.15,
                    "ml_age_strength": 0.55,
                    "ml_comp_weight": 0.12,
                    "ml_k_neighbors": 15,
                    "ml_auto_apply_tuning": False,
                },
                "display": {
                    "ml_position_filter": "OF",
                    "ml_sort_by": "Predicted HR",
                    "ml_projection_insight_player": "Aaron Judge",
                },
                "pipeline": {"has_run": True},
            },
            "baseball_workspace_state": {"projections_filters": dict(_SAMPLE)},
        }
        self.assertTrue(apply_cloud_projections_state_if_allowed(session, cloud))
        self.assertEqual(session["ml_lookback"], 4)
        self.assertTrue(session["ml_predictions_have_run"])
        self.assertFalse(is_projections_locally_dirty(session))

    def test_c_local_dirty_blocks_cloud_restore(self) -> None:
        session = {"ml_lookback": 3, "projections_state": {"scope": {"ml_lookback": 3}}}
        mark_projections_local_edit(session)
        cloud = {"projections_state": {"scope": {"ml_lookback": 4}}}
        self.assertFalse(apply_cloud_projections_state_if_allowed(session, cloud))
        self.assertEqual(session["ml_lookback"], 3)

    def test_c_local_dirty_blocks_page_filter_restore(self) -> None:
        session = {"ml_lookback": 3}
        mark_projections_local_edit(session)
        store = {"ML Predictions": {"ml_lookback": 5}}
        self.assertFalse(restore_projections_page_filters(session, store))

    def test_d_prepare_preserves_local_widget_drift(self) -> None:
        session = {
            "projections_state": {"scope": {"ml_lookback": 4}, "tuning": {}, "display": {}, "pipeline": {"has_run": False}},
            "ml_sort_by": "Predicted OPS",
        }
        mark_projections_local_edit(session)
        prepare_projections_page(session)
        self.assertEqual(session["ml_sort_by"], "Predicted OPS")

    def test_e_ami_return_restores_filters(self) -> None:
        session: dict = {}
        source = {"source_page": "ML Predictions", "filter_params": dict(_SAMPLE)}
        apply_projections_source_state_from_ami(session, source)
        self.assertEqual(session["ml_lookback"], 4)
        self.assertEqual(session["ml_projection_insight_player"], "Aaron Judge")
        self.assertFalse(is_projections_locally_dirty(session))

    def test_e_build_and_apply_source_state_roundtrip(self) -> None:
        session = {"active_page": "ML Predictions", **dict(_SAMPLE)}
        write_canonical_projections_state(session, filters=_SAMPLE, reason="seed")
        built = build_source_state("ML Predictions", session)
        self.assertEqual(built["filter_params"]["ml_lookback"], 4)
        target: dict = {}
        apply_source_state_to_session(target, built, schedule_navigation=False)
        self.assertEqual(target["ml_lookback"], 4)
        self.assertEqual(target["ml_sort_by"], "Predicted HR")

    def test_disk_blob_includes_projections_state(self) -> None:
        st = MagicMock()
        st.session_state = {"active_page": "ML Predictions", **dict(_SAMPLE), "page_filter_state": {}}
        write_canonical_projections_state(st.session_state, filters=_SAMPLE, reason="seed")
        blob = build_baseball_disk_state(st)
        self.assertEqual(blob["projections_state"]["scope"]["ml_lookback"], 4)
        meta = blob.get("baseball_workspace_state") or {}
        self.assertEqual(meta.get("projections_filters", {}).get("ml_sort_by"), "Predicted HR")

    def test_pipeline_refresh_marks_pending_sync(self) -> None:
        session: dict = {}
        mark_projections_pipeline_refresh(session)
        self.assertTrue(session.get("ml_predictions_have_run"))
        flush_projections_filter_edits(session, reason="pipeline_refresh")
        self.assertTrue(session["projections_state"]["pipeline"]["has_run"])

    def test_projections_edit_bypasses_blank_comparison_cloud_block(self) -> None:
        from suite_user_persistence import _cloud_autosave_blocked_reason

        st = MagicMock()
        st.session_state = {"comparison_state": {"players": []}, "compare_players": []}
        state = {"projections_state": {"scope": {"ml_lookback": 4}}}
        self.assertIsNone(_cloud_autosave_blocked_reason(st, "baseball", state, save_reason="projections_edit"))

    def test_streamlit_app_defines_projections_handler_before_use(self) -> None:
        streamlit_app = _REPO_ROOT / "streamlit_app.py"
        py_compile.compile(str(streamlit_app), doraise=True)
        py_compile.compile(_REPO_ROOT / "projections_state.py", doraise=True)
        text = streamlit_app.read_text(encoding="utf-8")
        def_pos = text.find("def projections_filter_changed")
        page_pos = text.find('if active_page == "ML Predictions"')
        use_pos = text.find("on_change=projections_filter_changed")
        self.assertNotEqual(def_pos, -1)
        self.assertLess(def_pos, page_pos)
        self.assertLess(def_pos, use_pos)


if __name__ == "__main__":
    unittest.main()
