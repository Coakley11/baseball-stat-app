"""E4 (built, NOT active): advanced Draft Assistant intelligence (group draft_assistant) and Draft Room
Simulator insights (group draft_simulator, activated separately — owner 2026-11-23).

Free keeps Roster Fit recommendations, the basic Draft Assistant, the Simulator board and every Live
Draft function. Stored choices are never rewritten; Free runs use the defaults.
"""

from __future__ import annotations

import ast
import re
import unittest

import pandas as pd

import baseball_monetization as bm
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
E, G = bm.ENFORCEMENT_ENV, bm.GROUPS_ENV
DA_CAPS = ("draft_ranking_modes", "draft_category_priorities", "draft_player_insight", "draft_scarcity_insights",
           "draft_ml_blend_controls")
SIM_CAPS = ("draft_simulator_insights",)
OTHERS = ("draft_strategy_library", "draft_lab_simulation", "draft_lab_live_analysis", "draft_pick_simulation",
          "ml_full_list", "ml_tuning", "ml_diagnostics")
AMI_DRAFT = ("draft_recommendations", "draft_recommendation_explanation")


def _app_functions(*names):
    tree = ast.parse(APP)
    src = [ast.get_source_segment(APP, n) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(src) == len(names), names
    return "\n\n".join(src)


def _da_page():
    start = APP.index('elif active_page == "Draft Assistant Simulator":')
    return APP[start:APP.index("\nelif active_page ==", start + 10)]


def _sim_page():
    start = APP.index('elif active_page == "Draft Room Simulator":')
    return APP[start:APP.index("\nelif active_page ==", start + 10)]


class GroupTests(unittest.TestCase):
    def test_off_by_default(self):
        for cap in DA_CAPS + SIM_CAPS:
            self.assertIs(bm.CAPABILITY_FEATURES[cap], bm.FeatureId.ADVANCED_DRAFT_INTELLIGENCE)
            self.assertFalse(bm.capability_enforced(cap, {}), cap)
            self.assertFalse(bm.capability_enforced(cap, {E: "preview", G: "draft_assistant,draft_simulator"}), cap)

    def test_draft_assistant_group_alone(self):
        env = {E: "on", G: "draft_assistant"}
        for cap in DA_CAPS:
            self.assertTrue(bm.capability_enforced(cap, env), cap)
        for cap in SIM_CAPS + OTHERS + AMI_DRAFT:
            self.assertFalse(bm.capability_enforced(cap, env), f"draft_assistant must not lock {cap}")
        self.assertNotIn(bm.FeatureId.ADVANCED_DRAFT_INTELLIGENCE, bm.enforced_features(env), "capabilities, not the feature")

    def test_draft_simulator_group_alone(self):
        env = {E: "on", G: "draft_simulator"}
        self.assertTrue(bm.capability_enforced("draft_simulator_insights", env))
        for cap in DA_CAPS + OTHERS + AMI_DRAFT:
            self.assertFalse(bm.capability_enforced(cap, env), f"draft_simulator must not lock {cap}")

    def test_other_groups_never_lock_e4(self):
        for name in ("strategies", "draft_lab", "simulate_pick", "ml"):
            env = {E: "on", G: name}
            for cap in DA_CAPS + SIM_CAPS:
                self.assertFalse(bm.capability_enforced(cap, env), f"{name} must not lock {cap}")

    def test_ami_in_live_rooms_is_never_locked_by_e4(self):
        env = {E: "on", G: "draft_assistant,draft_simulator"}
        for cap in AMI_DRAFT:
            self.assertFalse(bm.capability_enforced(cap, env), "AMI draft tools wait for the live-room origin tag")


class DraftAssistantWiringTests(unittest.TestCase):
    def setUp(self):
        self.page = _da_page()

    def test_one_authoritative_read_per_run(self):
        self.assertEqual(self.page.count('_da_allowed_now(st.session_state, "draft_ranking_modes", fresh=True)'), 1)
        for flag, cap in (("_da_rank_ok", "draft_ranking_modes"), ("_da_cat_ok", "draft_category_priorities"),
                          ("_da_insight_ok", "draft_player_insight"), ("_da_blend_ok", "draft_ml_blend_controls")):
            self.assertIn(f'{flag} = _da_allowed_now(st.session_state, "{cap}")', self.page)

    def test_ranking_modes_free_ranks_by_roster_fit_and_keeps_the_saved_choice(self):
        self.assertIn('if _da_rank_ok else "Roster Fit"),', self.page, "scoring cache argument")
        self.assertEqual(len(re.findall(r'if not _da_rank_ok:[^\n]*\n\s+_da_sort_choice = "Roster Fit"', self.page)), 2)
        self.assertIn('key="draft_assistant_rec_card_sort",', self.page)
        i = self.page.index('key="draft_assistant_rec_card_sort",')
        self.assertIn("disabled=not _da_rank_ok,", self.page[i:i + 700])
        self.assertNotIn('st.session_state["draft_assistant_rec_card_sort"] = "Roster Fit"\n        if not _da_rank_ok',
                         self.page)

    def test_category_priorities_free_uses_automatic_and_keeps_overrides(self):
        self.assertIn("merge_category_priorities(_auto_priorities, _priority_overrides if _da_cat_ok else {})", self.page)
        self.assertIn("needed_positions = list(dict.fromkeys(auto_needed_positions or []))", self.page)
        self.assertGreaterEqual(self.page.count("disabled=not _da_cat_ok"), 4, "both position widgets, priorities, restore")
        self.assertIn("disabled=not _da_cat_ok,  # never clear a saved override while it is locked", self.page)

    def test_insight_scarcity_and_blend(self):
        self.assertIn("if _da_insight_ok:  # E4 (A)", self.page)
        self.assertIn('capability="draft_scarcity_insights"):  # E4 (C)', self.page)
        self.assertEqual(self.page.count("disabled=not _da_blend_ok,"), 3, "ML-blend editing lock only")

    def test_global_ml_blend_keys_are_never_substituted(self):
        for key in ("draft_use_ml_blend", "draft_ml_blend_weight", "draft_ml_min_games_signal"):
            self.assertNotRegex(self.page, rf'{key}[^\n]*if _da_blend_ok', "the global blend is never substituted")

    def test_no_gate_inside_live_draft_modules(self):
        for name in ("live_draft_room_ui.py", "live_draft_recommendations.py", "live_draft_pick_scoring.py",
                     "draft_ui.py", "draft_actions.py"):
            src = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("allowed_now(", src, name)
            self.assertNotIn("capability_enforced(", src, name)


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        ns = {}
        exec(  # noqa: S102
            "DRAFT_SIMULATOR_PRO_COLUMNS = " + repr(self._columns()) + "\n" + _app_functions("_strip_simulator_pro_columns"),
            ns,
        )
        self.strip = ns["_strip_simulator_pro_columns"]

    @staticmethod
    def _columns():
        tree = ast.parse(APP)
        for n in tree.body:
            if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "DRAFT_SIMULATOR_PRO_COLUMNS":
                return ast.literal_eval(n.value)
        raise AssertionError("DRAFT_SIMULATOR_PRO_COLUMNS missing")

    def test_locked_drops_the_advanced_columns_only(self):
        df = pd.DataFrame(columns=["Player", "MLB Team", "proj_HR", *self._columns()])
        self.assertEqual(list(self.strip(df, False).columns), ["Player", "MLB Team", "proj_HR"])
        self.assertEqual(list(self.strip(df, True).columns), list(df.columns))
        self.assertIsNone(self.strip(None, False))

    def test_wiring(self):
        page = _sim_page()
        self.assertIn('_dr_insights_ok = _dr_allowed_now(st.session_state, "draft_simulator_insights")', page)
        self.assertIn("pick_info = _strip_simulator_pro_columns(pick_info, _dr_insights_ok)", page)
        self.assertEqual(page.count("_strip_simulator_pro_columns("), 3, "pick data + both roster views")
        self.assertIn('label="Post-draft roster grades", capability="draft_simulator_insights"):  # E4 (C)', page)
        i = page.index("pick_info = _strip_simulator_pro_columns")
        self.assertLess(i, page.index("draft_results = edited_draft.merge(pick_info"), "stripped before the merge")


if __name__ == "__main__":
    unittest.main()
