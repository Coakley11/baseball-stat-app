"""U3B–U3D: the Lineup page leads with whether this week's lineup is complete and saved,
commissioner controls sit in one marked panel, and an analyzed trade leads with a
You give ⇄ You receive verdict card built only from the trade engine's own output."""

import re
import unittest
from contextlib import nullcontext
from pathlib import Path

from u3_answers import ROSTER_ISSUE_LABEL, lineup_answer, trade_verdict

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
WEEKLY = (ROOT / "fantasy_weekly_lineup_ui.py").read_text(encoding="utf-8")
TRADE = (ROOT / "fantasy_trade_center_ui.py").read_text(encoding="utf-8")

SLOTS = [("C_1", "Catcher"), ("SS_1", "Shortstop"), ("OF_1", "OF 1"), ("OF_2", "OF 2")]
FULL = {"C_1": "Cat", "SS_1": "Short", "OF_1": "Out A", "OF_2": "Out B"}
OK = {"ok": True, "missing_slots": [], "ineligible_slots": [], "duplicate_players": [], "unfillable_slots": []}


def _lineup(**kw):
    base = dict(team="Team 1", week_text="Week 3", slots=SLOTS, assignments=FULL, validation=OK,
                bench_count=2, locked=False, record_status="")
    base.update(kw)
    return lineup_answer(**base)


class LineupAnswerTests(unittest.TestCase):
    def test_complete_unsaved_lineup_says_save_is_still_needed(self):
        a = _lineup(record_status="draft")
        self.assertEqual(a["headline"], "Lineup complete: 4 of 4 starters set")
        self.assertEqual(a["status"], "Draft (not submitted)")
        self.assertIn("press Save Lineup", a["body"])
        self.assertEqual(a["primary"], "save")
        self.assertEqual(a["tone"], "good")
        self.assertEqual(a["tiles"][0], ("Starters", "4/4", ""))

    def test_open_spots_the_roster_can_fill(self):
        a = _lineup(assignments={**FULL, "SS_1": "", "OF_2": ""},
                    validation={**OK, "ok": False, "missing_slots": ["SS", "OF"]})
        self.assertEqual(a["headline"], "Your lineup has 2 open positions: Shortstop and OF 2")  # U4 wording
        self.assertEqual(a["primary"], "suggest")
        self.assertEqual(a["from_bench"], ["Shortstop", "OF 2"])
        self.assertIn(("Shortstop: from bench", ""), a["chips"])
        self.assertEqual(a["status"], "Not saved yet")

    def test_open_spot_nobody_on_the_roster_can_play_points_to_waivers(self):
        a = _lineup(assignments={**FULL, "C_1": ""}, validation={**OK, "missing_slots": ["C"], "unfillable_slots": ["C"]})
        self.assertEqual(a["headline"], "Your lineup has 1 open position: Catcher")  # U4 wording
        self.assertEqual(a["primary"], "waivers")
        self.assertEqual(a["need_help"], ["Catcher"])
        self.assertIn("Needs a waiver or trade: Catcher", a["body"])

    def test_ineligible_starter_blocks_save(self):
        a = _lineup(validation={**OK, "ok": False, "ineligible_slots": [{"slot": "SS", "player": "Cat"}]})
        self.assertEqual(a["headline"], "Fix 1 starter before saving")
        self.assertIn(("Cat at SS not eligible", "warn"), a["chips"])
        self.assertEqual(a["primary"], "suggest")

    def test_locked_lineup_has_no_edit_action_and_states_the_lock(self):
        a = _lineup(locked=True, record_status="locked", edit_message="Week 3 lineup is saved and locked.")
        self.assertEqual(a["headline"], "Lineup saved and locked: 4 of 4 starters")
        self.assertEqual(a["status"], "Saved and locked")
        self.assertEqual(a["primary"], "")
        self.assertNotIn("Save Lineup", a["body"])

    def test_proxy_is_named_in_the_kicker(self):
        self.assertEqual(_lineup(proxy=True)["kicker"], "Commissioner acting for Team 1 · Week 3")


