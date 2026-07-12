"""Regression tests for Trade Center tab-state architecture (widget vs logical keys)."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from fantasy_trade_ideas import (
    LINEUP_ASSISTANT_TAB_KEY,
    LINEUP_ASSISTANT_TAB_WIDGET_KEY,
    TRADE_CENTER_INTERNAL_TAB_KEY,
    TRADE_CENTER_INTERNAL_TABS,
    TRADE_CENTER_INTERNAL_WIDGET_KEY,
    apply_lineup_assistant_tab_selection,
    apply_trade_center_internal_selection,
    resolve_lineup_assistant_tab,
    resolve_trade_center_internal_tab,
    sync_lineup_assistant_tab_widget,
    sync_trade_center_internal_widget,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _assignments_after_widget_key(source: str, widget_key_constant: str) -> list[tuple[int, str]]:
    """Return session assignments to widget_key that appear after st.radio/selectbox with that key."""
    tree = ast.parse(source)
    widget_key_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == widget_key_constant:
                    widget_key_names.add(widget_key_constant)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value == widget_key_constant:
            pass

    # Find imports/aliases for the constant
    const_values = {widget_key_constant}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == widget_key_constant:
                    const_values.add(alias.asname or alias.name)

    violations: list[tuple[int, str]] = []
    widget_rendered = False
    for node in tree.body:
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Attribute) and func.attr in ("radio", "selectbox"):
                    for kw in child.keywords:
                        if kw.arg == "key":
                            key_val = _ast_str(kw.value, const_values)
                            if key_val in const_values or key_val == widget_key_constant.replace("_KEY", "").lower():
                                widget_rendered = True
            if widget_rendered and isinstance(child, ast.Subscript):
                if isinstance(child.value, ast.Name) and child.value.id in ("session", "st.session_state"):
                    key = _subscript_key(child.slice, const_values)
                    if key in const_values:
                        violations.append((child.lineno, ast.get_source_segment(source, child) or ""))
    return violations


def _ast_str(node: ast.AST, names: set[str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in names:
        return node.id
    return None


def _subscript_key(slice_node: ast.AST, names: set[str]) -> str | None:
    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
        return slice_node.value
    if isinstance(slice_node, ast.Name) and slice_node.id in names:
        return slice_node.id
    return None


class TradeCenterTabStateTests(unittest.TestCase):
    def test_build_analyze_is_default_section(self) -> None:
        session: dict = {}
        self.assertEqual(resolve_trade_center_internal_tab(session), "Build & Analyze")
        self.assertEqual(session[TRADE_CENTER_INTERNAL_TAB_KEY], "Build & Analyze")

    def test_offers_selection_persists_to_logical_key(self) -> None:
        session: dict = {TRADE_CENTER_INTERNAL_WIDGET_KEY: "Offers & Activity"}
        tab = apply_trade_center_internal_selection(session, "Offers & Activity")
        self.assertEqual(tab, "Offers & Activity")
        self.assertEqual(session[TRADE_CENTER_INTERNAL_TAB_KEY], "Offers & Activity")

    def test_pending_count_change_does_not_invalidate_widget_state(self) -> None:
        session: dict = {
            TRADE_CENTER_INTERNAL_WIDGET_KEY: "Offers & Activity",
            TRADE_CENTER_INTERNAL_TAB_KEY: "Offers & Activity",
        }
        for pending in (0, 1, 2):
            sync_trade_center_internal_widget(session, requested_tab=resolve_trade_center_internal_tab(session))
            self.assertEqual(session[TRADE_CENTER_INTERNAL_WIDGET_KEY], "Offers & Activity", f"pending={pending}")
            self.assertIn(session[TRADE_CENTER_INTERNAL_WIDGET_KEY], TRADE_CENTER_INTERNAL_TABS)

    def test_player_action_handoff_opens_build_analyze(self) -> None:
        session: dict = {"_lineup_focus_trade_center": True}
        tab = resolve_lineup_assistant_tab(session)
        self.assertEqual(tab, "Trade Center")
        self.assertEqual(session[TRADE_CENTER_INTERNAL_TAB_KEY], "Build & Analyze")
        self.assertEqual(session[TRADE_CENTER_INTERNAL_WIDGET_KEY], "Build & Analyze")

    def test_incoming_offer_handoff_opens_offers(self) -> None:
        session: dict = {"_lineup_focus_trade_offers": True}
        tab = resolve_lineup_assistant_tab(session)
        self.assertEqual(tab, "Trade Center")
        self.assertEqual(session[TRADE_CENTER_INTERNAL_TAB_KEY], "Offers & Activity")
        self.assertEqual(session[TRADE_CENTER_INTERNAL_WIDGET_KEY], "Offers & Activity")

    def test_analyze_offer_handoff_opens_build_analyze(self) -> None:
        session: dict = {
            TRADE_CENTER_INTERNAL_TAB_KEY: "Offers & Activity",
            TRADE_CENTER_INTERNAL_WIDGET_KEY: "Offers & Activity",
        }
        session[TRADE_CENTER_INTERNAL_TAB_KEY] = "Build & Analyze"
        self.assertEqual(resolve_trade_center_internal_tab(session), "Build & Analyze")

    def test_history_handoff_opens_offers_activity(self) -> None:
        session: dict = {"_lineup_focus_trade_history": True}
        tab = resolve_lineup_assistant_tab(session)
        self.assertEqual(tab, "Trade Center")
        self.assertEqual(session[TRADE_CENTER_INTERNAL_TAB_KEY], "Offers & Activity")
        self.assertEqual(session[TRADE_CENTER_INTERNAL_WIDGET_KEY], "Offers & Activity")

    def test_sync_initializes_invalid_widget_to_logical_tab(self) -> None:
        session: dict = {
            TRADE_CENTER_INTERNAL_TAB_KEY: "Offers & Activity",
            TRADE_CENTER_INTERNAL_WIDGET_KEY: "Offers (2)",
        }
        sync_trade_center_internal_widget(session)
        self.assertEqual(session[TRADE_CENTER_INTERNAL_WIDGET_KEY], "Offers & Activity")

    def test_apply_never_writes_widget_key(self) -> None:
        session: dict = {TRADE_CENTER_INTERNAL_WIDGET_KEY: "Offers & Activity"}
        apply_trade_center_internal_selection(session, "Build & Analyze")
        self.assertEqual(session[TRADE_CENTER_INTERNAL_TAB_KEY], "Build & Analyze")
        self.assertEqual(session[TRADE_CENTER_INTERNAL_WIDGET_KEY], "Offers & Activity")

    def test_top_level_tab_selection_uses_logical_key_only(self) -> None:
        session: dict = {LINEUP_ASSISTANT_TAB_WIDGET_KEY: "Trade Center"}
        apply_lineup_assistant_tab_selection(session, "Trade Center")
        self.assertEqual(session[LINEUP_ASSISTANT_TAB_KEY], "Trade Center")
        self.assertEqual(session[LINEUP_ASSISTANT_TAB_WIDGET_KEY], "Trade Center")

    def test_top_level_sync_initializes_invalid_widget(self) -> None:
        session: dict = {LINEUP_ASSISTANT_TAB_KEY: "Trade Center", LINEUP_ASSISTANT_TAB_WIDGET_KEY: "Offers & Activity"}
        sync_lineup_assistant_tab_widget(session)
        self.assertEqual(session[LINEUP_ASSISTANT_TAB_WIDGET_KEY], "Trade Center")

    def test_trade_center_ui_uses_separate_widget_and_logical_keys(self) -> None:
        source = (REPO_ROOT / "fantasy_trade_center_ui.py").read_text(encoding="utf-8")
        self.assertIn("key=TRADE_CENTER_INTERNAL_WIDGET_KEY", source)
        self.assertNotIn("key=TRADE_CENTER_INTERNAL_TAB_KEY", source)
        self.assertIn("session[TRADE_CENTER_INTERNAL_TAB_KEY]", source)
        self.assertIn("apply_trade_center_internal_selection", source)

    def test_streamlit_app_top_level_nav_uses_widget_key(self) -> None:
        source = (REPO_ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("LINEUP_ASSISTANT_TAB_WIDGET_KEY", source)
        self.assertIn("apply_lineup_assistant_tab_selection", source)
        self.assertNotIn('key="lineup_assistant_tab"', source)

    def test_no_dynamic_offer_labels_in_radio_options(self) -> None:
        source = (REPO_ROOT / "fantasy_trade_center_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("offers_badge", source)
        self.assertNotIn('"Offers (', source)

    def test_render_pattern_avoids_widget_key_mutation_after_radio(self) -> None:
        """apply_trade_center_internal_selection must follow radio, not assign widget key."""
        source = (REPO_ROOT / "fantasy_trade_center_ui.py").read_text(encoding="utf-8")
        radio_idx = source.index("key=TRADE_CENTER_INTERNAL_WIDGET_KEY")
        after_radio = source[radio_idx:]
        self.assertIn("apply_trade_center_internal_selection", after_radio)
        self.assertNotIn(f"session[{TRADE_CENTER_INTERNAL_WIDGET_KEY}] = internal_tab", after_radio)
        self.assertNotIn(f"session[{TRADE_CENTER_INTERNAL_WIDGET_KEY}] = selected", after_radio)


if __name__ == "__main__":
    unittest.main()
