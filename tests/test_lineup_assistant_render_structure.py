"""Regression tests for Fantasy Lineup Assistant top-level section structure."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _lineup_assistant_source_block() -> str:
    source = (REPO_ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    lines = source.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith('if active_page == "Fantasy Lineup Assistant"'))
    end = next(i for i, line in enumerate(lines) if line.startswith('if active_page == "Waiver Wire'))
    return "\n".join(lines[start:end])


class LineupAssistantRenderStructureTests(unittest.TestCase):
    def test_streamlit_app_parses(self) -> None:
        source = (REPO_ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        ast.parse(source)

    def test_lineup_management_module_parses(self) -> None:
        source = (REPO_ROOT / "fantasy_lineup_management_ui.py").read_text(encoding="utf-8")
        ast.parse(source)

    def test_no_unresolved_l1_or_orphan_l2_in_assistant_block(self) -> None:
        block = _lineup_assistant_source_block()
        self.assertNotIn("with l1:", block)
        self.assertNotIn("with tab1:", block)
        self.assertNotIn("with tab2:", block)
        self.assertNotIn("lineup_tabs", block)
        self.assertNotIn("trade_tabs", block)

    def test_exclusive_top_level_branches(self) -> None:
        block = _lineup_assistant_source_block()
        self.assertIn('if _assistant_tab == "Trade Center":', block)
        self.assertIn('elif _assistant_tab == "Lineup Management":', block)
        trade_idx = block.index('if _assistant_tab == "Trade Center":')
        lineup_idx = block.index('elif _assistant_tab == "Lineup Management":')
        self.assertLess(trade_idx, lineup_idx)
        between = block[trade_idx:lineup_idx]
        self.assertIn("render_trade_center_tab(", between)
        self.assertNotIn('if _assistant_tab == "Lineup Management":', between)

    def test_lineup_management_delegates_to_extracted_renderer(self) -> None:
        block = _lineup_assistant_source_block()
        lineup_idx = block.index('elif _assistant_tab == "Lineup Management":')
        after = block[lineup_idx:]
        self.assertIn("render_lineup_management_page(", after)
        self.assertNotIn("if lineup_format == \"Points League\":", block)

    def test_lineup_module_owns_start_sit_columns(self) -> None:
        module = (REPO_ROOT / "fantasy_lineup_management_ui.py").read_text(encoding="utf-8")
        self.assertIn("l2, l3 = st.columns(2)", module)
        self.assertIn("with l2:", module)
        self.assertIn("with l3:", module)
        self.assertIn("render_weekly_lineup_section(", module)

    def test_trade_center_branch_does_not_reference_l2(self) -> None:
        block = _lineup_assistant_source_block()
        trade_idx = block.index('if _assistant_tab == "Trade Center":')
        lineup_idx = block.index('elif _assistant_tab == "Lineup Management":')
        trade_branch = block[trade_idx:lineup_idx]
        self.assertNotIn("with l2:", trade_branch)
        self.assertNotIn("with l3:", trade_branch)
        self.assertNotIn("l2, l3", trade_branch)

    def test_lineup_management_has_no_legacy_trade_analyzer(self) -> None:
        module = (REPO_ROOT / "fantasy_lineup_management_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("Trade Analyzer / Roster Move Assistant", module)
        self.assertNotIn("lineup_trade_give_players", module)
        self.assertNotIn("lineup_trade_get_players", module)
        self.assertNotIn("render_trade_proposals_section(", module)
        self.assertNotIn("Suggest Trades For My Team", module)

    def test_trade_center_internal_nav_helpers_still_imported(self) -> None:
        from fantasy_trade_center_ui import render_trade_center_tab
        from fantasy_trade_ideas import (
            TRADE_CENTER_INTERNAL_TAB_KEY,
            TRADE_CENTER_INTERNAL_WIDGET_KEY,
            apply_trade_center_internal_selection,
            resolve_trade_center_internal_tab,
            sync_trade_center_internal_widget,
        )

        self.assertTrue(callable(render_trade_center_tab))
        session: dict = {}
        self.assertEqual(resolve_trade_center_internal_tab(session), "Build & Analyze")
        sync_trade_center_internal_widget(session)
        self.assertEqual(session[TRADE_CENTER_INTERNAL_WIDGET_KEY], "Build & Analyze")
        apply_trade_center_internal_selection(session, "Offers & Activity")
        self.assertEqual(session[TRADE_CENTER_INTERNAL_TAB_KEY], "Offers & Activity")


if __name__ == "__main__":
    unittest.main()