def _analysis(verdict="Neutral", gain=0.4):
    return {
        "title": "Analysis: Cat for Short", "verdict": verdict, "weighted_gain": gain,
        "category_rows": [{"category": "HR", "change": 6.0}, {"category": "SB", "change": -4.0}, {"category": "BA", "change": 0.012}],
        "helps": ["HR", "BA"], "hurts": ["SB"],
        "player_rows": [{"side": "Give", "player": "Cat", "position": "C", "stats_line": "10 HR"},
                        {"side": "Receive", "player": "Short", "position": "SS/2B", "stats_line": "16 HR"}],
        "positions_lost": ["C"], "positions_gained": ["SS/2B"],
    }


class TradeVerdictTests(unittest.TestCase):
    def test_labels_follow_the_engine_classification(self):
        for engine, label, tone in (("Good for your team", "Favors your team", "good"),
                                    ("Bad for your team", "Favors the other team", "warn"),
                                    ("Neutral", "Balanced", "")):
            with self.subTest(engine=engine):
                v = trade_verdict(_analysis(engine), my_team="Team 1", partner="Team 2")
                self.assertEqual((v["label"], v["tone"]), (label, tone))
                self.assertIn("favors Team 2", v["body"])

    def test_roster_issue_on_your_team_overrides_the_label(self):
        issues = [{"team": "Team 1", "kind": "slot", "slot": "C", "message": "leaves your team without a C"},
                  {"team": "Team 2", "kind": "slot", "slot": "SS", "message": "leaves Team 2 without a SS"}]
        v = trade_verdict(_analysis("Good for your team", 3.1), my_team="Team 1", partner="Team 2", roster_issues=issues)
        self.assertEqual(v["label"], ROSTER_ISSUE_LABEL)
        self.assertEqual(v["headline"], "Creates roster issue · value favors your team")
        self.assertEqual(v["my_issues"], ["leaves your team without a C"])
        self.assertEqual(v["other_notes"], ["leaves Team 2 without a SS"])

    def test_open_roster_spots_are_not_a_roster_issue(self):
        issues = [{"team": "Team 1", "kind": "under", "slot": "", "message": "Your team would carry 9 players"}]
        v = trade_verdict(_analysis("Neutral"), my_team="Team 1", roster_issues=issues)
        self.assertEqual(v["label"], "Balanced")
        self.assertEqual(v["other_notes"], ["Your team would carry 9 players"])

    def test_tiles_and_category_chips_come_from_the_analysis(self):
        v = trade_verdict(_analysis("Good for your team", 3.14), my_team="Team 1")
        self.assertEqual(v["tiles"][0], ("Value difference", "+3.1", "need-weighted"))
        self.assertEqual(v["tiles"][1][1], "C")
        self.assertEqual(v["tiles"][2][1], "SS/2B")
        self.assertEqual([c for c, _t in v["chips"]], ["HR +6", "BA +.012", "SB −4"])


class TradeRosterIssueParityTests(unittest.TestCase):
    def test_warnings_are_the_issue_messages(self):
        import fantasy_trade_legality as legality

        src = (ROOT / "fantasy_trade_legality.py").read_text(encoding="utf-8")
        fn = src[src.index("def trade_roster_warnings("):src.index("def trade_roster_issues(")]
        self.assertIn('issue["message"]', fn)
        self.assertIn("trade_roster_issues(", fn)
        self.assertEqual(legality.trade_roster_warnings(None, proposer_team="A", recipient_team="B",
                                                       proposer_gives=[], proposer_receives=[]), [])


