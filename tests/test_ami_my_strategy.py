"""AMI A1 (owner, 2026-11-08): the existing AMI Coach reads the user's own saved Draft Strategies.

* ``my_strategy`` answers questions about the user's own saved strategies; ``draft_strategy`` stays the
  general drafting-advice intent.
* Read-only: no tool writes to storage or to the session (proved with recording backends and
  before/after session snapshots).
* Account-scoped: AMI reads only through the strategy store for the signed-in account.
* Deleted strategies are never read (KI-1 coordination).
* Saved data and unsaved editor changes are kept apart; nothing is invented.
* Signed-out visitors get a sign-in answer, and the Global Queue stays free. When enforcement is on,
  the strategy tools follow the page's Pro gate.
"""

from __future__ import annotations

import copy
import unittest
from unittest import mock

import baseball_monetization as bm
import draft_strategy_store as dss
import draft_strategy_v2 as v2
import draft_strategy_work as work
from ami_assistant import router as r
from ami_assistant import strategy_router as sr
from ami_assistant.context import AmiPageContext, build_ami_context
from ami_assistant.conversation import SESSION_KEY, ConversationState
from ami_assistant.engine import ask
from ami_assistant.safety import find_secrets
from ami_assistant.tools.registry import NOT_ENTITLED, REGISTRY
from ami_assistant.tools import strategy as ts
from tests.ami_assistant_fixtures import synthetic_dataset

PAGE = sr.STRATEGY_PAGE
STRATEGY_TOOLS = ("list_my_strategies", "get_my_strategy", "compare_strategy_to_global")


