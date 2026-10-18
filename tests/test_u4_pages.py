"""U4: draft pages lead with an answer built from their own computed state, Valuation centers the
player you chose, the Lineup answer sorts open spots by what fixes them, Trade Center shows give ⇄
receive everywhere, and visible copy uses the current page names."""

import re
import unittest
from pathlib import Path

import pandas as pd

import u2_answers as u2a
import u4_answers as u4a
from u3_answers import lineup_answer

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
LIB = (ROOT / "draft_archive_ui.py").read_text(encoding="utf-8")
TRADE = (ROOT / "fantasy_trade_center_ui.py").read_text(encoding="utf-8")


def _fn(src: str, name: str) -> str:
    body = src[src.index(f"def {name}("):]
    return body[:body.index("\ndef ", 10)]


def _summary(**kw):
    base = {"filled_picks": 6, "total_picks": 40, "num_teams": 2, "current_pick": 7, "current_round": 4,
            "your_next_pick": 8, "draft_complete": False, "total_rounds": 20}
    base.update(kw)
    return base


class DraftRoomAnswerTests(unittest.TestCase):
    def test_in_progress_board(self):
        a = u4a.draft_room_answer(_summary(), your_team="Daniel", rounds=20, source="validated_import",
                                  unsaved=True, on_clock_team="Rival")
        self.assertEqual(a["headline"], "Pick 7 is next (round 4): 6 of 40 picks made")
        self.assertIn("Rival is on the clock.", a["body"])
        self.assertIn("Daniel picks next at #8.", a["body"])
        self.assertIn("Last change came from an imported draft file.", a["body"])
        self.assertIn("unsaved changes", a["body"])
        self.assertEqual(a["tiles"][-1], ("Board", "Unsaved", ""))

    def test_empty_board_makes_no_save_claim(self):
        a = u4a.draft_room_answer(_summary(filled_picks=0, current_pick=1, current_round=1, your_next_pick=1),
                                  your_team="Daniel", rounds=20, unsaved=True)
        self.assertEqual(a["headline"], "Ready to draft: 2 teams × 20 rounds, no picks yet")
        self.assertNotIn("unsaved", a["body"].lower())
        self.assertEqual(a["tiles"][-1], ("Board", "Empty", ""))

    def test_complete_board(self):
        a = u4a.draft_room_answer(_summary(filled_picks=40, draft_complete=True), your_team="Daniel", rounds=20)
        self.assertEqual(a["headline"], "Draft complete: all 40 picks made")
        self.assertNotIn("picks next", a["body"])

    def test_board_sources(self):
        self.assertEqual(u4a.board_source_text("draft_player:recommendation_card"), "picks entered here")
        self.assertEqual(u4a.board_source_text("live_draft_room"), "the Live Draft Room")
        self.assertEqual(u4a.board_source_text("runtime_ownership_sync"), "")


class DraftAssistantAnswerTests(unittest.TestCase):
    def test_uses_the_ranked_pick_and_its_own_reason(self):
        best = {"fullName": "Bobby Witt Jr.", "Primary Position": "SS", "Why this pick": "Fills SS; top Decision Score",
                "Decision Score": 88.123}
        a = u4a.draft_assistant_answer(best, best_value={"fullName": "Aaron Judge"}, summary=_summary(),
                                       gaps=["SS", "C", "SS"], team="Daniel")
        self.assertEqual(a["headline"], "Best pick now: Bobby Witt Jr. (SS)")
        self.assertTrue(a["body"].startswith("Fills SS; top Decision Score."))
        self.assertIn("Highest raw value is Aaron Judge, before roster fit.", a["body"])
        self.assertIn("Your roster still needs SS and C.", a["body"])
        self.assertEqual(a["tiles"][0], ("Decision Score", "88.12", "Jr."))
        self.assertEqual(a["compare"], ["Bobby Witt Jr.", "Aaron Judge"])

    def test_no_claim_of_a_biggest_need(self):
        a = u4a.draft_assistant_answer({"fullName": "X"}, summary=_summary(), gaps=["C", "OF"])
        self.assertNotIn("biggest", a["body"].lower())

    def test_complete_and_empty_states(self):
        self.assertEqual(u4a.draft_assistant_answer(None, summary=_summary(draft_complete=True))["headline"],
                         "Your draft is complete")
        self.assertEqual(u4a.draft_assistant_answer(None, summary=_summary())["headline"], "No recommendation yet")


