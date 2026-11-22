"""Pro presentation prototype: one registry drives the Upgrade page and the in-app Pro labels.

Nothing here may change access: enforcement stays empty, indicators only describe state.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest import mock

import baseball_monetization as bm
import baseball_monetization_ui as ui

ROOT = Path(__file__).resolve().parents[1]
APP_SOURCES = ["streamlit_app.py", "fantasy_weekly_lineup_ui.py", "fantasy_lineup_management_ui.py",
               "fantasy_trade_center_ui.py", "fantasy_waiver_wire_ui.py", "draft_strategy_ui.py",
               "draft_archive_ui.py", "ami_assistant/ui.py"]


def _app_text() -> str:
    return "\n".join((ROOT / f).read_text(encoding="utf-8") for f in APP_SOURCES)


class RegistryTests(unittest.TestCase):
    def test_every_offered_pro_feature_is_fully_described(self):
        for d in bm.catalog():
            if d.status is bm.FeatureStatus.PLANNED:
                continue
            with self.subTest(feature=d.feature_id.value):
                self.assertIsNot(d.category, bm.Category.LATER)
                self.assertTrue(d.benefit and d.free_keeps and d.surfaces)
                self.assertTrue(d.available_items, "an offered feature must include something that exists")

    def test_unbuilt_features_are_planned(self):
        for fid in (bm.FeatureId.PREMIUM_EXPORTS, bm.FeatureId.EXPANDED_WORKSPACES):
            self.assertIs(bm.feature_definition(fid).status, bm.FeatureStatus.PLANNED)

    def test_nothing_is_enforced_and_every_feature_presents_as_preview(self):
        self.assertEqual(bm.enforced_features(), frozenset())
        for d in bm.catalog():
            self.assertFalse(bm.is_enforced(d.feature_id))
            self.assertEqual(ui.pro_state(bm.default_entitlement(), d.feature_id), "preview")

    def test_capabilities_come_from_the_single_capability_map(self):
        for d in bm.catalog():
            for cap in bm.capabilities_for(d.feature_id):
                self.assertIs(bm.CAPABILITY_FEATURES[cap], d.feature_id)
        self.assertEqual(bm.capabilities_for(bm.FeatureId.DRAFT_STRATEGIES), ("draft_strategy_library",))


class StateTests(unittest.TestCase):
    def test_states_follow_the_trusted_snapshot_and_enforcement(self):
        pro = bm.development_entitlement("pro")
        free = bm.default_entitlement()
        unready = bm.EntitlementSnapshot(ready=False)
        fid = bm.FeatureId.TRADE_INTELLIGENCE
        self.assertEqual(ui.pro_state(pro, fid), "included")
        with mock.patch.object(bm, "ENFORCED_FEATURES", frozenset({fid})):
            self.assertEqual(ui.pro_state(free, fid), "locked")
            self.assertEqual(ui.pro_state(unready, fid), "checking")
            self.assertEqual(ui.pro_state(pro, fid), "included")
            self.assertEqual(ui.pro_state(free, bm.FeatureId.DRAFT_LAB), "preview", "other features unaffected")

    def test_note_text_names_the_control_and_the_preview(self):
        text = ui.pro_note_text(bm.FeatureId.ML_PREDICTIONS, "preview", "Projection tuning")
        self.assertIn("Projection tuning", text)
        self.assertIn(ui.PREVIEW_NOTE, text)
        self.assertIn("included in your plan", ui.pro_note_text(bm.FeatureId.ML_PREDICTIONS, "included"))


class PricingContentTests(unittest.TestCase):
    def test_no_hardcoded_price_anywhere_in_the_presentation(self):
        for name in ("baseball_monetization_ui.py", "baseball_monetization.py"):
            self.assertIsNone(re.search(r"\$\s?\d", (ROOT / name).read_text(encoding="utf-8")), name)

    def test_price_label_comes_only_from_configuration(self):
        self.assertEqual(ui.pro_price_label({}), "")
        self.assertEqual(ui.pro_price_label({ui.PRICE_LABEL_ENV: "  X per month "}), "X per month")
        self.assertEqual(len(ui.pro_price_label({ui.PRICE_LABEL_ENV: "y" * 99})), ui.PRICE_LABEL_MAX)

    def test_planned_work_is_never_presented_as_included(self):
        cards = ui.pricing_cards_html()
        table = ui.comparison_table_html()
        for d in bm.catalog():
            if d.status is bm.FeatureStatus.PLANNED:
                self.assertNotIn(d.name, cards)
                self.assertNotIn(d.name, table)
                self.assertIn(d.name, ui.planned_items())
            for item in d.planned_items:
                self.assertNotIn(item.text, table)
                self.assertIn(f"{item.text} <span class='bxp-chip'>Coming later</span>", cards.replace("&#x27;", "'"))

    def test_every_offered_feature_is_on_the_page(self):
        cards = ui.pricing_cards_html()
        table = ui.comparison_table_html()
        for d in bm.catalog():
            if d.status is not bm.FeatureStatus.PLANNED:
                self.assertIn(d.name, cards)
                self.assertIn(d.name, table)


class IndicatorPlacementTests(unittest.TestCase):
    def test_every_indicator_names_a_registered_feature(self):
        used = re.findall(r'render_pro_note\(\s*st,\s*[\w.]+,\s*"(\w+)"', _app_text())
        self.assertGreaterEqual(len(used), 28)
        for fid in used:
            bm.FeatureId(fid)  # raises on a typo

    def test_each_offered_feature_is_labelled_somewhere_in_the_app(self):
        text = _app_text()
        used = set(re.findall(r'render_pro_note\(\s*st,\s*[\w.]+,\s*"(\w+)"', text))
        used |= set(re.findall(r'pro_note_text\(\s*"(\w+)"', text))
        missing = {d.feature_id.value for d in bm.catalog()
                   if d.status is not bm.FeatureStatus.PLANNED} - used
        self.assertFalse(missing, f"no Pro label for: {sorted(missing)}")

    def test_indicators_do_not_gate_anything_today(self):
        """Presentation only: callers ignore the return value, so nothing can be hidden yet."""
        self.assertNotRegex(_app_text(), r"(if|and|or|not)\s+render_pro_note\(")


class DecisionTests(unittest.TestCase):
    """Owner decisions 2026-11-22 are reflected in the registry."""

    def test_ml_free_keeps_the_top_25(self):
        self.assertIn("top 25", bm.feature_definition(bm.FeatureId.ML_PREDICTIONS).free_keeps)

    def test_live_draft_viewing_stays_free_and_grading_is_draft_lab(self):
        lab = bm.feature_definition(bm.FeatureId.DRAFT_LAB)
        self.assertIn("viewing, saving and exporting your completed drafts", lab.free_keeps)
        self.assertTrue(any("completed Live drafts" in i.text for i in lab.available_items))
        self.assertIs(bm.CAPABILITY_FEATURES["draft_lab_live_analysis"], bm.FeatureId.DRAFT_LAB)

    def test_simulate_draft_pick_is_pro_with_one_capability(self):
        self.assertIs(bm.CAPABILITY_FEATURES["draft_pick_simulation"], bm.FeatureId.ADVANCED_DRAFT_INTELLIGENCE)
        self.assertEqual(_app_text().count('label="Simulate Draft Pick (roster impact)"'), 3)

    def test_ami_coaching_label_follows_the_strategy_capability(self):
        import ami_assistant.tools  # noqa: F401  (registers tools)
        from ami_assistant.ui import _used_strategy_coaching

        self.assertTrue(_used_strategy_coaching({"tools": ["list_my_strategies"]}))
        self.assertFalse(_used_strategy_coaching({"tools": ["get_global_list"]}))
        self.assertFalse(_used_strategy_coaching({}))


class RenderedTests(unittest.TestCase):
    def test_pricing_page_and_locked_component_render(self):
        from streamlit.testing.v1 import AppTest

        def app():
            import streamlit as st
            from unittest import mock as _mock

            import baseball_monetization as _bm
            import baseball_monetization_ui as _ui

            _ui.render_pricing_page(st, st.session_state, _bm.default_entitlement())
            with _mock.patch.object(_bm, "ENFORCED_FEATURES", frozenset({_bm.FeatureId.TRADE_INTELLIGENCE})):
                allowed = _ui.render_pro_note(st, st.session_state, "trade_intelligence", key="t",
                                              snapshot=_bm.default_entitlement())
            st.write(f"ALLOWED={allowed}")

        at = AppTest.from_function(app, default_timeout=30).run()
        self.assertFalse(at.exception)
        self.assertIn(ui.PRICING_TITLE, [t.value for t in at.title])
        md = " ".join(str(m.value) for m in at.markdown)
        self.assertIn(ui.LOCKED_SENTENCE, md)
        self.assertIn(ui.PRICE_FALLBACK, md)
        self.assertIn("ALLOWED=False", md)
        self.assertIn("Current plan: **Free**", " ".join(str(i.value) for i in at.info))


if __name__ == "__main__":
    unittest.main()
