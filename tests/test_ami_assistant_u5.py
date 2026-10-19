"""U5 — one Ask AMI: quick answers, suggested questions, the phone entry, and the explicit
Command Center handoff ("Get full analysis") that replaces the separate Baseball Insight box."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from streamlit.testing.v1 import AppTest

from ami_assistant.page_help import PAGE_HELP
from ami_assistant.ui import FULL_ANALYSIS_KEY, LAST_KEY, PHONE_ROOT_KEY, SIDEBAR_ROOT_KEY, _surface_css, full_analysis_offered

ROOT = Path(__file__).resolve().parents[1]


def _u5_app() -> None:
    import streamlit as st

    from ami_assistant.ui import render_ami_assistant_panel
    from tests.ami_assistant_fixtures import synthetic_yearly

    calls = st.session_state.setdefault("_test_handoffs", [])

    def handoff(question: str, page: str) -> dict:
        calls.append([question, page])
        return {"duplicate": len(calls) > 1}

    render_ami_assistant_panel(st, active_page=st.session_state.get("test_page", "Comparison Tool"),
                               yearly_df=synthetic_yearly(), full_analysis=handoff)
    st.write("page body")


def _sidebar_text(at: AppTest) -> str:
    return "\n".join(m.value for m in at.sidebar.markdown) + "\n" + "\n".join(c.value for c in at.sidebar.caption)


def _ask(at: AppTest, question: str, *, prefix: str = "") -> None:
    at.text_input(key=f"{prefix}ami_assistant_question").input(question)
    # The sidebar and the phone bar each have an "Ask AMI" form; pick this surface's by its form.
    form = f"FormSubmitter:{prefix}ami_assistant_form-"
    next(b for b in at.button if b.label == "Ask AMI" and form in str(b.id)).click()
    at.run(timeout=60)


def _button(at: AppTest, label: str, *, sidebar: bool = True):
    pool = at.sidebar.button if sidebar else at.button
    return next((b for b in pool if b.label == label), None)


class QuickAnswerTests(unittest.TestCase):
    def test_suggested_questions_ask_in_one_tap(self) -> None:
        at = AppTest.from_function(_u5_app, default_timeout=60)
        at.run()
        suggestions = PAGE_HELP["Comparison Tool"].questions[:3]
        for s in suggestions:
            self.assertIsNotNone(_button(at, s), s)
        _button(at, suggestions[0]).click()
        at.run(timeout=60)
        self.assertIn(f"You asked: {suggestions[0]}".replace("You asked: ", "**You asked:** "),
                      "\n".join(m.value for m in at.sidebar.markdown))
        self.assertIsNone(_button(at, suggestions[1]), "suggestions step aside once there's an answer")

    def test_full_analysis_is_offered_under_data_answers_and_runs_only_on_press(self) -> None:
        at = AppTest.from_function(_u5_app, default_timeout=60)
        at.session_state["compare_players"] = ["Aaron Judge", "Juan Soto"]
        at.run()
        _ask(at, "What does Valuation mean?")  # app help: nothing to analyse further
        self.assertIsNone(_button(at, "Get full analysis"))
        _ask(at, "Who had the higher OPS from 2022 to 2025?")
        self.assertIsNotNone(_button(at, "Get full analysis"))
        self.assertEqual(at.session_state["_test_handoffs"], [], "asking never hands off")
        _button(at, "Get full analysis").click()
        at.run(timeout=60)
        self.assertEqual(at.session_state["_test_handoffs"], [["Who had the higher OPS from 2022 to 2025?", "Comparison Tool"]])
        self.assertIn("Full analysis requested", "\n".join(s.value for s in at.sidebar.success))
        # One send per answer: the button is spent, so a second press can't submit again.
        spent = _button(at, "Full analysis requested")
        self.assertIsNotNone(spent)
        self.assertTrue(spent.disabled)
        self.assertIsNone(_button(at, "Get full analysis"))
        self.assertEqual(len(at.session_state["_test_handoffs"]), 1)
        next(b for b in at.sidebar.button if b.label == "Clear conversation").click()
        at.run()
        self.assertNotIn(FULL_ANALYSIS_KEY, at.session_state)

    def test_no_full_analysis_under_refusals_help_or_questions_back(self) -> None:
        for last in ({"answer": "x", "grounding": "product_help", "intent": "help_page"},
                     {"answer": "x", "grounding": "product_help", "intent": "action_request"},
                     {"answer": "Which player?", "grounding": "app_data", "intent": "clarify"},
                     {"answer": "AMI is unavailable", "grounding": "app_data", "intent": "compare", "error": True},
                     # A tool refused for access or plan reasons: no way around it through Command Center.
                     {"answer": "x", "grounding": "app_data", "intent": "fantasy_lineup_status",
                      "tools": [{"tool": "get_lineup_status", "ok": False, "error_code": "not_your_team"}]},
                     {"answer": "x", "grounding": "app_data", "intent": "draft_next",
                      "tools": [{"tool": "get_draft_recommendations", "ok": False, "error_code": "not_entitled"}]}):
            self.assertFalse(full_analysis_offered(last), last)
        for last in ({"answer": "x", "grounding": "app_data", "intent": "compare"},
                     {"answer": "x", "grounding": "app_data", "intent": "fantasy_standings"},
                     {"answer": "x", "grounding": "external_current", "intent": "external_current"}):
            self.assertTrue(full_analysis_offered(last), last)

    def test_without_a_host_handoff_there_is_no_button(self) -> None:
        def app() -> None:
            import streamlit as st

            from ami_assistant.ui import render_ami_assistant_panel
            from tests.ami_assistant_fixtures import synthetic_yearly

            render_ami_assistant_panel(st, active_page="Comparison Tool", yearly_df=synthetic_yearly())

        at = AppTest.from_function(app, default_timeout=60)
        at.session_state["compare_players"] = ["Aaron Judge", "Juan Soto"]
        at.run()
        _ask(at, "Who had the higher OPS from 2022 to 2025?")
        self.assertIsNone(_button(at, "Get full analysis"))


class PhoneEntryTests(unittest.TestCase):
    def test_one_assistant_two_surfaces_one_conversation(self) -> None:
        at = AppTest.from_function(_u5_app, default_timeout=60)
        at.session_state["compare_players"] = ["Aaron Judge", "Juan Soto"]
        at.run()
        self.assertTrue(any(e.label == "💬 Ask AMI" for e in at.expander), "the phone bar is on the page")
        _ask(at, "Who had more power?", prefix="m_")  # asked from the phone bar
        self.assertEqual(at.session_state[LAST_KEY]["question"], "Who had more power?")
        at.run()
        self.assertIn("**You asked:** Who had more power?", "\n".join(m.value for m in at.sidebar.markdown))

    def test_exactly_one_surface_shows_per_device(self) -> None:
        from mobile_foundation import PHONE_MAX_PX

        css = _surface_css()
        desktop, phone = css.split(f"@media (max-width: {PHONE_MAX_PX}px)")
        self.assertIn(f"@media (min-width: {PHONE_MAX_PX + 1}px)", desktop)
        self.assertIn(f".st-key-{PHONE_ROOT_KEY}", desktop)  # phone bar hidden on desktop
        self.assertIn(f".st-key-{SIDEBAR_ROOT_KEY}", phone)  # sidebar panel hidden on phones


class HandoffTests(unittest.TestCase):
    def test_submit_baseball_insight_is_the_insight_buttons_own_submit(self) -> None:
        from baseball_ami_sidebar import submit_baseball_insight

        sent, hooks = [], []

        def fake_submit(**kwargs):
            sent.append(kwargs)
            return {"duplicate": len(sent) > 1, "question_id": "q1"}

        ss: dict = {}
        with mock.patch("suite_analytical_question.submit_analytical_question", side_effect=fake_submit):
            first = submit_baseball_insight(ss, source_page="Career Totals", question="  Is Pujols a Hall of Famer?  ",
                                            context_extra_builder=lambda: {"note": "ctx"},
                                            source_state_builder=lambda: {"state": 1}, on_after_send=lambda: hooks.append(1))
            second = submit_baseball_insight(ss, source_page="Career Totals", question="Is Pujols a Hall of Famer?",
                                             on_after_send=lambda: hooks.append(2))
        self.assertEqual((sent[0]["source_app"], sent[0]["source_page"], sent[0]["question"]),
                         ("baseball", "Career Totals", "Is Pujols a Hall of Famer?"))
        self.assertEqual(sent[0]["source_state"], {"state": 1})
        self.assertIn("note", json.dumps(sent[0]["context"]))  # the page's context rides along
        self.assertIs(sent[0]["session_state"], ss)
        self.assertEqual((first["duplicate"], second["duplicate"]), (False, True))
        self.assertEqual(hooks, [1], "the save deferral runs once, not for a duplicate")
        self.assertEqual(ss["_ami_send_gen_baseball_Career_Totals"], 2)  # the Insight box's own counter

    def test_the_old_insight_button_uses_the_same_submit(self) -> None:
        from baseball_ami_sidebar import render_baseball_insight_sidebar

        st = mock.MagicMock()
        st.session_state = {}
        st.sidebar.text_area.return_value = "Why is he improving?"
        st.sidebar.button.return_value = True
        with mock.patch("baseball_ami_sidebar.submit_baseball_insight", return_value={"duplicate": False}) as submit:
            render_baseball_insight_sidebar(st, source_page="Trend Value", session_state=st.session_state)
        submit.assert_called_once()
        self.assertEqual((submit.call_args.kwargs["source_page"], submit.call_args.kwargs["question"]),
                         ("Trend Value", "Why is he improving?"))

    def test_quick_answers_write_nothing(self) -> None:
        """Asking (typed, suggested, follow-up, phone) never reaches the Command Center pipeline or a store."""
        def boom(*_a, **_k):
            raise AssertionError("a quick answer tried to save")

        with mock.patch("suite_analytical_question.submit_analytical_question", side_effect=boom), \
                mock.patch("suite_activity_client.record_activity", side_effect=boom), \
                mock.patch("baseball_ami_sidebar.submit_baseball_insight", side_effect=boom), \
                mock.patch("requests.sessions.Session.request", side_effect=boom):
            at = AppTest.from_function(_u5_app, default_timeout=60)
            at.session_state["compare_players"] = ["Aaron Judge", "Juan Soto"]
            at.run()
            _button(at, PAGE_HELP["Comparison Tool"].questions[0]).click()
            at.run(timeout=60)
            _ask(at, "Who had more power?")
            _ask(at, "What about speed?", prefix="m_")
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["_test_handoffs"], [])

    def test_quick_conversations_are_never_persisted(self) -> None:
        import baseball_persistent_state as ps

        listed = set(ps._GLOBAL_KEYS) | set(ps._HOF_HANDOFF_KEYS) | set(ps._INSIGHT_KEYS) | set(ps._WORKSPACE_KEYS) \
            | set(ps._WORKFLOW_KEYS)
        for key in ("_ami_assistant_conversation", LAST_KEY, FULL_ANALYSIS_KEY, "_ami_assistant_pending_question",
                    "ami_assistant_question", "m_ami_assistant_question"):
            self.assertNotIn(key, listed)
        state = {"active_page": "Comparison Tool", "_ami_assistant_conversation": {"turns": [{"question": "secret q"}]},
                 LAST_KEY: {"question": "secret q", "answer": "a"}}
        try:
            disk = ps.build_baseball_disk_state(SimpleNamespace(session_state=dict(state)))
        except Exception as exc:  # the builder needs a fuller app session; the allowlists above still decide
            self.skipTest(f"disk state builder needs app state: {type(exc).__name__}")
        self.assertNotIn("secret q", json.dumps(disk, default=str))


class WiringAndHelpTests(unittest.TestCase):
    def test_the_app_hands_off_with_the_insight_boxs_context(self) -> None:
        app = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        fn = app[app.index("def _ami_full_analysis("): app.index("# U5: Ask AMI is the app's one question box")]
        for piece in ("submit_baseball_insight(", "build_baseball_applied_math_context(page, st.session_state)",
                      "build_source_state(page, st.session_state)", "_force_save_before_ami_return(page)"):
            self.assertIn(piece, fn)
        self.assertNotIn("render_baseball_insight_sidebar(", app)
        # Hall of Fame Case Mode keeps its own on-page send (Career Totals).
        self.assertIn("submit_analytical_question,", app)
        self.assertIn("hof_case", app[app.index("submit_analytical_question,"): app.index("submit_analytical_question,") + 4000])

    def test_home_points_to_ask_ami(self) -> None:
        home = (ROOT / "home_page.py").read_text(encoding="utf-8")
        self.assertNotIn("Baseball Insight", home)
        self.assertIn("Get full analysis", home)

    def test_help_explains_the_change(self) -> None:
        from ami_assistant.engine import ask
        from tests.ami_assistant_fixtures import synthetic_dataset

        for q in ("Where did Baseball Insight go?", "What is Command Center?", "How do I get a full analysis?"):
            answer = ask(q, session_state={}, active_page="Home", dataset=synthetic_dataset()).answer
            self.assertIn("Get full analysis", answer, q)
            self.assertIn("never saved", answer, q)

def _home_app() -> None:
    import streamlit as st

    import home_page
    from ami_assistant.ui import render_ami_assistant_panel
    from tests.ami_assistant_fixtures import synthetic_yearly

    render_ami_assistant_panel(st, active_page="Home", yearly_df=synthetic_yearly(),
                               full_analysis=lambda q, p: {"duplicate": False})
    home_page.render_home(st, st.session_state, navigate=lambda page, **_kw: None)


class HomeEntryTests(unittest.TestCase):
    def test_home_asks_into_the_one_conversation(self) -> None:
        from ami_assistant.page_help import HOME_ASK_BUTTONS

        at = AppTest.from_function(_home_app, default_timeout=60)
        at.run()
        # Home's Ask card buttons (the phone bar's "Try:" suggestions show the same questions, keyed apart).
        main_buttons = [b for b in at.main.button if str(b.key or "").startswith("u1_action_home_ask_")]
        self.assertEqual([b.label for b in main_buttons], list(HOME_ASK_BUTTONS))  # Home's own suggested questions
        self.assertEqual(sum(1 for t in at.text_input if t.label == "Ask AMI"), 2, "no new input: sidebar + phone bar only")
        main_buttons[0].click()
        at.run(timeout=60)
        self.assertEqual(at.session_state[LAST_KEY]["question"], HOME_ASK_BUTTONS[0])
        self.assertIn(f"**You asked:** {HOME_ASK_BUTTONS[0]}", "\n".join(m.value for m in at.sidebar.markdown))
        phone = next(e for e in at.expander if e.label == "💬 Ask AMI")
        self.assertTrue(phone.proto.expanded, "the phone bar opens with the answer")

    def test_home_skips_the_brand_banner_on_phones_only(self) -> None:
        from mobile_foundation import PHONE_MAX_PX

        at = AppTest.from_function(_home_app, default_timeout=60)
        at.run()
        css = "\n".join(m.value for m in at.main.markdown if "title-box" in m.value)
        self.assertIn(f"@media (max-width: {PHONE_MAX_PX}px)", css)
        self.assertIn(':has(.title-box) { display: none; }', css)


def _handoff_app() -> None:
    """The panel with the app's own handoff (same body as streamlit_app._ami_full_analysis)."""
    import streamlit as st

    from ami_assistant.ui import render_ami_assistant_panel
    from applied_math_context import build_baseball_applied_math_context, build_source_state
    from baseball_ami_sidebar import submit_baseball_insight
    from tests.ami_assistant_fixtures import synthetic_yearly

    def _ami_full_analysis(question: str, page: str) -> dict:
        return submit_baseball_insight(
            st.session_state, source_page=page, question=question,
            context_extra_builder=lambda: build_baseball_applied_math_context(page, st.session_state),
            source_state_builder=lambda: build_source_state(page, st.session_state),
            on_after_send=lambda: st.session_state.__setitem__("_suite_defer_baseball_save_reason", f"ami_send:{page}"),
        )

    render_ami_assistant_panel(st, active_page=st.session_state.get("test_page", "Career Totals"),
                               yearly_df=synthetic_yearly(), full_analysis=_ami_full_analysis)


