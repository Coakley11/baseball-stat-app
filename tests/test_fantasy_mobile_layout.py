"""Mobile M4 — Fantasy Team phone presentation contract (no product logic)."""

from __future__ import annotations

import re
import unittest
from contextlib import nullcontext
from pathlib import Path

import fantasy_mobile_layout as F

ROOT = Path(__file__).resolve().parents[1]


def _src(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


class _KeyedSt:
    def __init__(self):
        self.keys = []

    def container(self, key=None, **_kw):
        self.keys.append(key)
        return nullcontext()


class _PinSt:
    class column_config:  # noqa: N801 - mirrors streamlit attribute
        @staticmethod
        def Column(**kw):  # noqa: N802 - mirrors streamlit API
            return dict(kw)


class CssContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = F.fantasy_mobile_css()

    def test_every_rule_is_phone_scoped(self) -> None:
        body = re.sub(r"/\*.*?\*/", "", self.css, flags=re.S).strip()
        self.assertTrue(body.startswith(f"@media (max-width: {F.PHONE_MAX_PX}px)"))
        depth, closes_at_zero = 0, 0
        for ch in body:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    closes_at_zero += 1
        self.assertEqual(depth, 0)
        self.assertEqual(closes_at_zero, 1, "nothing may leak outside the phone media query")

    def test_no_has_selectors(self) -> None:
        self.assertNotIn(":has(", self.css)

    def test_card_rules_only_target_keyed_cards(self) -> None:
        for line in self.css.splitlines():
            if "grid" in line and "{" in line:
                self.assertIn(f"st-key-{F.CARD_KEY_PREFIX}", line)

    def test_card_layout_maps_photo_body_action_columns(self) -> None:
        for n in (1, 2, 3):
            self.assertIn(f":nth-child({n})", self.css)
        self.assertIn("grid-template-columns: 48px minmax(0, 1fr)", self.css)

    def test_card_markdown_margin_reset_prevents_overlap(self) -> None:
        """Regression: Streamlit's -1rem markdown margin made card text lines overlap."""
        self.assertRegex(self.css, r'stMarkdownContainer"\] \{ margin-bottom: 0 !important')

    def test_nothing_is_hidden(self) -> None:
        self.assertNotIn("display: none", self.css)
        self.assertNotIn("visibility: hidden", self.css)

    def test_style_tag_wraps_css(self) -> None:
        tag = F.fantasy_mobile_style_tag()
        self.assertTrue(tag.startswith("<style>") and tag.endswith("</style>"))


class HelperTests(unittest.TestCase):
    def test_leading_identity_columns_only_pins_a_leading_run(self) -> None:
        cols = ["Team", "Player", "Primary Position", "HR"]
        self.assertEqual(F.leading_identity_columns(cols, F.STANDINGS_IDENTITY_COLUMNS), ["Team", "Player"])
        # A non-leading identity column is never pinned (pinning would move it left).
        self.assertEqual(F.leading_identity_columns(["MLB Team", "Player"], ("Player",)), [])
        self.assertEqual(F.leading_identity_columns(["Fantasy Team", "Players", "Total HR"], F.STANDINGS_IDENTITY_COLUMNS), ["Fantasy Team"])

    def test_pinned_config_uses_column_pinned(self) -> None:
        cfg = F.pinned_identity_column_config(_PinSt, ["Fantasy slot", "Player", "HR"], F.LINEUP_IDENTITY_COLUMNS)
        self.assertEqual(cfg, {"Fantasy slot": {"pinned": True}, "Player": {"pinned": True}})

    def test_pinned_config_supported_by_installed_streamlit(self) -> None:
        import streamlit as st

        cfg = F.pinned_identity_column_config(st, ["Team", "HR"], ("Team",))
        self.assertIn("Team", cfg)

    def test_card_key_is_prefixed_unique_and_safe(self) -> None:
        a = F.fantasy_card_key("waiver_rec_0", "José Caballero")
        b = F.fantasy_card_key("waiver_rec_1", "José Caballero")
        self.assertTrue(a.startswith(F.CARD_KEY_PREFIX))
        self.assertNotEqual(a, b)
        self.assertRegex(a[len(F.CARD_KEY_PREFIX):], r"^[\w-]+$")

    def test_phone_rows_use_m1_prefixes(self) -> None:
        st = _KeyedSt()
        with F.phone_wrap_row(st, "trade-actions"):
            pass
        with F.phone_inline_row(st, "fl-open-slots"):
            pass
        self.assertEqual(st.keys, ["m-wrap-trade-actions", "m-inline-fl-open-slots"])

    def test_phone_rows_tolerate_minimal_st_doubles(self) -> None:
        with F.phone_wrap_row(object(), "x"):
            pass
        with F.phone_inline_row(object(), "x"):
            pass


class WiringTests(unittest.TestCase):
    def test_style_appended_to_base_markdown_on_its_own_line(self) -> None:
        self.assertIn('_MOBILE_FOUNDATION_STYLE += "\\n" + fantasy_mobile_style_tag()', _src("streamlit_app.py"))

    def test_waiver_cards_are_keyed(self) -> None:
        src = _src("fantasy_waiver_wire_ui.py")
        self.assertEqual(src.count("st.container(border=True, key=_card_key(key_prefix, name))"), 3)
        self.assertEqual(src.count("st.container(border=True):"), 0)

    def test_rows_wrapped_with_m1_helpers(self) -> None:
        self.assertIn('with phone_wrap_row(st, "fantasy-nav"):', _src("draft_archive_ui.py"))
        self.assertIn('with phone_wrap_row(st, "trade-actions"):', _src("fantasy_trade_center_ui.py"))
        lineup = _src("fantasy_weekly_lineup_ui.py")
        self.assertIn('with _phone_inline_row(st, "fl-open-slots"):', lineup)
        self.assertIn('with _phone_inline_row(st, "fl-save-reset"):', lineup)

    def test_action_widget_keys_unchanged(self) -> None:
        trade = _src("fantasy_trade_center_ui.py")
        for key in ("tc_find_ideas", "tc_analyze_trade", "tc_propose_trade", "tc_clear_trade", "tc_reset_builder"):
            self.assertIn(f'key="{key}"', trade)
        lineup = _src("fantasy_weekly_lineup_ui.py")
        self.assertIn('key=f"{prefix}_waiver_{row[\'waiver_label\']}_{idx}_{int(selected_week)}"', lineup)

    def test_pinning_is_opt_in_and_limited_to_fantasy_tables(self) -> None:
        app = _src("streamlit_app.py")
        self.assertIn("    pin_columns=None,\n", app)
        self.assertEqual(app.count('pin_columns=("Fantasy Team", "Team", "Player")'), 3)
        self.assertEqual(_src("fantasy_lineup_management_ui.py").count('pin_columns=("Fantasy slot", "Player")'), 2)
        # Unpinned tables keep the exact pre-M4 call.
        self.assertIn('        st.dataframe(display_df, width="stretch", hide_index=True)\n', app)


if __name__ == "__main__":
    unittest.main()
