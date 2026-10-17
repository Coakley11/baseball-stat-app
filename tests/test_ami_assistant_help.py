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


def _home_app() -> None:
    import streamlit as st

    import home_page

    home_page.render_home(st, st.session_state, navigate=lambda page, **_kw: None)


def _rendered_home_buttons(*, with_league: bool = False) -> set[str]:
    """Labels of the buttons Home draws, without or with an active league in the session."""
    from streamlit.testing.v1 import AppTest

    from tests.test_ami_assistant_fantasy import ME, LeagueCase
    from tests.test_team_control_and_local_saves import _as

    case = None
    at = AppTest.from_function(_home_app, default_timeout=60)
    if with_league:
        case = LeagueCase("setUp")
        case.setUp()
        for key, value in case.session.items():
            at.session_state[key] = value
    try:
        with _as(ME):
            at.run()
    finally:
        if case is not None:
            case.tearDown()
    assert not at.exception, at.exception
    return {b.label for b in at.button}


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
        # The accepted U1–U3 labels; page keys are unchanged.
        for key, label in (("Fantasy Standings Tracker", "League Standings"), ("Waiver Wire / Add-Drop Center", "Waiver Wire"),
                           ("Comparison Tool", "Compare Players"), ("Fantasy Sleepers & Busts", "Sleepers & Busts"),
                           ("Fantasy Lineup Assistant", "Lineup & Trades")):
            self.assertEqual(display_label(key), label)
            self.assertEqual(PAGE_HELP[key].label, label)
            self.assertEqual(find_page(f"What is {label}?").key, key, label)  # current label is understood
        # Old page names are still understood.
        for old, key in (("Open Fantasy Standings", "Fantasy Standings Tracker"),
                         ("fantasy standings tracker", "Fantasy Standings Tracker"),
                         ("live fantasy standings", "Fantasy Standings Tracker"),
                         ("Where is the Comparison Tool?", "Comparison Tool"),
                         ("Fantasy Sleepers & Busts", "Fantasy Sleepers & Busts"),
                         ("the Lineup Assistant", "Fantasy Lineup Assistant")):
            self.assertEqual(find_page(old).key, key, old)

    def test_u1_headlines_are_the_page_headings(self) -> None:
        for key, ph in PAGE_HELP.items():
            if ph.headline:
                self.assertTrue(label_in(ph.headline, page_source(key)), f"{key}: headline not found on the page")

    def test_home_help_lists_the_buttons_home_actually_renders(self) -> None:
        # Render Home with and without a league and read the buttons Streamlit draws. A string
        # left in home_page.TASKS that Home no longer shows (U3A's draft card) can't pass this.
        rendered = _rendered_home_buttons() | _rendered_home_buttons(with_league=True)
        self.assertEqual(set(PAGE_HELP[HOME_PAGE].controls), rendered)
        self.assertNotIn("Start a mock draft", rendered)
        from draft_tools import HOME_DRAFT_CHOICES

        self.assertLessEqual({label for label, _page in HOME_DRAFT_CHOICES}, rendered)

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
        import draft_tools

        for key, ph in PAGE_HELP.items():
            if ph.headline:
                self.assertEqual(ph.purpose.lower(), ph.headline.lower())  # redesigned pages lead with their heading
            elif draft_tools.purpose(key):
                # Draft pages show draft_tools.purpose() under their title (U3A).
                self.assertEqual(ph.purpose, draft_tools.purpose(key))
                self.assertIn("draft_tools.purpose(active_page)", page_section(key))
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
        call = "render_ami_assistant_panel(st, active_page=active_page, yearly_df=yearly_df, entitlement=_monetization_snapshot)"
        self.assertEqual(APP.count(call), 1)
        # AMI gets the page gate's own plan snapshot for this run, resolved before the panel renders.
        self.assertLess(APP.index("_monetization_snapshot = current_entitlement("), APP.index(call))
        self.assertLess(APP.index(call), APP.index("render_baseball_insight_sidebar(\r\n") if "\r\n" in APP
                        else APP.index("render_baseball_insight_sidebar(\n"))
        block = APP[APP.index("from ami_assistant.ui import render_ami_assistant_panel") - 10: APP.index(call) + 200]
        self.assertIn("except ImportError:", block)

    def test_load_data_delegates_to_lahman_data(self) -> None:
        body = APP[APP.index("def load_data(_hof_cache_key: float = 0.0):"):]
        body = body[: body.index("\n\n\n")]
        self.assertIn("return build_lahman_frames(read_required_csv, BASE_DIR)", body)