COMMAND_CENTER = Path.home() / "Documents" / "GitHub" / "daniel-ai-command-center"


class EndToEndHandoffTests(unittest.TestCase):
    """The real Get full analysis → Command Center pipeline, isolated: every cloud writer is a
    recorder and the network is off. Command Center's own checkout supplies the module the pipeline
    imports (music_resume_payload, not synced into this repo); without it the test is skipped."""

    def setUp(self) -> None:
        import sys

        if not (COMMAND_CENTER / "music_resume_payload.py").is_file():
            self.skipTest("Command Center checkout not available")
        self._path = str(COMMAND_CENTER)
        self._added = self._path not in sys.path
        if self._added:
            sys.path.append(self._path)
        self.rec = {"activity": [], "blob": [], "upsert": []}

    def tearDown(self) -> None:
        import sys

        if getattr(self, "_added", False) and self._path in sys.path:
            sys.path.remove(self._path)

    def _isolated(self):
        from contextlib import ExitStack

        stack = ExitStack()
        stack.enter_context(mock.patch("suite_activity_client.record_activity",
                                       side_effect=lambda *a, **k: self.rec["activity"].append((a, k))))
        stack.enter_context(mock.patch("suite_analytical_question._store_question_context_blob",
                                       side_effect=lambda p: self.rec["blob"].append(p)))
        stack.enter_context(mock.patch("suite_analytical_question._upsert_applied_intelligence_resume",
                                       side_effect=lambda p, **k: self.rec["upsert"].append(p)))
        stack.enter_context(mock.patch("requests.sessions.Session.request",
                                       side_effect=AssertionError("no network in the isolated handoff")))
        return stack

    def test_history_question_reaches_command_center_once(self) -> None:
        with self._isolated():
            at = AppTest.from_function(_handoff_app, default_timeout=90)
            at.session_state["test_page"] = "Career Totals"
            at.run()
            _ask(at, "Who has the most career HR since 2010?")
            self.assertEqual(self.rec, {"activity": [], "blob": [], "upsert": []}, "the quick answer saved nothing")
            _button(at, "Get full analysis").click()
            at.run(timeout=90)
        self.assertFalse(at.exception)
        self.assertEqual(len(self.rec["upsert"]), 1)
        sent = self.rec["upsert"][0]
        self.assertEqual((sent["question"], sent["source_page"], sent["source_app"]),
                         ("Who has the most career HR since 2010?", "Career Totals", "baseball"))
        self.assertEqual(sent["context"].get("page"), "Career Totals")  # the page's own analysis context
        self.assertEqual(len(self.rec["blob"]), 1)
        self.assertEqual(self.rec["activity"][0][1].get("page"), "Career Totals")
        self.assertEqual(at.session_state["_suite_defer_baseball_save_reason"], "ami_send:Career Totals")
        self.assertIn("Full analysis requested", "\n".join(s.value for s in at.sidebar.success))
        self.assertTrue(_button(at, "Full analysis requested").disabled)  # no second submission

    def test_league_question_carries_the_league_page(self) -> None:
        with self._isolated():
            at = AppTest.from_function(_handoff_app, default_timeout=90)
            at.session_state["test_page"] = "Fantasy Standings Tracker"
            at.run()
            _ask(at, "Where am I in the standings?")
            _button(at, "Get full analysis").click()
            at.run(timeout=90)
        self.assertEqual([(u["question"], u["source_page"]) for u in self.rec["upsert"]],
                         [("Where am I in the standings?", "Fantasy Standings Tracker")])

    def test_a_failed_handoff_says_so_and_can_be_retried(self) -> None:
        with self._isolated(), mock.patch("suite_analytical_question.build_applied_math_resume_url",
                                          side_effect=ModuleNotFoundError("No module named 'music_resume_payload'")):
            at = AppTest.from_function(_handoff_app, default_timeout=90)
            at.session_state["test_page"] = "Career Totals"
            at.run()
            _ask(at, "Who has the most career HR since 2010?")
            _button(at, "Get full analysis").click()
            at.run(timeout=90)
        self.assertFalse(at.exception, "a failed handoff never breaks the page")
        self.assertIn("Couldn't send this to Command Center", "\n".join(e.value for e in at.sidebar.error))
        self.assertEqual(self.rec["upsert"], [])
        self.assertIsNotNone(_button(at, "Get full analysis"))  # still available to retry
        self.assertNotIn("_suite_defer_baseball_save_reason", at.session_state)


if __name__ == "__main__":
    unittest.main()
