"""Visual-identity polish: one icon, colour and name per feature, display-only.

Pins that the presentation layer (feature_identity, ui_hierarchy, nav labels, Home, stat chips)
agrees with itself and never changes what a control opens or what number it shows.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import feature_identity as fi

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")


def _app():
    import streamlit_app as app

    return app


def _contrast_on_white(hex_color: str) -> float:
    def channel(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    lum = 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    return 1.05 / (lum + 0.05)


class _FakeSt:
    def __init__(self, session=None):
        self.session_state = dict(session or {})
        self.markdowns: list[str] = []

    def markdown(self, body, unsafe_allow_html=False):
        self.markdowns.append(str(body))


class FeatureRegistryTests(unittest.TestCase):
    def test_every_page_has_one_feature_and_family(self) -> None:
        app = _app()
        self.assertEqual(set(app.PAGE_OPTIONS), set(fi.FEATURES))
        for page, feat in fi.FEATURES.items():
            self.assertIn(feat.family, fi.FAMILIES, page)
            self.assertTrue(feat.icon and feat.name and feat.purpose, page)

    def test_sidebar_labels_use_the_feature_icon_and_name(self) -> None:
        """Sidebar, phone picker, page header and Home all show the same icon and words."""
        app = _app()
        for page in app.PAGE_OPTIONS:
            label = app.page_option_label(page)
            feat = fi.feature(page)
            self.assertEqual(label, f"{feat.icon} {feat.name}", page)

    def test_previous_labels_still_resolve_to_their_page(self) -> None:
        app = _app()
        self.assertEqual(app.normalize_page_key("📈 Compare Players"), "Comparison Tool")
        self.assertEqual(app.normalize_page_key("🧠 Lineup & Trades"), "Fantasy Lineup Assistant")
        self.assertEqual(app.normalize_page_key("📈 Comparison Tool"), "Comparison Tool")

    def test_family_colours_are_readable_on_white(self) -> None:
        for fam in fi.FAMILIES.values():
            self.assertGreaterEqual(_contrast_on_white(fam.color), 4.5, fam.key)

    def test_section_families_cover_every_nav_section(self) -> None:
        from nav_groups import SECTION_ORDER, section_display

        for section in SECTION_ORDER:
            self.assertIn(section, fi.SECTION_FAMILY)
            self.assertTrue(section_display(section).endswith(section))


class PresentationComponentTests(unittest.TestCase):
    def test_page_head_with_feature_shows_family_and_icon_once(self) -> None:
        import ui_hierarchy as ui

        st = _FakeSt()
        ui.page_head(st, "🔎 Historical Explorer", "Best seasons.", feature="Historical Explorer")
        html = st.markdowns[-1]
        self.assertIn('class="u1-page-head u1-fam"', html)
        self.assertIn(">Players<", html)
        self.assertEqual(html.count("🔎"), 1)
        self.assertIn(">Historical Explorer<", html)

    def test_page_head_without_feature_is_unchanged(self) -> None:
        import ui_hierarchy as ui

        st = _FakeSt()
        ui.page_head(st, "What would you like to do?", "Look up players.")
        self.assertIn('<div class="u1-page-head"><p class="u1-title">What would you like to do?</p>', st.markdowns[-1])

    def test_tiles_name_stat_abbreviations_and_keep_values(self) -> None:
        import ui_hierarchy as ui

        st = _FakeSt({"active_page": "Historical Explorer"})
        ui.metric_tiles(st, [("HR", "61", ""), ("AVG", ".269", "qualified"), ("Seasons", "10", "")])
        html = st.markdowns[-1]
        self.assertIn('<abbr title="Home runs">HR</abbr>', html)
        self.assertIn('<div class="u1-hint">Home runs</div>', html)
        self.assertIn('<div class="u1-s">qualified</div>', html)  # the page's own sub-line wins
        self.assertNotIn("Batting average</div>", html)
        for value in ("61", ".269", "10"):
            self.assertIn(f'<div class="u1-v">{value}</div>', html)
        self.assertIn("u1-tiles u1-fam", html)  # the page's family colour

    def test_warning_tone_wins_over_family_colour(self) -> None:
        import ui_hierarchy as ui

        st = _FakeSt({"active_page": "Trend Value"})
        ui.answer_card(st, "No hitters match", tone="warn")
        self.assertIn('class="u1-answer warn"', st.markdowns[-1])


class NavigationUnchangedTests(unittest.TestCase):
    def test_action_buttons_open_the_page_their_icon_names(self) -> None:
        """_u1_act(page, ...) only decorates the label; its callback targets that same page."""
        pairs = re.findall(r'_u1_act\("([^"]+)", "[^"]+"\), _u1_nav_cb\("([^"]+)"\)', APP)
        self.assertGreater(len(pairs), 8)
        for label_page, target in pairs:
            self.assertEqual(label_page, target)
        for _page, action in re.findall(r'_u1_act\("([^"]+)", f"[^"]+"\), _u1_player_action_cb\("([^"]+)"', APP):
            self.assertIn(action, ("Send to Comparison Tool", "Send to Trend Page"))

    def test_trend_buttons_say_what_they_do(self) -> None:
        self.assertNotIn("(f\"{last}'s trend\"", APP)
        self.assertIn("View {last}'s trend", APP)

    def test_home_directory_lists_each_tool_once_with_its_family(self) -> None:
        import home_page

        pages = [p for _fam, _line, group in home_page.TOOL_GROUPS for p in group]
        self.assertEqual(len(pages), len(set(pages)))
        for fam, _line, group in home_page.TOOL_GROUPS:
            for page in group:
                self.assertEqual(fi.feature(page).family, fam, page)
        # Home, Pricing are reachable elsewhere; every working tool is listed.
        self.assertEqual(set(pages) | {"Home", "Pricing & Upgrade"}, set(fi.FEATURES))

    def test_home_task_destinations_unchanged(self) -> None:
        import home_page

        self.assertEqual([t[4] for t in home_page.TASKS],
                         ["Historical Explorer", "Comparison Tool", "Draft Assistant Simulator", "Fantasy Standings Tracker"])


class HomeRenderTests(unittest.TestCase):
    def test_home_renders_without_errors_or_duplicate_keys(self) -> None:
        """Real Streamlit run of Home (two task cards share the Players family)."""
        from streamlit.testing.v1 import AppTest

        def script():
            import streamlit as st

            import home_page

            home_page.render_home(st, st.session_state, navigate=lambda *a, **k: None)

        at = AppTest.from_function(script, default_timeout=120)
        at.run()
        self.assertEqual([str(e.value)[:200] for e in at.exception], [])
        labels = [b.label for b in at.button]
        self.assertIn("🔎 Find a player", labels)
        self.assertIn("⚖️ Compare players", labels)
        self.assertIn("🧪 Analyze Draft Strategy", labels)
        for page in ("Historical Explorer", "Live Draft Room", "Fantasy Lineup Assistant"):
            feat = fi.feature(page)
            self.assertIn(f"{feat.icon} {feat.name}", labels, page)  # the Every tool directory
        keys = [b.key for b in at.button]
        self.assertEqual(len(keys), len(set(keys)))


class StatChipTests(unittest.TestCase):
    def test_chips_keep_every_value_in_order(self) -> None:
        import pandas as pd
        from player_photos import compact_fantasy_stat_line, stat_line_chips_html

        line = compact_fantasy_stat_line(pd.Series({"proj_HR": 48, "proj_RBI": 111, "proj_R": 105, "proj_SB": 9, "proj_BA": 0.289}))
        html = stat_line_chips_html(line)
        self.assertIn("Proj:", html)
        values = re.findall(r"<b>([^<]+)</b> (\w+)", html)
        self.assertEqual(values, [(".289", "AVG"), ("48", "HR"), ("111", "RBI"), ("105", "R"), ("9", "SB")])

    def test_unparseable_line_falls_back_to_text(self) -> None:
        from player_photos import stat_line_chips_html

        self.assertEqual(stat_line_chips_html("Pitcher, no projection"), '<div class="ld-rec-stat-line">Pitcher, no projection</div>')


if __name__ == "__main__":
    unittest.main()
