"""Mobile M3 — Live Draft phone composition contract (presentation only)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import live_draft_mobile_layout as L

ROOT = Path(__file__).resolve().parents[1]
APP_SRC = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")


class CssContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = L.live_draft_mobile_css()

    def test_every_rule_is_phone_scoped(self) -> None:
        body = re.sub(r"/\*.*?\*/", "", self.css, flags=re.S).strip()
        self.assertTrue(body.startswith(f"@media (max-width: {L.PHONE_MAX_PX}px)"))
        # Exactly one top-level block: nothing leaks to desktop.
        depth, closes_at_zero = 0, 0
        for ch in body:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    closes_at_zero += 1
        self.assertEqual(depth, 0)
        self.assertEqual(closes_at_zero, 1)

    def test_no_nested_has(self) -> None:
        """A nested :has() makes the browser drop the whole rule (incl. the flatten list)."""
        for m in re.finditer(r":has\(", self.css):
            depth, i = 1, m.end()
            while depth and i < len(self.css):
                self.assertFalse(
                    self.css.startswith(":has(", i),
                    f"nested :has() near: {self.css[m.start():m.start() + 140]}",
                )
                depth += {"(": 1, ")": -1}.get(self.css[i], 0)
                i += 1

    def test_hierarchy_tiers_are_ordered(self) -> None:
        tiers = [
            L.ORDER_QUICK_NAV,
            L.ORDER_ALERTS,
            L.ORDER_CLOCK,
            L.ORDER_STATUS_PILLS,
            L.ORDER_ACTION,
            L.ORDER_CONTROLS,
            L.ORDER_REC_COLUMN,
            L.ORDER_BOARD_COLUMN,
            L.ORDER_REC_TABLES,
            L.ORDER_CHAT,
        ]
        self.assertEqual(tiers, sorted(tiers))
        self.assertLess(L.ORDER_CLOCK, L.ORDER_ACTION)
        self.assertLess(L.ORDER_ACTION, L.ORDER_REC_COLUMN)  # action above recommendations
        self.assertLess(L.ORDER_REC_COLUMN, L.ORDER_BOARD_COLUMN)  # recs before queue/board
        for tier in tiers:
            self.assertIn(f"order: {tier};", self.css)

    def test_clock_and_action_rules_follow_and_outrank_column_tiers(self) -> None:
        """Regression (caught live): the generic rec-column tier out-specified the action
        rule, leaving Manual Draft at -50. Clock/action now share the tier base selector
        plus a :has() and come later in the sheet."""
        css = self.css
        rec_tier = css.index(f"order: {L.ORDER_REC_COLUMN};")
        tables_tier = css.index(f"order: {L.ORDER_REC_TABLES};")
        self.assertGreater(css.index(f"order: {L.ORDER_ACTION};"), max(rec_tier, tables_tier))
        self.assertGreater(css.index(f"order: {L.ORDER_CLOCK};"), max(rec_tier, tables_tier))
        action_rule = css[: css.index(f"order: {L.ORDER_ACTION};")].rsplit("}", 1)[-1]
        self.assertIn(':has(> [class*="st-key-ldr-m-action"])', action_rule)
        self.assertIn('[data-testid="stColumn"]:has([class*="st-key-ldr-m-action"]) > [data-testid="stVerticalBlock"] > *', action_rule)

    def test_control_chat_block_flattened_by_explicit_paths_only(self) -> None:
        """Generic :has(2-column) would flatten the bordered Control Center card too."""
        for path in L._CTRL_HB_PATHS:
            self.assertIn(path, self.css)
        self.assertNotIn('.st-key-ldr-m-controls [data-testid="stHorizontalBlock"]:has(', self.css)

    def test_clock_hooks_cover_solo_markup_and_shared_iframe(self) -> None:
        self.assertIn(":has(.live-draft-on-clock)", self.css)
        self.assertIn('iframe[srcdoc*="live-draft-on-clock"]', self.css)

    def test_flatten_and_reorder_only_apply_to_live_view_page(self) -> None:
        """Every display:contents / order rule is scoped to the page column that holds a
        draft-action hook — other pages and the Solo minimal-clock view are untouched."""
        page = '[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"]:has([class*="st-key-ldr-m-action"])'
        contents = self.css.split("display: contents")[0].rsplit("@media", 1)[-1]
        for sel in [s.strip() for s in contents.split("{")[-1].split(",") if s.strip()]:
            self.assertTrue(sel.startswith(page), sel[:120])
        for line in self.css.splitlines():
            if "order:" in line and "{" in line:
                self.assertIn(page, line, line[:160])

    def test_no_content_is_hidden_except_named_redundant_hooks(self) -> None:
        hidden = re.findall(r"\.st-key-([a-z-]+), \[data-testid=\"stLayoutWrapper\"\]:has\(> \.st-key-\1\) \{ display: none", self.css)
        self.assertEqual(
            sorted(hidden),
            sorted([L.ACTIVE_TITLE_KEY, L.BRAND_CAPTION_KEY, L.DUP_SUMMARY_KEY, L.DUP_ROOM_HEADER_KEY]),
        )
        self.assertNotIn("visibility: hidden", self.css)
        # Exactly one more display:none rule: the layout-only collapse of zero-height
        # style blocks and the deploy-build marker — nothing user-visible.
        self.assertEqual(self.css.count("display: none"), len(hidden) + 1)
        collapse = [ln for ln in self.css.splitlines() if "style:first-child" in ln or "#solo-deploy-build" in ln]
        self.assertEqual(len(collapse), 2)
        self.assertIn(':not(:has(> [data-testid="stMarkdown"] [data-testid="stMarkdownContainer"] > :not(style)))', collapse[0])

    def test_rec_cards_become_swipe_rows_not_hidden(self) -> None:
        self.assertIn('[class*="st-key-ldr-m-recs"] [data-testid="stHorizontalBlock"]', self.css)
        self.assertIn("scroll-snap-type: x mandatory", self.css)
        self.assertIn("flex-wrap: nowrap", self.css)

    def test_style_tag_wraps_css(self) -> None:
        self.assertEqual(L.live_draft_mobile_style_tag(), f"<style>{L.live_draft_mobile_css()}</style>")

    def test_keyed_returns_container_with_key(self) -> None:
        calls = []

        class _St:
            def container(self, key=None):
                calls.append(key)
                return key

        self.assertEqual(L.keyed(_St(), L.ACTION_KEY), L.ACTION_KEY)
        self.assertEqual(calls, [L.ACTION_KEY])


class AppWiringTests(unittest.TestCase):
    """Hooks wrap existing call sites; render order and widget keys are unchanged."""

    def test_style_appended_to_base_markdown_not_a_new_element(self) -> None:
        self.assertNotIn("st.markdown(live_draft_mobile_style_tag()", APP_SRC)

    def test_appended_style_block_starts_on_its_own_line(self) -> None:
        """Regression (caught live): a <style> started on the same line as the previous
        block's </style> is parsed by CommonMark as markdown text — the CSS showed up as
        visible page text and no stylesheet was created."""
        self.assertIn('_MOBILE_FOUNDATION_STYLE += "\\n" + live_draft_mobile_style_tag()', APP_SRC)
        self.assertTrue(L.live_draft_mobile_style_tag().startswith("<style>"))

    def test_every_hook_constant_is_wired_exactly_once(self) -> None:
        for key in (
            L.ACTION_KEY,
            L.ACTION_EARLY_KEY,
            L.CONTROLS_KEY,
            L.RECS_KEY,
            L.RECS_EARLY_KEY,
            L.ACTIVE_TITLE_KEY,
            L.BRAND_CAPTION_KEY,
            L.DUP_SUMMARY_KEY,
            L.DUP_ROOM_HEADER_KEY,
        ):
            self.assertEqual(APP_SRC.count(f'_ldr_m_hook("{key}")'), 1, key)

    def test_setup_rows_use_m1_wrap_helper_around_existing_columns(self) -> None:
        for row, cols in (
            (L.LEAGUE_SETTINGS_ROW, "lc1, lc2, lc3 = st.columns(3)"),
            (L.ROSTER_SLOTS_ROW, "rs1, rs2, rs3, rs4 = st.columns(4)"),
            (L.TEAM_NAMES_ROW, "team_cols = st.columns(min(int(live_num_teams), 4))"),
        ):
            idx = APP_SRC.index(f'with mobile_wrap_row(st, "{row}"):')
            self.assertIn(cols, APP_SRC[idx: idx + 160], row)

    def test_roster_slot_widget_keys_unchanged(self) -> None:
        for k in ("live_slot_c", "live_slot_1b", "live_slot_2b", "live_slot_3b", "live_slot_ss",
                  "live_slot_of", "live_slot_dh", "live_slot_p", "live_slot_bench"):
            self.assertEqual(APP_SRC.count(f'key="{k}"'), 1, k)

    def test_clock_fragment_call_sites_are_not_wrapped(self) -> None:
        """Fragment identity = hash(function + delta_path). The On-the-Clock banner call
        sites must not be moved into a hook (that would remount the live timer)."""
        for m in re.finditer(r"render_live_on_clock_banner\(\n", APP_SRC):
            before = APP_SRC[max(0, m.start() - 400): m.start()]
            self.assertNotIn("_ldr_m_hook(", before.splitlines()[-1] if before else "")
            window = APP_SRC[max(0, m.start() - 300): m.start()]
            self.assertNotIn('_ldr_m_hook("', window, "clock call wrapped by a hook")

    def test_manual_draft_panels_are_the_action_hooks(self) -> None:
        for key in (L.ACTION_KEY, L.ACTION_EARLY_KEY):
            idx = APP_SRC.index(f'_ldr_m_hook("{key}")')
            self.assertIn("render_live_manual_draft_panel(", APP_SRC[idx: idx + 400], key)

    def test_duplicate_room_header_hook_is_multiplayer_only(self) -> None:
        idx = APP_SRC.index(f'_ldr_m_hook("{L.DUP_ROOM_HEADER_KEY}")')
        self.assertIn("if (_multiplayer_draft and _draft_in_progress)", APP_SRC[idx: idx + 200])


if __name__ == "__main__":
    unittest.main()
