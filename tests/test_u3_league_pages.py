"""U3B–U3D: the Lineup page leads with whether this week's lineup is complete and saved,
and commissioner controls sit in one marked panel."""

import re
import unittest
from contextlib import nullcontext
from pathlib import Path

from u3_answers import lineup_answer

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
        self.assertEqual(a["headline"], "2 starting spots open: Shortstop and OF 2")
        self.assertEqual(a["primary"], "suggest")
        self.assertIn(("Shortstop open", "warn"), a["chips"])
        self.assertEqual(a["status"], "Not saved yet")

    def test_open_spot_nobody_on_the_roster_can_play_points_to_waivers(self):
        a = _lineup(assignments={**FULL, "C_1": ""}, validation={**OK, "missing_slots": ["C"], "unfillable_slots": ["C"]})
        self.assertEqual(a["headline"], "3 of 4 starters set; this roster has no one for Catcher")
        self.assertEqual(a["primary"], "waivers")
        self.assertIn("Check waivers", a["body"])

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


if __name__ == "__main__":
    unittest.main()