class TradeStatLineTests(unittest.TestCase):
    def test_zero_counting_stat_is_not_shown_as_a_rate(self):
        import pandas as pd
        from fantasy_trade_player_index import format_player_stat_line

        df = pd.DataFrame([{"Player": "Walker", "R": 73, "HR": 29, "RBI": 87, "SB": 0, "BA": 0.226, "G": 156}])
        self.assertEqual(format_player_stat_line(df, "Walker"), "R 73 · HR 29 · RBI 87 · SB 0 · AVG .226 · G 156")


class PhoneGapCssTests(unittest.TestCase):
    def test_invisible_carriers_leave_the_flow_without_nested_has(self):
        from mobile_foundation import mobile_foundation_css

        css = mobile_foundation_css()
        rule = css[css.index("8b."):]
        self.assertIn(".st-key-_url_page_sync_event {", rule)
        self.assertIn("> style:only-child) {", rule)
        self.assertEqual(rule.count("position: absolute !important;"), 2)
        self.assertNotIn("display: none", rule, "the URL-sync iframe must keep running: take it out of the flow, don't hide it")
        code = re.sub(r"/\*.*?\*/", "", rule, flags=re.S).replace(":has(", "\0")
        stack, depth = [], 0  # stack: depth at which each open :has( started
        for ch in code:
            if ch == "\0":
                self.assertFalse(stack, "a :has() nested inside :has() voids the whole CSS rule")
                stack.append(depth)
                depth += 1
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if stack and stack[-1] == depth:
                    stack.pop()


class FakeExpander:
    def __init__(self, log, label):
        self.log, self.label = log, label

    def __enter__(self):
        self.log.append(("enter", self.label))
        return self

    def __exit__(self, *_a):
        self.log.append(("exit", self.label))
        return False


class FakeSt:
    def __init__(self):
        self.log = []

    def expander(self, label, expanded=False):
        self.log.append(("expander", label, expanded))
        return FakeExpander(self.log, label)

    def caption(self, text):
        self.log.append(("caption", text))

    def markdown(self, text, **_kw):
        self.log.append(("markdown", text))


class CommissionerPanelTests(unittest.TestCase):
    def test_one_labelled_panel_and_a_visible_proxy_banner(self):
        import ui_hierarchy as ui

        st = FakeSt()
        panel = ui.commissioner_panel(st)
        self.assertEqual(st.log[0], ("expander", "🛡️ Commissioner Tools", False))
        self.assertIsInstance(panel, FakeExpander)
        ui.proxy_banner(st, "Commissioner acting for Team 3", "Logged.")
        self.assertIn("Commissioner acting for Team 3.", st.log[-1][1])
        self.assertIn('class="u1-commish"', st.log[-1][1])

    def test_lineup_commissioner_controls_render_in_the_panel(self):
        fn = WEEKLY[WEEKLY.index("def render_weekly_lineup_section("):]
        self.assertIn("panel = ui.commissioner_panel(st) if (is_commissioner or proxy_teams) else None", fn)
        picker = fn.index("_render_manage_team_picker(st, session, context, own_team=active_team, proxy=proxy_teams)")
        self.assertIn("with (panel if panel is not None else nullcontext()):", fn[picker - 120:picker])
        self.assertIn("render_edit_lineup_format_action(st, session)", fn[fn.index("with (panel if panel is not None else nullcontext()):\n        render_edit"):])
        self.assertIn("panel=panel if is_commissioner else None", fn)
        self.assertIn("ui.proxy_banner(st, proxy_control.banner(),", fn)
        self.assertNotIn('st.info(\n            f"**Commissioner acting for', fn)
        finalize = WEEKLY[WEEKLY.index("def _render_period_finalize("):]
        self.assertIn("with (panel if (is_commissioner and panel is not None) else nullcontext()):", finalize)

    def test_waiver_and_trade_commissioner_controls_use_the_same_panel(self):
        waiver = (ROOT / "fantasy_waiver_wire_ui.py").read_text(encoding="utf-8")
        fn = waiver[waiver.index("def _render_waiver_manage_team("):]
        fn = fn[:fn.index("\ndef ", 10)]
        self.assertIn("with ui.commissioner_panel(st):", fn)
        self.assertIn('ui.proxy_banner(st, f"Commissioner acting for {choice}"', fn)
        trade = TRADE[TRADE.index("def render_commissioner_trade_panel("):]
        self.assertIn("with ui.commissioner_panel(st):", trade[:trade.index("\ndef ", 10)])


