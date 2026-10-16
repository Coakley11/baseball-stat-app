"""AMI assistant: intent routing, player resolution, page context and follow-ups (synthetic data)."""

from __future__ import annotations

import unittest

from ami_assistant import router as r
from ami_assistant.context import AmiPageContext, build_ami_context
from ami_assistant.conversation import ConversationState
from ami_assistant.engine import ask
from ami_assistant.players import AMBIGUOUS, NOT_FOUND, RESOLVED, find_player_mentions, resolve_label, resolve_player
from tests.ami_assistant_fixtures import synthetic_dataset


def route(question: str, page: str = "", session: dict | None = None, conv: ConversationState | None = None) -> r.Plan:
    ds = synthetic_dataset()
    return r.Router(ds).route(question, build_ami_context(session or {}, page), conv or ConversationState())


class PlayerResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ds = synthetic_dataset()

    def test_bare_surname_prefers_the_recent_hitter_and_says_so(self) -> None:
        res = resolve_player(self.ds, "Judge")
        self.assertEqual(res.status, RESOLVED)
        self.assertEqual(res.player.player_id, "judgeaa01")
        self.assertIn("Joe Judge", res.note)

    def test_pitchers_and_small_samples_lose_to_the_clear_hitter(self) -> None:
        self.assertEqual(resolve_player(self.ds, "Soto").player.player_id, "sotoju01")
        self.assertEqual(resolve_player(self.ds, "Bobby Witt").player.player_id, "wittbo02")

    def test_comparable_players_with_one_name_are_ambiguous(self) -> None:
        res = resolve_player(self.ds, "Frank Thomas")
        self.assertEqual(res.status, AMBIGUOUS)
        self.assertEqual({c.player_id for c in res.candidates}, {"thomafr03", "thomafr04"})

    def test_page_selection_breaks_ties(self) -> None:
        res = resolve_player(self.ds, "Frank Thomas", prefer_ids=["thomafr03"])
        self.assertEqual(res.player.player_id, "thomafr03")

    def test_dropdown_labels_with_spans_resolve_exactly(self) -> None:
        self.assertEqual(resolve_label(self.ds, "Frank Thomas (1951-1966)").player.player_id, "thomafr03")
        self.assertEqual(resolve_label(self.ds, "Aaron Judge").player.player_id, "judgeaa01")

    def test_unknown_name(self) -> None:
        self.assertEqual(resolve_player(self.ds, "Zzyzx Qwerty").status, NOT_FOUND)

    def test_mentions_ignore_ordinary_and_app_words(self) -> None:
        names = [m.resolution.player.name for m in find_player_mentions(self.ds, "Compare Judge and Soto on Trend Value")]
        self.assertEqual(names, ["Aaron Judge", "Juan Soto"])
        self.assertEqual(find_player_mentions(self.ds, "Who had more power? Show the best shortstops"), [])
        self.assertEqual([m.resolution.player.name for m in find_player_mentions(self.ds, "Show me Mookie Betts's best seasons")],
                         ["Mookie Betts"])


