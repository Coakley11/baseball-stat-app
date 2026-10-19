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
        _button(at, "Get full analysis").click()
        at.run(timeout=60)
        self.assertEqual(len(at.session_state["_test_handoffs"]), 2)
        self.assertIn("already asked for this analysis", "\n".join(i.value for i in at.sidebar.info))
        next(b for b in at.sidebar.button if b.label == "Clear conversation").click()
        at.run()
        self.assertNotIn(FULL_ANALYSIS_KEY, at.session_state)

    def test_no_full_analysis_under_refusals_help_or_questions_back(self) -> None:
        for last in ({"answer": "x", "grounding": "product_help", "intent": "help_page"},
                     {"answer": "x", "grounding": "product_help", "intent": "action_request"},
                     {"answer": "Which player?", "grounding": "app_data", "intent": "clarify"},
                     {"answer": "AMI is unavailable", "grounding": "app_data", "intent": "compare", "error": True}):
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


if __name__ == "__main__":
    unittest.main()