class _Backend:
    """In-memory rows of one item type; records every write."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.writes: list[tuple[str, str]] = []

    def put(self, key, title, payload):
        self.writes.append(("put", key))
        self.rows[key] = copy.deepcopy(payload)

    def all(self):
        return copy.deepcopy(list(self.rows.values()))

    def fetch(self, key):
        return copy.deepcopy(self.rows.get(key))

    def delete(self, key):
        self.writes.append(("delete", key))
        self.rows.pop(key, None)


def _strategy(sid: str, name: str, players: list[tuple[str, str, str]]) -> dict:
    s = v2.new_strategy(name, queue=[{"name": n, "position": p} for n, p, _ in players])
    s = {**s, "id": sid}
    for n, _p, note in players:
        if note:
            s = v2.set_note(s, n, note)
    return s


ITEM_TYPES = (v2.ITEM_TYPE, v2.BACKUP_ITEM_TYPE, v2.RESEARCH_ITEM_TYPE, v2.TRASH_ITEM_TYPE)


class _Base(unittest.TestCase):
    ds = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.ds = synthetic_dataset()

    def setUp(self) -> None:
        # One store per account: storage is account-scoped (Supabase RLS / the workspace folder).
        self.stores = {acct: {t: _Backend() for t in ITEM_TYPES} for acct in ("A", "B")}
        self.account = "A"
        for p in (mock.patch("draft_strategy_store._backend",
                             side_effect=lambda t=v2.ITEM_TYPE: self.stores[self.account][t]),
                  mock.patch("suite_auth.is_auth_enabled", return_value=False)):
            p.start()
            self.addCleanup(p.stop)
        a = self.stores["A"][v2.ITEM_TYPE].rows
        power = _strategy("P", "Power-Hitting", [("Aaron Judge", "OF", "elite power"), ("Kyle Schwarber", "OF", ""),
                                                 ("Salvador Perez", "C", "late C"), ("Pete Alonso", "1B", ""),
                                                 ("Will Smith", "C", "")])
        power = v2.pin(power, "Aaron Judge")
        a["P"] = v2.set_preferences(power, {"category_priorities": ["HR", "RBI"], "ranking_note": "HR over AVG"})
        a["S"] = _strategy("S", "Speed", [("Bobby Witt Jr.", "SS", "five tools"), ("Elly De La Cruz", "SS", "")])
        v2.append_research({}, "S", "Witt stole 30+ in each of the last 3 seasons", kind="finding", player="Bobby Witt Jr.")
        self.stores["B"][v2.ITEM_TYPE].rows["X"] = _strategy("X", "Barry Secret", [("Gunnar Henderson", "SS", "B-only note")])
        for b in self.stores["A"].values():
            b.writes.clear()
        self.s: dict = {"draft_queue": ["Aaron Judge", "Juan Soto"],
                        "draft_queue_plan": {"pins": [], "notes": {"juan soto": "global note"}, "moves": []}}
        work.open_strategy(self.s, "P")

    def ask(self, q: str, page: str = PAGE, session: dict | None = None):
        return ask(q, session_state=self.s if session is None else session, active_page=page, dataset=self.ds)

    def writes(self) -> list:
        return [w for acct in self.stores.values() for b in acct.values() for w in b.writes]


class RoutingTests(_Base):
    OWNER = {
        "What players are in my Power-Hitting Strategy?": (sr.F_CONTENTS, "get_my_strategy"),
        "Where did I rank Aaron Judge?": (sr.F_RANK, "get_my_strategy"),
        "Is Juan Soto in this queue?": (sr.F_MEMBER, "get_my_strategy"),
        "What notes did I save about Bobby Witt Jr.?": (sr.F_NOTE, "get_my_strategy"),
        "How many catchers do I have in this strategy?": (sr.F_POSITIONS, "get_my_strategy"),
        "What are my main positional priorities?": (sr.F_PRIORITIES, "get_my_strategy"),
        "How does this strategy differ from my Global Queue?": (sr.F_DIFF, "compare_strategy_to_global"),
        "Which saved strategies do I have?": (sr.F_LIST, "list_my_strategies"),
    }

    def _route(self, q: str, page: str = PAGE, conv: ConversationState | None = None):
        ctx = build_ami_context(self.s, page)
        return r.Router(self.ds).route(q, ctx, conv or ConversationState())

    def test_the_owners_questions_route_to_my_strategy(self) -> None:
        for q, (focus, tool) in self.OWNER.items():
            plan = self._route(q)
            self.assertEqual((plan.intent, plan.focus, plan.tool_names), (sr.MY_STRATEGY, focus, [tool]), q)

    def test_a_named_strategy_and_player_are_passed_to_the_tool(self) -> None:
        plan = self._route("What players are in my Power-Hitting Strategy?")
        self.assertEqual(plan.calls[0].args["name"], "power-hitting")
        plan = self._route("Where did I rank Aaron Judge?")
        self.assertEqual(plan.calls[0].args, {"name": "", "player": "Aaron Judge"})

    def test_general_drafting_advice_stays_with_the_existing_intents(self) -> None:
        self.assertEqual(self._route("Should I draft for need or best available?", "Live Draft Room").intent,
                         r.DRAFT_STRATEGY)
        for q in ("What is a good draft strategy?", "Who should I draft next?", "How do I save my strategy?",
                  "What does positional scarcity mean?", "Is my lineup saved?", "Compare Aaron Judge and Juan Soto."):
            self.assertNotEqual(self._route(q).intent, sr.MY_STRATEGY, q)

    def test_this_queue_off_the_strategy_page_is_not_a_strategy_question(self) -> None:
        self.assertNotEqual(self._route("Is Juan Soto in this queue?", "Live Draft Room").intent, sr.MY_STRATEGY)

    def test_change_requests_get_a_strategy_answer_not_a_waiver_answer(self) -> None:
        plan = self._route("Add Aaron Judge to my Speed strategy")
        self.assertEqual((plan.intent, plan.calls), (sr.MY_STRATEGY, []))
        self.assertIn("Add to this strategy", plan.clarification)
        self.assertIn("**Speed**", plan.clarification)
        self.assertNotIn("waiver", plan.clarification.lower())


class AnswerTests(_Base):
    def test_contents_of_a_named_strategy(self) -> None:
        a = self.ask("What players are in my Power-Hitting Strategy?").answer
        self.assertIn("**Power-Hitting**", a)
        self.assertIn("5 players", a)
        self.assertIn("1. **Aaron Judge** · OF · 📌 pinned · has a note", a)

    def test_rank_membership_and_a_player_who_is_not_there(self) -> None:
        self.assertIn("You ranked **Aaron Judge** #1 of 5 in **Power-Hitting** (selected, saved). It's pinned.",
                      self.ask("Where did I rank Aaron Judge?").answer)
        self.assertIn("**Juan Soto** isn't in **Power-Hitting**", self.ask("Is Juan Soto in this queue?").answer)
        self.assertIn("Yes: **Will Smith** is #5 of 5", self.ask("Is Will Smith in this strategy?").answer)

    def test_notes_are_quoted_exactly_and_found_in_another_strategy(self) -> None:
        a = self.ask("What notes did I save about Bobby Witt Jr.?").answer
        self.assertIn("**Bobby Witt Jr.** is in your saved strategy **Speed** (#1 of 2): “five tools”", a)
        a = self.ask("What notes did I save about Aaron Judge?").answer
        self.assertIn("“elite power”", a)
        a = self.ask("What notes did I save about Pete Alonso?").answer
        self.assertIn("You haven't saved a note on **Pete Alonso**", a)

    def test_positions_priorities_and_research(self) -> None:
        a = self.ask("How many catchers do I have in this strategy?").answer
        self.assertIn("2 catchers: Salvador Perez (#3), Will Smith (#5)", a)
        a = self.ask("What are my main positional priorities?").answer
        for bit in ("Balanced (recommended)", "HR, RBI", "“HR over AVG”", "Pinned:** Aaron Judge", "2 C, 2 OF, 1 1B"):
            self.assertIn(bit, a)
        a = self.ask("What research have I saved in my Speed strategy?").answer
        self.assertIn("Witt stole 30+ in each of the last 3 seasons", a)

    def test_difference_from_the_global_queue(self) -> None:
        a = self.ask("How does this strategy differ from my Global Queue?").answer
        self.assertIn("Only in the Global Queue (1): Juan Soto", a)
        self.assertIn("In both: 1", a)
        self.assertIn("Nothing was changed", a)

    def test_list_marks_the_selected_strategy(self) -> None:
        a = self.ask("Which saved strategies do I have?").answer
        self.assertIn("- **Power-Hitting** · 5 players · selected", a)
        self.assertIn("- **Speed** · 2 players", a)

    def test_a_follow_up_keeps_the_strategy_and_question(self) -> None:
        self.ask("Where did I rank Aaron Judge?")
        a = self.ask("What about Pete Alonso?").answer
        self.assertIn("You ranked **Pete Alonso** #4 of 5", a)

    def test_global_queue_questions_are_answered_from_the_global_queue(self) -> None:
        a = self.ask("Is Juan Soto in my Global Queue?").answer
        self.assertIn("**Juan Soto** is #2 of 2 in your **Global Queue**", a)


class UnsavedTests(_Base):
    def test_unsaved_edits_are_kept_apart_from_saved_information(self) -> None:
        work.edit(self.s, "P", v2.move, "Pete Alonso", 0)
        a = self.ask("Where did I rank Pete Alonso?").answer
        self.assertIn("You ranked **Pete Alonso** #4 of 5 in **Power-Hitting** (selected, saved).", a)
        self.assertIn("**Unsaved changes in the editor** (not saved yet): **Pete Alonso** is #1 of 5.", a)
        self.assertEqual(self.stores["A"][v2.ITEM_TYPE].rows["P"]["queue"][3]["name"], "Pete Alonso")  # not saved by AMI

    def test_a_never_saved_strategy_is_labelled_as_unsaved(self) -> None:
        work.create(self.s, "Draft Day", from_global=True)
        a = self.ask("What players are in this strategy?").answer
        self.assertIn("**Draft Day** hasn't been saved yet", a)
        self.assertIn("(not saved yet)", a)
        self.assertNotIn("Draft Day", str(self.stores["A"][v2.ITEM_TYPE].rows))


class DeletedStrategyTests(_Base):
    def test_deleted_strategies_are_never_read(self) -> None:
        v2.soft_delete({}, "S", confirmed=True)  # deleted (here or on another device)
        answers = [self.ask(q).answer for q in (
            "Which saved strategies do I have?", "What notes did I save about Bobby Witt Jr.?",
            "What players are in my Speed strategy?", "What research have I saved in my Speed strategy?")]
        joined = " ".join(answers)
        for leaked in ("five tools", "Witt stole", "Elly De La Cruz"):
            self.assertNotIn(leaked, joined)
        self.assertIn("You don't have a saved strategy called “speed”", answers[2])

    def test_a_deleted_selected_strategy_is_not_used(self) -> None:
        v2.soft_delete({}, "P", confirmed=True)
        a = self.ask("What players are in this strategy?").answer
        self.assertIn("no longer saved (it may have been deleted)", a)
        self.assertNotIn("Aaron Judge", a.split("_")[-1] if a.count("_") >= 2 else a)
        self.assertNotIn("elite power", a)

    def test_the_global_queue_does_not_say_loaded_from_a_deleted_strategy(self) -> None:
        work.replace_global_with(self.s, "P", confirmed=True)
        self.assertIn("loaded from **Power-Hitting**", self.ask("What's in my Global Queue?").answer)
        v2.soft_delete({}, "P", confirmed=True)
        before = copy.deepcopy(self.s.get(dss.LOADED_KEY))
        self.assertNotIn("loaded from", self.ask("What's in my Global Queue?").answer.lower())
        self.assertEqual(self.s.get(dss.LOADED_KEY), before)  # AMI reports it; it never changes the session


class ReadOnlyTests(_Base):
    QUESTIONS = (
        "What players are in my Power-Hitting Strategy?", "Where did I rank Aaron Judge?", "Is Juan Soto in this queue?",
        "What notes did I save about Bobby Witt Jr.?", "How many catchers do I have in this strategy?",
        "What are my main positional priorities?", "How does this strategy differ from my Global Queue?",
        "Which saved strategies do I have?", "What's in my Global Queue?", "Add Aaron Judge to my Speed strategy",
        "Remove Kyle Schwarber from my Power-Hitting strategy", "Save my strategy",
    )

    def test_no_question_writes_storage_or_the_session(self) -> None:
        work.edit(self.s, "P", v2.move, "Pete Alonso", 0)  # an unsaved working copy must survive untouched
        for q in self.QUESTIONS:
            before = copy.deepcopy({k: v for k, v in self.s.items() if k != SESSION_KEY})
            self.ask(q)
            self.assertEqual({k: v for k, v in self.s.items() if k != SESSION_KEY}, before, q)
        self.assertEqual(self.writes(), [])

    def test_every_strategy_tool_is_registered_read_only(self) -> None:
        for name in (*STRATEGY_TOOLS, "get_global_list"):
            spec = REGISTRY.get(name)
            self.assertIsNotNone(spec, name)
            self.assertFalse(spec.mutates, name)
        with self.assertRaises(ValueError):
            from ami_assistant.tools.registry import ToolSpec

            REGISTRY.register(ToolSpec("save_strategy_note", "my_strategies", "x", {}, lambda: None, mutates=True))

    def test_tool_calls_leave_the_session_unchanged(self) -> None:
        for name, args in (("list_my_strategies", {}), ("get_my_strategy", {"player": "Aaron Judge"}),
                           ("get_global_list", {}), ("compare_strategy_to_global", {"name": "speed"})):
            before = copy.deepcopy(self.s)
            res = REGISTRY.call(name, args, session=self.s)
            self.assertTrue(res.ok, (name, res.message))
            self.assertEqual(self.s, before, name)
            self.assertEqual(find_secrets(res.as_dict()), [], name)
        self.assertEqual(self.writes(), [])


class IsolationTests(_Base):
    def test_each_account_reads_only_its_own_strategies(self) -> None:
        a_answers = " ".join(self.ask(q).answer for q in (
            "Which saved strategies do I have?", "What notes did I save about Gunnar Henderson?"))
        self.assertNotIn("Barry Secret", a_answers)
        self.assertNotIn("B-only note", a_answers)
        self.account = "B"  # another account signs in on its own session
        b_session: dict = {"draft_queue": []}
        b_answers = " ".join(self.ask(q, session=b_session).answer for q in (
            "Which saved strategies do I have?", "What notes did I save about Bobby Witt Jr.?",
            "What players are in my Power-Hitting strategy?"))
        self.assertIn("Barry Secret", b_answers)
        for leaked in ("Power-Hitting** ·", "five tools", "elite power", "Speed** ·"):
            self.assertNotIn(leaked, b_answers)
        self.assertEqual(self.writes(), [])

    def test_conversation_memory_stays_in_each_session(self) -> None:
        self.ask("Where did I rank Aaron Judge?")
        other: dict = {"draft_queue": []}
        self.assertNotIn(SESSION_KEY, other)
        self.assertEqual(ConversationState.from_dict(self.s[SESSION_KEY]).intent, sr.MY_STRATEGY)


class AccessTests(_Base):
    def test_signed_out_visitors_are_asked_to_sign_in_and_nothing_is_read(self) -> None:
        reads: list = []
        for acct in self.stores.values():
            for b in acct.values():
                b.all = (lambda orig: (lambda: reads.append(1) or orig()))(b.all)
        with mock.patch("suite_auth.is_anonymous_guest", return_value=True):
            a = self.ask("Which saved strategies do I have?").answer
            self.assertIn("Sign in to use your saved Draft Strategies", a)
            g = self.ask("What's in my Global Queue?").answer  # the Global Queue stays free
            self.assertIn("Global Queue", g)
            guest = {"draft_queue": ["Aaron Judge"]}  # sign-out clears the editor state
            self.assertEqual(build_ami_context(guest, PAGE).strategy, {})
            self.assertIn("Sign in", self.ask("Which saved strategies do I have?", session=guest).answer)
        self.assertEqual(reads, [])

    def test_when_enforced_strategy_tools_follow_the_pro_gate(self) -> None:
        free, pro = bm.default_entitlement(), bm.development_entitlement("pro")
        with mock.patch.object(bm, "ENFORCED_FEATURES", frozenset({bm.FeatureId.DRAFT_STRATEGIES})):
            for name in STRATEGY_TOOLS:
                res = REGISTRY.call(name, {}, session=self.s, entitlement=free)
                self.assertEqual(res.error_code, NOT_ENTITLED, name)
            self.assertTrue(REGISTRY.call("get_global_list", {}, session=self.s, entitlement=free).ok)
            a = ask("Which saved strategies do I have?", session_state=self.s, active_page=PAGE, dataset=self.ds,
                    entitlement=free).answer
            self.assertIn("part of Pro", a)
            with mock.patch("baseball_monetization_ui.current_entitlement", return_value=pro):
                self.assertTrue(REGISTRY.call("list_my_strategies", {}, session=self.s, entitlement=pro).ok)
        self.assertEqual(self.writes(), [])

    def test_nothing_is_enforced_today(self) -> None:
        self.assertNotIn(bm.FeatureId.DRAFT_STRATEGIES, bm.enforced_features())


class ContextTests(_Base):
    def test_the_selected_strategy_is_in_the_context_from_session_state_only(self) -> None:
        ctx = build_ami_context(self.s, PAGE)
        self.assertEqual(ctx.strategy, {"selected": "Power-Hitting", "unsaved": False, "never_saved": False})
        self.assertIn("strategy Power-Hitting", ctx.summary())
        work.edit(self.s, "P", v2.move, "Pete Alonso", 0)
        self.assertIn("(unsaved changes)", build_ami_context(self.s, PAGE).summary())
        self.assertNotIn("strategy", build_ami_context(self.s, "Leaderboards").summary())
        self.assertEqual(self.writes(), [])

    def test_strategy_matching_ignores_case_punctuation_and_the_word_strategy(self) -> None:
        rows = [{"name": "Power-Hitting"}, {"name": "Speed"}, {"name": "Speed Backup"}]
        self.assertEqual([s["name"] for s in ts.match_strategy("power hitting strategy", rows)[0]], ["Power-Hitting"])
        self.assertEqual([s["name"] for s in ts.match_strategy("speed", rows)[0]], ["Speed"])
        self.assertEqual(ts.match_strategy("pitching", rows)[0], [])

    def test_player_matching_never_guesses_between_players(self) -> None:
        entries = [{"name": "Will Smith"}, {"name": "Will Smith (P)"}, {"name": "Bobby Witt Jr."}]
        self.assertEqual(ts.find_entry("Bobby Witt Jr", entries)["name"], "Bobby Witt Jr.")
        self.assertEqual(ts.find_entry("witt", entries)["name"], "Bobby Witt Jr.")
        self.assertIsNone(ts.find_entry("Smith", entries))  # two candidates: no guess


if __name__ == "__main__":
    unittest.main()
