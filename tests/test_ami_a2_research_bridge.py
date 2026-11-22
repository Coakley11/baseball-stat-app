"""AMI A2 (owner, 2026-11-22): the selected Draft Strategy inside AMI's research answers.

* Research answers about players add where they sit in the selected strategy
  ("In your **Sluggers** strategy: Aaron Judge #1 (pinned, your note saved); Juan Soto #2.").
* "Compare my top two shortstops" resolves the players from the strategy, then the existing stat tools answer.
* Same safety as A1: read-only, account-scoped, deleted strategies never read, the page's Pro gate,
  signed-out visitors get no strategy line and no storage read.
"""

from __future__ import annotations

import copy
import unittest
from unittest import mock

import baseball_monetization as bm
import draft_strategy_v2 as v2
import draft_strategy_work as work
from ami_assistant.conversation import SESSION_KEY
from ami_assistant.engine import ask
from ami_assistant.strategy_research import membership_line, resolve_top_question
from ami_assistant.tools.registry import NOT_ENTITLED, REGISTRY
from ami_assistant.tools.strategy_research import position_code
from tests.ami_assistant_fixtures import synthetic_dataset
from tests.test_ami_my_strategy import ITEM_TYPES, _Backend, _strategy

COMPARE_PAGE = "Comparison Tool"
TREND_PAGE = "Trend Value"
VALUE_PAGE = "Valuation"
HIST_PAGE = "Historical Explorer"


class _Base(unittest.TestCase):
    ds = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.ds = synthetic_dataset()

    def setUp(self) -> None:
        self.stores = {acct: {t: _Backend() for t in ITEM_TYPES} for acct in ("A", "B")}
        self.account = "A"
        for p in (mock.patch("draft_strategy_store._backend",
                             side_effect=lambda t=v2.ITEM_TYPE: self.stores[self.account][t]),
                  mock.patch("suite_auth.is_auth_enabled", return_value=False)):
            p.start()
            self.addCleanup(p.stop)
        a = self.stores["A"][v2.ITEM_TYPE].rows
        sluggers = _strategy("SL", "Sluggers", [("Aaron Judge", "OF", "elite power"), ("Juan Soto", "OF", ""),
                                                ("Corey Seager", "SS", ""), ("Mookie Betts", "SS/OF", ""),
                                                ("Babe Ruth", "OF", "")])
        a["SL"] = v2.pin(sluggers, "Aaron Judge")
        a["SP"] = _strategy("SP", "Speed", [("Mookie Betts", "SS", "steals"), ("Corey Seager", "SS", "")])
        self.stores["B"][v2.ITEM_TYPE].rows["X"] = _strategy("X", "Barry Secret", [("Juan Soto", "OF", "B-only")])
        for acct in self.stores.values():
            for b in acct.values():
                b.writes.clear()
        self.s: dict = {}
        work.open_strategy(self.s, "SL")

    def ask(self, q: str, page: str = COMPARE_PAGE, session: dict | None = None, **kw):
        return ask(q, session_state=self.s if session is None else session, active_page=page, dataset=self.ds, **kw)

    def writes(self) -> list:
        return [w for acct in self.stores.values() for b in acct.values() for w in b.writes]


class MembershipOnResearchAnswers(_Base):
    def test_compare_answer_names_both_players_in_the_selected_strategy(self) -> None:
        r = self.ask("Compare Aaron Judge and Juan Soto")
        self.assertEqual(r.intent, "compare")
        self.assertIn("In your **Sluggers** strategy: Aaron Judge #1 (pinned, your note saved); Juan Soto #2.", r.answer)
        self.assertIn("strategy_membership", [t["tool"] for t in r.tools])

    def test_trend_valuation_and_historical_answers_get_the_line(self) -> None:
        for page, q in ((TREND_PAGE, "How is Aaron Judge trending?"),
                        (VALUE_PAGE, "What is Juan Soto's value?"),
                        (HIST_PAGE, "Show Corey Seager's seasons")):
            a = self.ask(q, page=page).answer
            self.assertIn("In your **Sluggers** strategy", a, q)

    def test_a_player_outside_the_strategy_is_reported_not_guessed(self) -> None:
        a = self.ask("Compare Aaron Judge and Geovany Soto").answer
        self.assertIn("Geovany Soto isn't in it", a)

    def test_no_selected_strategy_with_several_saved_adds_nothing(self) -> None:
        s: dict = {}
        a = self.ask("Compare Aaron Judge and Juan Soto", session=s).answer
        self.assertNotIn("strategy:", a.split("\n")[-1].lower())
        self.assertNotIn("In your", a)

    def test_only_one_saved_strategy_counts_as_selected(self) -> None:
        self.stores["A"][v2.ITEM_TYPE].rows.pop("SP")
        a = self.ask("Compare Aaron Judge and Juan Soto", session={}).answer
        self.assertIn("In your **Sluggers** strategy", a)

    def test_unsaved_editor_changes_are_labelled_and_the_saved_order_is_used(self) -> None:
        rec = self.s[work.WORK_KEY]["SL"]
        rec["strategy"] = {**rec["strategy"], "queue": list(reversed(rec["strategy"]["queue"]))}
        rec["dirty"] = True
        a = self.ask("Compare Aaron Judge and Juan Soto").answer
        self.assertIn("(saved version; the editor has unsaved changes)", a)
        self.assertIn("Aaron Judge #1", a)

    def test_a_deleted_selected_strategy_is_never_read(self) -> None:
        self.stores["A"][v2.ITEM_TYPE].rows.pop("SL")
        a = self.ask("Compare Aaron Judge and Juan Soto").answer
        self.assertNotIn("Sluggers", a)

    def test_leaderboards_and_non_player_answers_are_unchanged(self) -> None:
        r = self.ask("Who led in home runs in 2020?", page="Leaderboards")
        self.assertNotIn("strategy_membership", [t["tool"] for t in r.tools])