class IntentRoutingTests(unittest.TestCase):
    def test_app_help(self) -> None:
        self.assertEqual(route("How do I compare two players?").intent, r.HELP_HOWTO)
        self.assertEqual(route("Where do I make a trade?").calls[0].args, {"task": "make_trade"})
        self.assertEqual(route("How do I add someone from waivers?").calls[0].args, {"task": "add_waiver"})
        self.assertEqual(route("How do I use Historical Explorer?").calls[0].args, {"task": "historical_explorer"})
        page = route("What can I do on this page?", page="Trend Value")
        self.assertEqual((page.intent, page.calls[0].args), (r.HELP_PAGE, {"page": "Trend Value"}))
        self.assertEqual(route("What does this chart mean?", page="Leaderboards").calls[0].args, {"page": "Leaderboards"})

    def test_metric_and_page_definitions(self) -> None:
        self.assertEqual(route("What does Decision Score mean?").calls[0].args, {"term": "decision_score"})
        self.assertEqual(route("What does Valuation Score mean?").calls[0].args, {"term": "valuation_score"})
        # Naming a page asks about the page (which includes its terms).
        self.assertEqual(route("What does Valuation mean?").calls[0].args, {"page": "Valuation"})
        self.assertEqual(route("What is Trend Value?").calls[0].args, {"page": "Trend Value"})

    def test_player_lookup(self) -> None:
        plan = route("Show me Babe Ruth's best seasons")
        self.assertEqual((plan.intent, plan.tool_names), (r.PROFILE, ["get_player_profile"]))
        plan = route("How did Aaron Judge do in 2022?")
        self.assertEqual(plan.intent, r.SEASONS)
        self.assertEqual(plan.calls[0].args["year_range"], [2022, 2022])

    def test_comparison(self) -> None:
        plan = route("Compare Aaron Judge and Juan Soto.")
        self.assertEqual(plan.intent, r.COMPARE)
        self.assertEqual(plan.calls[0].args, {"player_ids": ["judgeaa01", "sotoju01"]})
        plan = route("Who had the better five-year OPS, Judge or Soto?")
        self.assertEqual(plan.calls[0].args["year_range"], [2021, 2025])
        self.assertEqual(plan.calls[0].args["stats"], ["OPS"])

    def test_leaderboard(self) -> None:
        plan = route("Who are the best shortstops over the last five years?")
        self.assertEqual(plan.intent, r.LEADERBOARD)
        self.assertEqual(plan.calls[0].args, {"stat": "OPS", "top_n": 10, "year_range": [2021, 2025], "position": "SS"})
        plan = route("Who led in home runs from 2020 to 2025?")
        self.assertEqual(plan.calls[0].args["stat"], "HR")
        self.assertNotIn("position", plan.calls[0].args)

    def test_trend(self) -> None:
        plan = route("How has Mookie Betts's power changed over time?")
        self.assertEqual(plan.intent, r.TREND)
        self.assertEqual(plan.calls[0].args["stats"], ["HR", "SLG", "2B"])
        leaders = route("Who is improving fastest in OPS?", page="Trend Value",
                        session={"single_trend_dashboard_player": "Bobby Witt"})
        self.assertEqual((leaders.intent, leaders.calls[0].args["stat"]), (r.TREND_LEADERS, "OPS"))

    def test_valuation(self) -> None:
        plan = route("Is Bobby Witt undervalued?")
        self.assertEqual((plan.intent, plan.calls[0].args["player_id"]), (r.VALUATION, "wittbo02"))
        board = route("Who are the best values?", page="Valuation", session={"valuation_selected_player": "Aaron Judge"})
        self.assertEqual(board.intent, r.VALUATION_BOARD)

    def test_draft_questions_are_read_only(self) -> None:
        self.assertEqual(route("Who should I draft next?").tool_names, ["get_draft_recommendations"])
        self.assertEqual(route("What positions am I weak at?").tool_names, ["get_team_needs"])
        self.assertEqual(route("Who are the best available shortstops?").calls[0].args, {"limit": 5, "position": "SS"})
        self.assertEqual(route("Should I draft for need or take the best player available?").intent, r.DRAFT_STRATEGY)
        self.assertEqual(route("Why is Bobby Witt recommended?", page="Draft Assistant Simulator").tool_names,
                         ["explain_draft_recommendation"])

    def test_fantasy_team_questions_route_to_unwired_contracts(self) -> None:
        for question, tool_name in (("I need a shortstop. What can I do?", "get_available_free_agents"),
                                    ("Who should I drop?", "get_available_free_agents"),
                                    ("Would this trade improve my team?", "evaluate_trade"),
                                    ("Who should I start this week?", "get_lineup"),
                                    ("What categories am I weakest in?", "get_standings")):
            plan = route(question)
            self.assertEqual(plan.intent, r.FANTASY, question)
            self.assertEqual(plan.calls[0].name, tool_name, question)

    def test_requests_to_change_things_are_refused(self) -> None:
        for question, action in (("Draft Bobby Witt for me", "draft_player"), ("Add Juan Soto to my team", "add_waiver_player"),
                                 ("Drop Mookie Betts", "drop_player"), ("Trade Judge for Soto", "execute_trade"),
                                 ("Please bench Corey Seager", "change_lineup"), ("Queue Rookie Guy", "queue_player")):
            plan = route(question)
            self.assertEqual((plan.intent, plan.action), (r.ACTION, action), question)
            self.assertTrue(all(c.name in ("find_feature", "explain_app_page") for c in plan.calls))
        # Page names that start with a verb are not instructions.
        self.assertNotEqual(route("Draft Lab: what does it do?").intent, r.ACTION)

    def test_current_mlb_questions_are_outside_the_data(self) -> None:
        for q in ("Who leads MLB in home runs today?", "Is Aaron Judge injured right now?", "How did Soto do in 2030?"):
            plan = route(q)
            self.assertEqual((plan.intent, plan.grounding), (r.EXTERNAL, "external_current"), q)
            self.assertEqual(plan.calls, [])

    def test_unknown_and_ambiguous_names_ask_instead_of_guessing(self) -> None:
        plan = route("Compare Judge and Smithers")
        self.assertEqual(plan.intent, r.CLARIFY)
        self.assertIn("Smithers", plan.clarification)
        plan = route("Compare Frank Thomas and Babe Ruth")
        self.assertEqual(plan.intent, r.CLARIFY)
        self.assertIn("1951–1966", plan.clarification)