class DraftLabAnswerTests(unittest.TestCase):
    def test_result_from_the_simulations_own_tables(self):
        summary = pd.DataFrame({"Fantasy Team": ["Team C", "Team D"], "Projected Team Rank": [2, 1],
                                "Total Projected Fantasy Value": [8.22, 8.30], "Position Gaps": ["C", "None"]})
        picks = pd.DataFrame({"Fantasy Team": ["Team D", "Team D"], "Pick Type": ["Good Pick", "Best Pick"],
                              "Player": ["A", "Randy Arozarena"], "Reason": ["x", "Filled a OF need."]})
        a = u4a.draft_lab_answer(summary, picks, total_picks=56)
        self.assertEqual(a["headline"], "Projected best draft: Team D")
        self.assertIn("Draft Lab Team Score 8.30, 0.08 ahead of Team C.", a["body"])
        self.assertIn("Best pick: Randy Arozarena (Filled a OF need).", a["body"])
        self.assertIn("filled every required position", a["body"])
        self.assertEqual(a["tiles"][1], ("Team score", "8.30", "Draft Lab Team Score"))

    def test_no_table_no_answer(self):
        self.assertIsNone(u4a.draft_lab_answer(pd.DataFrame()))


class LibraryAnswerTests(unittest.TestCase):
    def test_active_league_and_most_recent(self):
        archives = [{"draft_id": "b", "draft_name": "Mock 2", "updated_at": "2026-10-17T10:00"},
                    {"draft_id": "a", "draft_name": "Home League", "updated_at": "2026-10-01T10:00"}]
        a = u4a.library_answer(archives, active=archives[1], active_team="Team 1", active_team_count=4)
        self.assertEqual(a["headline"], "Active league: Home League")
        self.assertIn("2 saved drafts; most recent: Mock 2 (2026-10-17).", a["body"])
        self.assertEqual((a["recent_id"], a["recent_is_active"]), ("b", False))

    def test_empty_library(self):
        self.assertEqual(u4a.library_answer([])["headline"], "No saved drafts yet")


class ValuationFocusTests(unittest.TestCase):
    def _pool(self):
        from valuation_scores import add_valuation_scores

        df = pd.DataFrame({"fullName": [f"P{i}" for i in range(5)]})
        for c in ["R", "H", "2B", "3B", "HR", "RBI", "SB"]:
            df[c] = [50, 40, 30, 20, 10]
        for c in ["BA", "OBP", "SLG", "OPS"]:
            df[c] = [0.3, 0.29, 0.28, 0.27, 0.26]
        for c in ["R_trend", "H_trend", "2B_trend", "3B_trend", "HR_trend", "RBI_trend", "SB_trend", "BB_trend",
                  "BA_trend", "OBP_trend", "SLG_trend", "OPS_trend"]:
            df[c] = [0.0, 1.0, -1.0, 0.5, -0.5]
        return add_valuation_scores(df, 2, 1)

    def test_selected_player_leads_with_model_contributions(self):
        df = self._pool()
        ranked = df.sort_values("Valuation_Score", ascending=False)["fullName"].tolist()
        pick = ranked[2]
        a = u2a.valuation_answer(df, df, w_current=2, w_trend=1, years=[2024, 2025], focus=pick)
        self.assertTrue(a["focus_found"])
        self.assertEqual(a["player"], pick)
        self.assertTrue(a["headline"].startswith(f"{pick}: Valuation "))
        self.assertIn("3rd of 5", a["headline"])
        row = df[df["fullName"] == pick].iloc[0]
        prod, trend = a["contributions"]
        self.assertAlmostEqual(prod, 2 * row["Perf_Pct"] / 3 * 100)
        self.assertAlmostEqual(trend, 1 * row["Trend_Pct"] / 3 * 100)
        self.assertAlmostEqual((prod + trend) / 100, row["Valuation_Raw"])  # exactly the model's blend
        self.assertNotIn("decline", a["body"].lower())

    def test_default_or_missing_selection_leads_with_top(self):
        df = self._pool()
        top = df.sort_values("Valuation_Score", ascending=False).iloc[0]["fullName"]
        a = u2a.valuation_answer(df, df, w_current=2, w_trend=1, years=[2025], focus=top)
        self.assertTrue(a["headline"].startswith("Top valuation"))
        b = u2a.valuation_answer(df, df, w_current=2, w_trend=1, years=[2025], focus="Nobody")
        self.assertEqual(b["player"], top)
        self.assertIn("Nobody isn't in the current list", b["body"])

    def test_page_passes_the_selection_and_offers_a_way_back(self):
        fn = _fn(APP, "_render_u2_valuation_answer")
        self.assertIn('focus = str(st.session_state.get("valuation_selected_player") or "").strip()', fn)
        self.assertIn('("Show top player", lambda: st.session_state.pop("valuation_selected_player", None))', fn)