class SafetyRules(_Base):
    def test_read_only_no_storage_writes_and_only_ami_memory_changes(self) -> None:
        before = copy.deepcopy({k: v for k, v in self.s.items() if k != SESSION_KEY})
        self.ask("Compare Aaron Judge and Juan Soto")
        self.ask("Compare my top two shortstops")
        self.assertEqual({k: v for k, v in self.s.items() if k != SESSION_KEY}, before)
        self.assertEqual(self.writes(), [])

    def test_signed_out_visitors_get_the_research_answer_without_a_strategy_line_or_read(self) -> None:
        reads: list = []
        for acct in self.stores.values():
            for b in acct.values():
                b.all = (lambda orig: (lambda: reads.append(1) or orig()))(b.all)
        with mock.patch("suite_auth.is_anonymous_guest", return_value=True):
            r = self.ask("Compare Aaron Judge and Juan Soto")
            self.assertEqual(r.intent, "compare")
            self.assertNotIn("In your", r.answer)
            self.assertFalse(r.error)
            top = self.ask("Compare my top two shortstops").answer
            self.assertIn("Sign in", top)
        self.assertEqual(reads, [])

    def test_when_enforced_non_pro_users_get_no_strategy_data(self) -> None:
        free, pro = bm.default_entitlement(), bm.development_entitlement("pro")
        with mock.patch.object(bm, "ENFORCED_FEATURES", frozenset({bm.FeatureId.DRAFT_STRATEGIES})):
            for name, args in (("strategy_membership", {"players": ["Aaron Judge"]}),
                               ("strategy_top_at_position", {"position": "SS"})):
                self.assertEqual(REGISTRY.call(name, args, session=self.s, entitlement=free).error_code, NOT_ENTITLED)
            a = self.ask("Compare Aaron Judge and Juan Soto", entitlement=free).answer
            self.assertNotIn("Sluggers", a)
            self.assertIn("part of Pro", self.ask("Compare my top two shortstops", entitlement=free).answer)
            with mock.patch("baseball_monetization_ui.current_entitlement", return_value=pro):
                self.assertIn("Sluggers", self.ask("Compare Aaron Judge and Juan Soto", entitlement=pro).answer)
        self.assertNotIn(bm.FeatureId.DRAFT_STRATEGIES, bm.enforced_features())  # nothing enforced today

    def test_two_accounts_never_see_each_other(self) -> None:
        self.account = "B"
        s: dict = {}
        work.open_strategy(s, "X")
        a = self.ask("Compare Aaron Judge and Juan Soto", session=s).answer
        self.assertIn("Barry Secret", a)
        self.assertNotIn("Sluggers", a)
        self.account = "A"
        self.assertNotIn("Barry Secret", self.ask("Compare Aaron Judge and Juan Soto").answer)