class LineupPageOrderTests(unittest.TestCase):
    def test_answer_then_actions_then_board_then_save(self):
        fn = WEEKLY[WEEKLY.index("def render_weekly_lineup_section("):]
        order = [fn.index(s) for s in ('key=f"{prefix}_selected_week"', "answer = lineup_answer(", '"Use Suggested Lineup",',
                                       '"Check Waivers"', '"Explore Trades"', "render_interactive_lineup_board(", '"Save Lineup",')]
        self.assertEqual(order, sorted(order))
        self.assertNotIn("render_team_header_html(", fn)

    def test_new_actions_only_navigate_or_flag(self):
        fn = WEEKLY[WEEKLY.index("# Next actions."):WEEKLY.index("board_payload = build_interactive_board_payload(")]
        self.assertIn('on_click=nav_callback("Waiver Wire / Add-Drop Center")', fn)
        self.assertIn('on_click=lambda: session.__setitem__("_lineup_focus_trade_center", True)', fn)
        for forbidden in ("save_weekly_lineup", "persist_weekly_lineup_draft", "finalize"):
            self.assertNotIn(forbidden, fn)
        for key in re.findall(r'key=f"(u3lu_[^"]+)"', fn):
            self.assertTrue(key.endswith("_btn"), "button keys must not be snapshotted into page state")

    def test_page_head_label_and_compatibility(self):
        from nav_groups import NAV_LABELS

        self.assertEqual(NAV_LABELS["Fantasy Lineup Assistant"], "🧠 Lineup & Trades")
        self.assertIn('"Fantasy Lineup Assistant": "🧠 Fantasy Lineup Assistant"', APP, "old label still maps to the key")
        start = APP.index('elif active_page == "Fantasy Lineup Assistant":')
        body = APP[start:APP.index('elif active_page == "Waiver Wire', start)]
        self.assertIn('"🧠 Lineup & Trades",', body)
        self.assertNotIn("render_section_header(", body)
        self.assertLess(body.index("render_lineup_management_page("), body.index("render_active_saved_draft_chip("),
                        "the active-league card sits below the page content")
        self.assertIn("nav_callback=_u1_nav_cb", body)


class TradeCardWiringTests(unittest.TestCase):
    def test_card_leads_and_details_stay_available(self):
        fn = TRADE[TRADE.index("def _render_analysis_panel("):TRADE.index("def _render_analysis_details(")]
        order = [fn.index(s) for s in ("ui.trade_sides(", "ui.answer_card(", "ui.metric_tiles(", 'st.expander("Detailed calculation"')]
        self.assertEqual(order, sorted(order))
        details = TRADE[TRADE.index("def _render_analysis_details("):]
        details = details[:details.index("\ndef ", 10)]
        for kept in ("Verdict:", "verdict_text", "Players in the deal", "Current-season statistical comparison",
                     "Projected category direction", "Roster and position impact", "interpretation"):
            self.assertIn(kept, details)

    def test_one_analysis_slot_above_the_buttons(self):
        fn = TRADE[TRADE.index("def _render_build_analyze("):]
        fn = fn[:fn.index("\ndef ", 10)]
        self.assertEqual(fn.count("_render_analysis_panel(st, "), 3)
        self.assertEqual(fn.count("with analysis_slot.container():"), 3)
        self.assertLess(fn.index("analysis_slot = st.empty()"), fn.index('"Analyze Exact Trade",'))
        self.assertLess(fn.index("roster_issues = _trade_roster_issues("), fn.index("analysis_slot = st.empty()"))


if __name__ == "__main__":
    unittest.main()