class LineupConsolidationTests(unittest.TestCase):
    SLOTS = [("C_1", "Catcher"), ("SS_1", "Shortstop"), ("OF_1", "OF 1"), ("OF_2", "OF 2")]

    def test_open_spots_sorted_by_what_fixes_them(self):
        a = lineup_answer(team="Team 1", week_text="Week 2", slots=self.SLOTS,
                          assignments={"C_1": "", "SS_1": "", "OF_1": "A", "OF_2": ""},
                          validation={"unfillable_slots": ["SS"], "ineligible_slots": [], "duplicate_players": []},
                          bench_count=2, locked=False)
        self.assertEqual(a["headline"], "Your lineup has 3 open positions: Catcher, Shortstop and OF 2")
        self.assertEqual(a["from_bench"], ["Catcher", "OF 2"])
        self.assertEqual(a["need_help"], ["Shortstop"])
        self.assertIn("Needs a waiver or trade: Shortstop", a["body"])

    def test_board_no_longer_repeats_the_answer_as_warnings(self):
        src = (ROOT / "fantasy_weekly_lineup_ui.py").read_text(encoding="utf-8")
        fn = _fn(src, "_render_open_slots_and_validation")
        self.assertIn('if "stays empty" in lower or "not eligible" in lower or "twice" in lower:\n            continue', fn)
        self.assertIn('if row.get("button_label")', fn)


