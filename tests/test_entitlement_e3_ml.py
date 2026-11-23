"""E3 (built, NOT active): ML Predictions — top 25 Free, full list / tuning / diagnostics Pro.

Enforced only when BASEBALL_ENTITLEMENT_ENFORCEMENT=on and "ml" is in BASEBALL_ENTITLEMENT_GROUPS.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import baseball_monetization as bm
import baseball_monetization_ui as ui

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
FREE = bm.EntitlementSnapshot(plan=bm.Plan.FREE, ready=True, status=bm.SubscriptionStatus.AUTHENTICATED_FREE)
PRO = bm.EntitlementSnapshot(plan=bm.Plan.PRO, ready=True, status=bm.SubscriptionStatus.ACTIVE)
ON = {bm.ENFORCEMENT_ENV: "on", bm.GROUPS_ENV: "ml"}
ML_CAPS = ("ml_full_list", "ml_tuning", "ml_diagnostics")


def _app_functions(*names):
    """Lift functions out of streamlit_app.py without importing the app (it renders on import)."""
    tree = ast.parse(APP)
    src = [ast.get_source_segment(APP, n) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(src) == len(names), names
    return "\n\n".join(src)


class _St:
    session_state: dict = {}


def _display(session):
    ns = {"st": _St, "ML_FREE_PREDICTIONS": 25, "filter_players_by_fantasy_position": lambda df, f: df, "pd": pd}
    _St.session_state = session
    exec(_app_functions("_ml_full_list_allowed", "_ml_apply_display_view", "_ml_sorted_display_view"), ns)  # noqa: S102
    return ns["_ml_apply_display_view"]


class RegistryTests(unittest.TestCase):
    def test_capabilities_and_group(self):
        for cap in ML_CAPS:
            self.assertIs(bm.CAPABILITY_FEATURES[cap], bm.FeatureId.ML_PREDICTIONS)
            self.assertFalse(bm.capability_enforced(cap, {}), "off by default")
            self.assertTrue(bm.capability_enforced(cap, ON))
        self.assertEqual(bm.ROLLOUT_GROUPS["ml"].capabilities, frozenset(ML_CAPS))
        for other in ("draft_strategy_library", "draft_lab_simulation", "draft_pick_simulation", "advanced_analytics"):
            self.assertFalse(bm.capability_enforced(other, ON), f"enabling ml never locks {other}")
        self.assertIn("top 25", bm.feature_definition(bm.FeatureId.ML_PREDICTIONS).free_keeps)


class DisplayLimitTests(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame({"fullName": [f"P{i}" for i in range(100)], "Predicted OPS": [i / 100 for i in range(100)]})

    def test_switch_off_shows_everything(self):
        view = _display({ui.RUN_SNAPSHOT_KEY: FREE})(self.df, "All positions", "Predicted OPS")
        self.assertEqual(len(view), 100)

    def test_free_sees_the_top_25_after_filters_and_sort_pro_sees_all(self):
        with mock.patch.dict("os.environ", ON):
            view = _display({ui.RUN_SNAPSHOT_KEY: FREE})(self.df, "All positions", "Predicted OPS")
            self.assertEqual(len(view), 25)
            self.assertEqual(view["fullName"].iloc[0], "P99", "cap applies after sorting: the best 25")
            self.assertEqual(view["fullName"].iloc[-1], "P75")
            self.assertEqual(len(_display({ui.RUN_SNAPSHOT_KEY: PRO})(self.df, "All positions", "Predicted OPS")), 100)

    def test_the_engine_output_is_not_modified(self):
        before = self.df.copy()
        with mock.patch.dict("os.environ", ON):
            _display({ui.RUN_SNAPSHOT_KEY: FREE})(self.df, "All positions", "Predicted OPS")
        pd.testing.assert_frame_equal(self.df, before)


class WiringTests(unittest.TestCase):
    def test_every_display_entry_point_goes_through_the_capped_view(self):
        callers = re.findall(r"_ml_apply_display_view\(stored_df, [\w]+, [\w]+\)", APP)
        self.assertGreaterEqual(len(callers), 3, "answer card, nav results, results table")
        self.assertNotIn("_ml_sorted_display_view(", APP.replace("def _ml_sorted_display_view(", "").replace(
            "view = _ml_sorted_display_view(stored_df, position_filter, sort_col)", ""), "no uncapped path")

    def test_one_authoritative_read_per_ml_run(self):
        self.assertEqual(APP.count('_pro_allowed_now(st.session_state, "ml_tuning", fresh=True)'), 1)

    def test_tuning_defaults_apply_only_when_locked_and_saved_values_are_kept(self):
        self.assertIn('ML_DEFAULT_TUNING = {"regression_strength": 0.20, "age_strength": 0.50, '
                      '"comp_weight": 0.10, "k_neighbors": 10}', APP, "the slider defaults")
        for arg, default in (("Regression to Mean", "0.20"), ("Aging Curve Strength", "0.50"),
                             ("Similar Player Weight", "0.10"), ("Similar Players Used", "10")):
            self.assertRegex(APP, rf'st\.slider\("{arg}", [\d.]+, [\d.]+, {re.escape(default)}, ', "defaults agree")
        self.assertIn("if _ml_tuning_ok else dict(ML_DEFAULT_TUNING)", APP)
        self.assertIn("**_ml_run_tuning,", APP)
        # Results tuned while Pro was active are re-blended with the defaults even with auto-apply off.
        i = APP.index("if not _ml_tuning_ok and st.session_state.get(ML_LAST_TUNING_SIG_KEY)")
        self.assertIn('st.session_state["ml_tuning_apply_requested"] = True', APP[i:i + 600])
        for key in ("ml_regression_strength", "ml_age_strength", "ml_comp_weight", "ml_k_neighbors"):
            self.assertIn(f'key="{key}", on_change=projections_filter_changed, disabled=not _ml_tuning_ok)', APP,
                          "disabled, not removed, so the saved value stays")
        self.assertIn("ml_projection_style=ml_projection_style,", APP, "style is a shared Free draft setting")

    def test_the_blend_caption_shows_what_the_run_uses(self):
        i = APP.index("# E3: show the blend this run actually uses")
        block = APP[i:i + 1200]
        self.assertIn('if _ml_tuning_ok else', block)
        self.assertIn('ML_DEFAULT_TUNING["regression_strength"]', block)
        self.assertIn("your saved slider values apply with Pro", block)

    def test_diagnostics_are_guarded(self):
        self.assertIn('capability="ml_diagnostics"):', APP)
        self.assertIn("if _ml_diag_ok:  # E3: age curve and feature importance are Pro diagnostics", APP)

    def test_engine_and_shared_settings_untouched(self):
        engine = _app_functions("_ml_execute_pipeline_if_needed")
        self.assertNotIn("allowed_now", engine)
        self.assertNotIn("_ml_tuning_ok", engine)
        gate_region = APP[APP.index("_ml_tuning_ok = render_pro_note"):APP.index("_ml_diag_ok = _pro_allowed_now")]
        for key in ("ml_projection_style", "draft_use_ml_blend", "draft_projection_style"):
            self.assertNotIn(f'st.session_state["{key}"] =', gate_region)


if __name__ == "__main__":
    unittest.main()