class TopPlayersFromTheStrategy(_Base):
    def test_compare_my_top_two_shortstops_uses_the_strategy_then_the_stat_tools(self) -> None:
        r = self.ask("Compare my top two shortstops")
        self.assertEqual(r.intent, "compare")
        self.assertIn("From your **Sluggers** strategy, your top two shortstops: Corey Seager (#3), Mookie Betts (#4).",
                      r.answer)
        tools = [t["tool"] for t in r.tools]
        self.assertEqual(tools[0], "strategy_top_at_position")
        self.assertTrue(any(t not in ("strategy_top_at_position", "strategy_membership") for t in tools))

    def test_a_named_strategy_is_used(self) -> None:
        a = self.ask("Compare my top two shortstops in my Speed strategy").answer
        self.assertIn("From your **Speed** strategy, your top two shortstops: Mookie Betts (#1), Corey Seager (#2).", a)

    def test_a_multi_position_entry_counts_for_each_position(self) -> None:
        a = self.ask("Compare my top three outfielders").answer
        self.assertIn("Aaron Judge (#1, pinned), Juan Soto (#2), Mookie Betts (#4)", a)

    def test_too_few_at_the_position_is_said_plainly(self) -> None:
        a = self.ask("Compare my top two catchers").answer
        self.assertIn("Your **Sluggers** strategy has 0 catchers (none), so I can't take the top 2.", a)

    def test_one_player_becomes_a_profile_question(self) -> None:
        r = self.ask("Tell me about my top outfielder")
        self.assertIn("your top outfielder: Aaron Judge (#1, pinned)", r.answer)

    def test_resolver_ignores_questions_without_the_personal_cue(self) -> None:
        self.assertIsNone(resolve_top_question("Who are the top two shortstops?", lambda *a: None))
        self.assertEqual(position_code("first basemen"), "1B")
        self.assertEqual(position_code("relievers"), "RP")


class ResearchContextLine(_Base):
    def test_research_pages_name_the_selected_strategy_from_session_only(self) -> None:
        from ami_assistant.context import build_ami_context

        for page in (TREND_PAGE, VALUE_PAGE, HIST_PAGE, "Fantasy Sleepers & Busts"):
            ctx = build_ami_context(self.s, page)
            self.assertIn("strategy Sluggers", ctx.summary(), page)
        self.assertNotIn("strategy", build_ami_context(self.s, "Leaderboards").summary())
        self.assertEqual(build_ami_context({}, TREND_PAGE).strategy, {})
        self.assertEqual(self.writes(), [])


class PositionalDepth(_Base):
    BOARD = {"page": "Draft Assistant Simulator", "position_scarcity_table": [
        {"Position": "SS", "Available Players": 7, "Top Available": "Gunnar Henderson", "Scarcity Dropoff": 4.2},
        {"Position": "C", "Available Players": 3, "Top Available": "Adley Rutschman", "Scarcity Dropoff": 9.1}]}

    def test_strategy_depth_with_a_board_uses_the_draft_pages_table(self) -> None:
        self.s["_ami_draft_snapshot"] = copy.deepcopy(self.BOARD)
        a = self.ask("How deep is shortstop in my strategy?", page="Draft Assistant Simulator").answer
        self.assertIn("Your **Sluggers** strategy has 2 shortstops: Corey Seager (#3), Mookie Betts (#4).", a)
        self.assertIn("On your current draft board (SS): 7 still available, best available Gunnar Henderson, "
                      "scarcity drop-off 4.2.", a)

    def test_without_a_board_ami_says_it_needs_one(self) -> None:
        a = self.ask("Is catcher scarce in my strategy?").answer
        self.assertIn("has 0 catchers.", a)
        self.assertIn("I need a draft board", a)

    def test_depth_questions_without_the_strategy_keep_their_route(self) -> None:
        from ami_assistant.strategy_research import resolve_depth_question

        for q in ("Do I have enough catchers?", "How deep is shortstop this year?", "Is catcher scarce?"):
            self.assertIsNone(resolve_depth_question(q, lambda *a: self.fail("no tool call expected")), q)

    def test_depth_is_read_only_and_gated(self) -> None:
        free = bm.default_entitlement()
        with mock.patch.object(bm, "ENFORCED_FEATURES", frozenset({bm.FeatureId.DRAFT_STRATEGIES})):
            self.assertIn("part of Pro", self.ask("How deep is shortstop in my strategy?", entitlement=free).answer)
        with mock.patch("suite_auth.is_anonymous_guest", return_value=True):
            self.assertIn("Sign in", self.ask("How deep is shortstop in my strategy?").answer)
        self.assertEqual(self.writes(), [])


class LineWording(unittest.TestCase):
    def test_empty_or_refused_results_give_no_line(self) -> None:
        from ami_assistant.tools.registry import ToolResult, fail

        self.assertEqual(membership_line(fail("strategy_membership", NOT_ENTITLED, "x")), "")
        self.assertEqual(membership_line(ToolResult("strategy_membership", True, {"strategy": None, "players": []})), "")


if __name__ == "__main__":
    unittest.main()