class DraftPageWiringTests(unittest.TestCase):
    def _branch(self, expr):
        start = APP.index(f"elif active_page == {expr}:")
        nxt = re.compile(r"^elif active_page ==", re.M).search(APP, start + 10)
        return APP[start:nxt.start()]

    def test_answer_slot_sits_right_under_the_tool_switcher(self):
        for expr, slot in (('"Draft Room Simulator"', "room_answer_slot"), ('"Draft Assistant Simulator"', "da_answer_slot"),
                           ("DRAFT_LAB_PAGE", "lab_answer_slot")):
            body = self._branch(expr)
            with self.subTest(page=expr):
                nav = body.index("draft_tools.render_draft_tool_nav(st, active_page, _u1_nav_cb)")
                self.assertLess(nav, body.index(f"{slot} = st.container()"))
                self.assertLess(body.index(f"{slot} = st.container()") - nav, 120)
                self.assertIn(f"with {slot}:", body)

    def test_draft_room_actions_reuse_the_boards_own_paths(self):
        fn = _fn(APP, "_render_u4_draft_room_answer")
        self.assertIn("submit_board_pick_assignment(", fn)
        self.assertIn("record_manual_save_button_click(st.session_state)", fn)
        self.assertIn('_u1_nav_cb("Saved Draft Library")', fn)
        self.assertNotIn("draft_player(", fn)

    def test_import_section_stays_above_the_tabs_and_opens_while_pending(self):
        body = self._branch('"Draft Room Simulator"')
        self.assertLess(body.index('with st.expander("Import existing draft"'), body.index("st.tabs(["))
        self.assertIn("has_active_draft_import_upload(", body)
        self.assertIn('expanded=bool(_import_pending or st.session_state.get("_u4_draft_import_open"))', body)

    def test_draft_lab_controls_keep_their_keys_under_explore_more(self):
        body = self._branch("DRAFT_LAB_PAGE")
        settings = body.index('with st.expander("Simulation settings"')
        for widget in ('st.selectbox("Projection Window"', 'st.selectbox("Fantasy Format"', 'st.selectbox("Projection Style"',
                       '"Picks per Team",'):
            self.assertGreater(body.index(widget), settings)
        for key in ("draft_lab_window", "draft_lab_scoring_type", "draft_lab_projection_style", "draft_lab_picks_per_team"):
            self.assertIn(f'key="{key}"', body[settings:])
        self.assertNotIn("w1, w2, w3, w4, w5 = st.columns(5)", body)
        self.assertLess(body.index("lab_run_slot = st.container()"), settings)

    def test_assistant_answer_does_not_rescore(self):
        fn = _fn(APP, "_render_u4_draft_assistant_answer")
        for forbidden in ("apply_draft_pick_scoring", "Decision Score\"] =", "sort_values("):
            self.assertNotIn(forbidden, fn)

    def test_library_actions_reuse_the_card_paths(self):
        fn = _fn(LIB, "_render_library_answer")
        self.assertIn("_activate_archive_entry(st, session, recent_id)", fn)
        self.assertIn("session[_RENAME_CONFIRM_PREFIX + recent_id] = True", fn)
        self.assertIn("schedule_fantasy_analysis_navigation(session, target)", fn)


class TradePresentationTests(unittest.TestCase):
    def test_idea_cards_show_give_receive_and_only_engine_reasons(self):
        fn = _fn(TRADE, "_render_idea_card")
        self.assertIn("ui.trade_sides(", fn)
        for field in ('"Value Explanation"', '"Category Gains"', '"Category Losses"', '"Main Risk"'):
            self.assertIn(field, fn)
        self.assertIn("_queue_idea_builder_update", fn)

    def test_builder_headers_match_the_card(self):
        self.assertIn("YOU GIVE · {html_lib.escape(my_team)}", TRADE)
        self.assertIn("<h4>YOU RECEIVE</h4>", TRADE)
        self.assertNotIn('class="tc-hero"', _fn(TRADE, "_render_trade_center_hero"))


class LabelConsistencyTests(unittest.TestCase):
    OLD = ("Fantasy Standings Tracker", "Fantasy Lineup Assistant", "Waiver Wire / Add-Drop Center",
           "Comparison Tool", "Fantasy Sleepers & Busts")

    def test_visible_instructions_use_current_page_names(self):
        for f in ("streamlit_app.py", "app_tutorial.py", "fantasy_waiver_wire_ui.py", "draft_archive_ui.py"):
            src = (ROOT / f).read_text(encoding="utf-8")
            for old in self.OLD:
                with self.subTest(file=f, label=old):
                    self.assertNotIn(f"**{old}**", src)
        for old in self.OLD:
            self.assertNotIn(f'_nav_label(FANTASY_STANDINGS_PAGE, "{old}"', LIB)

    def test_old_labels_still_resolve_to_page_keys(self):
        for key, old in (("Comparison Tool", "📈 Comparison Tool"), ("Fantasy Sleepers & Busts", "💎 Fantasy Sleepers & Busts"),
                         ("Fantasy Lineup Assistant", "🧠 Fantasy Lineup Assistant"),
                         ("Fantasy Standings Tracker", "📊 Fantasy Standings Tracker"),
                         ("Waiver Wire / Add-Drop Center", "🔄 Waiver Wire / Add-Drop Center")):
            self.assertIn(f'"{key}": "{old}"', APP, "the pre-U1 label table keeps mapping old labels to keys")


if __name__ == "__main__":
    unittest.main()