class U2U3HelpTests(unittest.TestCase):
    """Help for the U2/U3 pages restates each page's own rule; every rule is pinned to its source."""

    def test_draft_tools_come_from_draft_tools(self) -> None:
        import draft_tools

        from ami_assistant.page_help import HOWTO_BY_KEY

        res = REGISTRY.call("explain_draft_tools", {})
        self.assertTrue(res.ok)
        self.assertEqual([(t["page_key"], t["purpose"]) for t in res.data["tools"]],
                         [(page, why) for page, _i, _n, why in draft_tools.DRAFT_TOOLS])
        home = {page: label for label, page in draft_tools.HOME_DRAFT_CHOICES}
        self.assertEqual({t["page_key"]: t["home_choice"] for t in res.data["tools"] if t["home_choice"]}, home)
        pair = REGISTRY.call("explain_draft_tools", {"pages": ["Draft Lab / Simulation", "Draft Assistant Simulator"]})
        self.assertEqual([t["page_key"] for t in pair.data["tools"]], ["Draft Assistant Simulator", "Draft Lab / Simulation"])
        # "How do I start a draft?" is Home's draft card, choice by choice, in the tools' own words.
        steps = " ".join(REGISTRY.call("find_feature", {"task": "start_draft"}).data["steps"])
        for label, page in draft_tools.HOME_DRAFT_CHOICES:
            self.assertIn(label, steps)
            self.assertIn(draft_tools.purpose(page), steps)
        self.assertEqual(HOWTO_BY_KEY["start_draft"].controls, tuple(label for label, _p in draft_tools.HOME_DRAFT_CHOICES))

    def test_reading_rules_are_the_pages_own(self) -> None:
        import u2_answers
        from valuation_scores import VALUATION_MIN_AB

        u2 = (ROOT / "u2_answers.py").read_text(encoding="utf-8")
        compare = " ".join(PAGE_HELP["Comparison Tool"].reading)
        self.assertIn("No overall winner", u2)
        self.assertIn("no overall winner", compare.lower())
        for stat in u2_answers.COMPARE_METRICS:
            self.assertIn(stat, compare)
        valuation = " ".join(PAGE_HELP["Valuation"].reading)
        self.assertIn("never called a decline", u2)
        self.assertIn("never a decline", valuation)
        self.assertIn(f"fewer than {VALUATION_MIN_AB} at-bats", valuation)
        ml = " ".join(PAGE_HELP["ML Predictions"].reading)
        self.assertIn("is the model's label from sample size and volatility, not a statistical range.", u2)
        self.assertIn("the model's label from sample size and volatility, not a statistical range", ml)
        self.assertIn("No interval is shown", u2)
        self.assertIn("no prediction interval", ml)
        self.assertIn("These are ranking gaps, not predictions.", u2)
        self.assertIn("ranking gaps, not predictions", " ".join(PAGE_HELP["Fantasy Sleepers & Busts"].reading))
        # Trend Value's playing-time weighting is the glossary term, built from trend_slopes.RATE_SHRINK_PA.
        self.assertIn("trend_value", PAGE_HELP["Trend Value"].terms)
        self.assertIn("weight seasons by plate appearances", TERMS["trend_value"].definition)

    def test_lineup_statuses_are_the_lineup_pages(self) -> None:
        from u3_answers import lineup_answer

        from ami_assistant.page_help import LINEUP_STATUSES

        # Not saved / Draft / Saved and locked, from the Lineup page's own function.
        for (locked, record), status in zip(((False, ""), (False, "draft"), (True, "locked")), LINEUP_STATUSES):
            ans = lineup_answer(team="A", week_text="Week 1", slots=[("C", "C")], assignments={"C": "X"},
                                validation={"ok": True}, bench_count=0, locked=locked, record_status=record)
            self.assertIn(status, str(ans), status)
        definition = TERMS["lineup_status"].definition
        for status in LINEUP_STATUSES:
            self.assertIn(f"**{status}**", definition)
        # Until fantasy_read_api has week_lineup_status, AMI explains statuses but never infers yours.
        self.assertIn("can't see your lineup's current status", definition)

    def test_trade_verdicts_are_the_trade_centers(self) -> None:
        from u3_answers import ROSTER_ISSUE_LABEL, TRADE_VALUE_LABELS, TRADE_VALUE_THRESHOLD, trade_verdict

        from ami_assistant.page_help import TRADE_VERDICTS

        labels = {trade_verdict({"verdict": v, "weighted_gain": 0}, my_team="A")["label"] for v in TRADE_VALUE_LABELS}
        issue = [{"team": "A", "kind": "slot", "slot": "C", "message": "no C"}]
        labels.add(trade_verdict({"verdict": "Neutral", "weighted_gain": 0}, my_team="A", roster_issues=issue)["label"])
        self.assertEqual(labels, set(TRADE_VERDICTS))
        definition = TERMS["trade_verdict"].definition
        for label in TRADE_VERDICTS:
            self.assertIn(f"**{label}**", definition)
        self.assertIn(f"+{TRADE_VALUE_THRESHOLD}", definition)
        self.assertIn(ROSTER_ISSUE_LABEL, definition)

    def test_commissioner_tools_help(self) -> None:
        from ui_hierarchy import COMMISSIONER_PANEL_LABEL

        from ami_assistant.glossary import COMMISSIONER_CAPTION

        term = TERMS["commissioner_tools"]
        self.assertIn(term.name, COMMISSIONER_PANEL_LABEL)
        ui_src = (ROOT / "ui_hierarchy.py").read_text(encoding="utf-8")
        caption = "".join(part for part in ui_src[ui_src.index("Only the commissioner sees these."):].split('"')[0:3:2])
        self.assertEqual(" ".join(caption.split()), COMMISSIONER_CAPTION)
        self.assertIn('f"Commissioner acting for {self.team}"', (ROOT / "fantasy_team_control.py").read_text(encoding="utf-8"))
        for phrase in ("shown only to the league's commissioner", "Commissioner acting for", "doesn't make it yours",
                       "only for a team nobody has claimed", "stay outside it"):
            self.assertIn(phrase, term.definition)

    def test_explore_more_is_page_specific(self) -> None:
        for key, ph in PAGE_HELP.items():
            says = "explore more" in ph.outputs.lower() or bool(ph.explore_more)
            self.assertEqual(bool(ph.explore_more_text), says, key)
        self.assertIn("full table", PAGE_HELP["Valuation"].explore_more_text)
        self.assertIn("Hall of Fame Case Mode", PAGE_HELP["Career Totals"].explore_more_text)
        self.assertEqual(PAGE_HELP["Draft Room Simulator"].explore_more_text, "")

    def test_help_prose_names_pages_by_their_current_labels(self) -> None:
        """AMI's own prose (not the app's Quick Guide copy it quotes) never spells an old page name."""
        from ami_assistant.context import PAGE_REF
        from ami_assistant.page_help import HOWTOS

        stale = {k for k in PAGE_HELP if display_label(k) != k} | {"Lineup Assistant", "Standings Tracker",
                                                                   "Start a mock draft", "Live Fantasy Standings"}
        texts = []
        for key in PAGE_HELP:
            d = REGISTRY.call("explain_app_page", {"page": key}).data
            texts += [d["purpose"], d["explore_more"], d["navigation"], *d["reading"], *d["next_steps"],
                      *(t["definition"] for t in d["terms"]), str(d["tasks"])]
        for h in HOWTOS:
            d = REGISTRY.call("find_feature", {"task": h.key}).data
            texts += [*d["steps"], d["note"], d["navigation"]]
        texts += [REGISTRY.call("explain_metric", {"term": k}).data["definition"] for k in TERMS]
        texts.append(str(REGISTRY.call("explain_draft_tools", {}).data))
        for text in texts:
            self.assertNotIn("[[", text)
            for old in stale:
                self.assertNotIn(old, text, text[:120])
        # Every [[page]] reference in AMI's strings names a real page key.
        for path in (ROOT / "ami_assistant").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    for ref in PAGE_REF.findall(node.value):
                        if not ref.startswith("<"):  # "[[<page key>]]" in docs
                            self.assertTrue(ref in PAGE_HELP, f"{path.name}: [[{ref}]] is not a page key")


if __name__ == "__main__":
    unittest.main()
