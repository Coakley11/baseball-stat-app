"""AMI app-help registry is authoritative: every page covered, every control label real."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from ami_assistant.glossary import TERMS
from ami_assistant.page_help import HOWTOS, MONOLITH, PAGE_HELP, display_label, find_page
from ami_assistant.tools import REGISTRY
from draft_score_display import SCORE_TOOLTIPS
from mobile_nav_m2 import PAGE_GROUPS
from nav_groups import HOME_PAGE, PAGE_SECTION
from page_guides import PAGE_GUIDES
from tests.ami_assistant_fixtures import page_section

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")


def page_options() -> list[str]:
    for node in ast.parse(APP).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "PAGE_OPTIONS":
            return [elt.value for elt in node.value.elts]
    raise AssertionError("PAGE_OPTIONS not found")


def page_source(page_key: str) -> str:
    ph = PAGE_HELP[page_key]
    parts = []
    for src in ph.sources:
        parts.append(page_section(page_key) if src == MONOLITH else (ROOT / src).read_text(encoding="utf-8"))
    return "\n".join(parts)


def label_in(label: str, source: str) -> bool:
    return f'"{label}"' in source or f"f\"{label}\"" in source or f'"{label} ' in source or f'"{label} —' in source


class PageHelpCoverageTests(unittest.TestCase):
    def test_every_app_page_has_help_and_navigation(self) -> None:
        options = page_options()
        self.assertEqual(sorted(PAGE_HELP), sorted(options))
        for key in options:
            ph = PAGE_HELP[key]
            self.assertTrue(ph.purpose, key)
            self.assertEqual(ph.group, PAGE_GROUPS.get(key, ""), key)  # phone sections == U1 nav sections
            self.assertEqual(ph.group, PAGE_SECTION.get(key, ""), key)
            # Navigation names the label the user sees (U1 renames) and its section.
            self.assertIn(f"**{display_label(key)}**", ph.navigation())
            if key != HOME_PAGE:
                self.assertIn(f"**{PAGE_SECTION[key]}**", ph.navigation())

    def test_u1_display_labels_and_old_names(self) -> None:
        self.assertEqual(display_label("Fantasy Standings Tracker"), "League Standings")
        self.assertEqual(display_label("Waiver Wire / Add-Drop Center"), "Waiver Wire")
        self.assertEqual(display_label("Comparison Tool"), "Comparison Tool")
        # Old page names are still understood.
        for old in ("Open Fantasy Standings", "fantasy standings tracker", "live fantasy standings", "League Standings"):
            self.assertEqual(find_page(old).key, "Fantasy Standings Tracker", old)

    def test_u1_headlines_are_the_page_headings(self) -> None:
        for key, ph in PAGE_HELP.items():
            if ph.headline:
                self.assertTrue(label_in(ph.headline, page_source(key)), f"{key}: headline not found on the page")

    def test_home_help_lists_the_real_task_cards(self) -> None:
        from home_page import TASKS

        home = PAGE_HELP[HOME_PAGE]
        for _icon, _title, _body, button, page in TASKS:
            self.assertIn(button, home.controls)
            self.assertIn(page, PAGE_HELP)

    def test_quoted_u1_copy_matches_the_app(self) -> None:
        from ami_assistant.glossary import CONSIDER_ADD_CAPTION

        self.assertIn(CONSIDER_ADD_CAPTION, (ROOT / "fantasy_waiver_wire_ui.py").read_text(encoding="utf-8"))
        doc = (ROOT / "suggested_lineup.py").read_text(encoding="utf-8")
        self.assertIn("never saves, locks or finalizes", doc)
        self.assertIn("presses Save Lineup", doc)
        self.assertIn("does not save, lock or finalize", TERMS["use_suggested_lineup"].definition)

    def test_every_suggested_question_gets_a_real_answer(self) -> None:
        from ami_assistant import router as r
        from ami_assistant.context import build_ami_context
        from ami_assistant.conversation import ConversationState
        from tests.ami_assistant_fixtures import synthetic_dataset

        router = r.Router(synthetic_dataset())
        for key, ph in PAGE_HELP.items():
            for q in ph.questions:
                plan = router.route(q, build_ami_context({}, key), ConversationState())
                self.assertNotEqual(plan.intent, r.CLARIFY, f"{key}: {q!r} -> {plan.clarification}")

    def test_guides_are_the_ones_the_app_renders(self) -> None:
        self.assertIn("from page_guides import PAGE_GUIDES", APP)
        self.assertNotIn("PAGE_GUIDES = {", APP)
        for key, ph in PAGE_HELP.items():
            if ph.headline:
                self.assertEqual(ph.purpose, ph.headline)  # U1 pages lead with their page heading
            elif key in PAGE_GUIDES:
                self.assertEqual(ph.purpose, PAGE_GUIDES[key]["purpose"])
            if key in PAGE_GUIDES:
                self.assertEqual(ph.when, PAGE_GUIDES[key]["when"])

    def test_pricing_purpose_is_the_page_caption(self) -> None:
        src = (ROOT / "baseball_monetization_ui.py").read_text(encoding="utf-8")
        self.assertIn(PAGE_HELP["Pricing & Upgrade"].purpose_fallback, src)

    def test_every_listed_control_exists_on_its_page(self) -> None:
        for key, ph in PAGE_HELP.items():
            source = page_source(key)
            for label in ph.controls:
                self.assertTrue(label_in(label, source), f"{key}: control {label!r} not found in {ph.sources}")

    def test_every_how_to_step_uses_real_controls(self) -> None:
        for h in HOWTOS:
            self.assertIn(h.page, PAGE_HELP)
            source = page_source(h.page)
            for label in h.controls:
                self.assertTrue(label_in(label, source), f"{h.key}: {label!r} not on {h.page}")
            text = " ".join(h.steps)
            for label in h.controls:
                self.assertIn(label, text + " " + h.title, f"{h.key}: control {label!r} listed but not used in steps")


class GlossaryTests(unittest.TestCase):
    def test_draft_scores_are_the_column_tooltips(self) -> None:
        self.assertEqual(TERMS["decision_score"].definition, SCORE_TOOLTIPS["Decision Score"])
        self.assertEqual(TERMS["player_grade"].definition, SCORE_TOOLTIPS["Player Grade"])
        self.assertEqual(TERMS["roster_fit"].definition, SCORE_TOOLTIPS["Roster Fit Score"])

    def test_valuation_terms_come_from_the_page_guide(self) -> None:
        extra = " ".join(PAGE_GUIDES["Valuation"]["extra"])
        for key in ("valuation_score", "current_score", "trend_score"):
            self.assertTrue(TERMS[key].definition)
            self.assertIn(TERMS[key].definition, extra.replace("<strong>", "").replace("</strong>", ""))

    def test_inline_copy_quoted_in_definitions_still_exists(self) -> None:
        self.assertIn("Market Rank − Model Rank (positive = sleeper, negative = bust risk)", APP)
        self.assertIn("“Use qualified” restores it", TERMS["qualified"].definition)
        self.assertIn('f"Use qualified ({qual_state[\'qualified\']:,} AB)"', APP)

    def test_rate_formulas_match_add_rate_stats(self) -> None:
        import pandas as pd

        from lahman_data import add_rate_stats

        row = add_rate_stats(pd.DataFrame([{"AB": 500, "H": 150, "2B": 30, "3B": 5, "HR": 25, "BB": 60, "HBP": 5, "SF": 5}])).iloc[0]
        self.assertAlmostEqual(row["BA"], 150 / 500)
        self.assertAlmostEqual(row["OBP"], (150 + 60 + 5) / (500 + 60 + 5 + 5))
        self.assertAlmostEqual(row["SLG"], ((150 - 30 - 5 - 25) + 2 * 30 + 3 * 5 + 4 * 25) / 500)
        self.assertAlmostEqual(row["OPS"], row["OBP"] + row["SLG"])

    def test_metric_tool_answers_every_term(self) -> None:
        for key in TERMS:
            res = REGISTRY.call("explain_metric", {"term": key})
            self.assertTrue(res.ok and res.data["definition"], key)

    def test_definitions_name_pages_by_their_sidebar_labels(self) -> None:
        from ami_assistant.engine import ask

        answer = ask("What is official standings?", session_state={}, active_page="Home").answer
        self.assertIn("You'll see it on: League Standings", answer)
        self.assertNotIn("Fantasy Standings Tracker", answer)


class AppWiringTests(unittest.TestCase):
    def test_panel_is_rendered_once_before_the_insight_sender_and_guarded(self) -> None:
        call = "render_ami_assistant_panel(st, active_page=active_page, yearly_df=yearly_df)"
        self.assertEqual(APP.count(call), 1)
        self.assertLess(APP.index(call), APP.index("render_baseball_insight_sidebar(\r\n") if "\r\n" in APP
                        else APP.index("render_baseball_insight_sidebar(\n"))
        block = APP[APP.index("from ami_assistant.ui import render_ami_assistant_panel") - 10: APP.index(call) + 200]
        self.assertIn("except ImportError:", block)

    def test_load_data_delegates_to_lahman_data(self) -> None:
        body = APP[APP.index("def load_data(_hof_cache_key: float = 0.0):"):]
        body = body[: body.index("\n\n\n")]
        self.assertIn("return build_lahman_frames(read_required_csv, BASE_DIR)", body)


if __name__ == "__main__":
    unittest.main()