class PageContextTests(unittest.TestCase):
    def test_selected_players_page_and_range(self) -> None:
        ctx = build_ami_context({"compare_players": ["Aaron Judge", "Juan Soto"], "compare_year_range": (2021, 2025),
                                 "compare_stat": "OPS"}, "Comparison Tool")
        self.assertEqual(ctx.players, ("Aaron Judge", "Juan Soto"))
        self.assertEqual(ctx.year_range, (2021, 2025))
        self.assertIn("Aaron Judge, Juan Soto", ctx.summary())

    def test_current_player_feeds_pronoun_questions(self) -> None:
        plan = route("Why is he ranked this high?", page="Valuation", session={"valuation_selected_player": "Bobby Witt"})
        self.assertEqual((plan.intent, plan.calls[0].args["player_id"]), (r.VALUATION, "wittbo02"))
        self.assertIn("page selection", plan.used_context)
        plan = route("Why does this player's trend look strong?", page="Trend Value",
                     session={"single_trend_dashboard_player": "Mookie Betts", "trend_lag": 4})
        self.assertEqual((plan.intent, plan.calls[0].args["window"]), (r.TREND, 4))

    def test_two_selected_players_feed_a_comparison(self) -> None:
        plan = route("Who had the higher OPS from 2022 to 2025?", page="Comparison Tool",
                     session={"compare_players": ["Aaron Judge", "Juan Soto"]})
        self.assertEqual(plan.calls[0].args, {"player_ids": ["judgeaa01", "sotoju01"], "year_range": [2022, 2025], "stats": ["OPS"]})

    def test_changed_page_range_is_used_for_this_range(self) -> None:
        a = route("Who are the best shortstops in this range?", page="Career Totals", session={"career_year_range_filter": [2015, 2019]})
        b = route("Who are the best shortstops in this range?", page="Career Totals", session={"career_year_range_filter": [2021, 2025]})
        self.assertEqual(a.calls[0].args["year_range"], [2015, 2019])
        self.assertEqual(b.calls[0].args["year_range"], [2021, 2025])

    def test_paywall_placeholder_is_not_a_page(self) -> None:
        self.assertEqual(build_ami_context({}, "__MONETIZATION_GATE__").page, "")

    def test_missing_selection_asks(self) -> None:
        self.assertEqual(route("Why is he ranked this high?", page="Valuation").intent, r.VALUATION_BOARD)
        self.assertEqual(route("Show me his best seasons").intent, r.CLARIFY)


class FollowUpTests(unittest.TestCase):
    def test_comparison_follow_ups_keep_players(self) -> None:
        ds = synthetic_dataset()
        session: dict = {}
        first = ask("Compare Judge and Soto.", session_state=session, active_page="Comparison Tool", dataset=ds)
        self.assertEqual(first.intent, r.COMPARE)
        second = ask("What about just the last three years?", session_state=session, active_page="Comparison Tool", dataset=ds)
        self.assertEqual(second.intent, r.COMPARE)
        self.assertIn("seasons 2023–2025", second.answer)
        self.assertIn("conversation", second.used_context)
        third = ask("Who had more power?", session_state=session, active_page="Comparison Tool", dataset=ds)
        self.assertEqual(third.intent, r.COMPARE)
        self.assertIn("2023–2025", third.answer)
        self.assertIn("home runs", third.answer)
        self.assertIn("Aaron Judge", third.answer)

    def test_pronoun_after_two_players_asks_which(self) -> None:
        conv = ConversationState(intent=r.COMPARE, player_ids=["judgeaa01", "sotoju01"], player_names=["Aaron Judge", "Juan Soto"])
        plan = route("How has his power changed?", conv=conv)
        self.assertEqual(plan.intent, r.CLARIFY)
        self.assertIn("Aaron Judge or Juan Soto", plan.clarification)

    def test_leaderboard_follow_up_switches_position_and_stat(self) -> None:
        ds = synthetic_dataset()
        session: dict = {}
        ask("Who are the best shortstops over the last five years?", session_state=session, dataset=ds)
        nxt = r.Router(ds).route("What about catchers?", AmiPageContext(), ConversationState.from_dict(session["_ami_assistant_conversation"]))
        self.assertEqual(nxt.calls[0].args["position"], "C")
        self.assertEqual(nxt.calls[0].args["year_range"], [2021, 2025])

    def test_new_names_replace_the_subject(self) -> None:
        ds = synthetic_dataset()
        session: dict = {}
        ask("Compare Judge and Soto", session_state=session, dataset=ds)
        ask("Tell me about Babe Ruth", session_state=session, dataset=ds)
        self.assertEqual(session["_ami_assistant_conversation"]["player_ids"], ["ruthba01"])


if __name__ == "__main__":
    unittest.main()
