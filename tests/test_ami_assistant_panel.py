"""The Ask AMI sidebar panel: question → answer, context line, follow-up, clear, error-safe."""

from __future__ import annotations

import unittest

from streamlit.testing.v1 import AppTest


def _panel_app() -> None:
    import streamlit as st

    from ami_assistant.ui import render_ami_assistant_panel
    from tests.ami_assistant_fixtures import synthetic_yearly

    render_ami_assistant_panel(st, active_page=st.session_state.get("test_page", "Comparison Tool"), yearly_df=synthetic_yearly())


def _broken_app() -> None:
    import streamlit as st

    from ami_assistant.ui import render_ami_assistant_panel

    st.session_state["_ami_assistant_last"] = "not a dict"
    render_ami_assistant_panel(st, active_page="Comparison Tool", yearly_df=object())
    st.write("page still renders")


def _sidebar_text(at: AppTest) -> str:
    return "\n".join(m.value for m in at.sidebar.markdown) + "\n" + "\n".join(c.value for c in at.sidebar.caption)


class PanelTests(unittest.TestCase):
    def ask(self, at: AppTest, question: str) -> None:
        at.sidebar.text_input(key="ami_assistant_question").input(question)
        next(b for b in at.sidebar.button if b.label == "Ask AMI").click()
        at.run(timeout=60)

    def test_question_answer_context_and_follow_up(self) -> None:
        at = AppTest.from_function(_panel_app, default_timeout=60)
        at.session_state["compare_players"] = ["Aaron Judge", "Juan Soto"]
        at.run()
        self.assertIn("Looking at: Compare Players · Aaron Judge, Juan Soto", _sidebar_text(at))  # U2 label
        self.ask(at, "Who had the higher OPS from 2022 to 2025?")
        text = _sidebar_text(at)
        self.assertIn("You asked:", text)
        self.assertIn("Aaron Judge vs Juan Soto", text)
        self.assertIn("App data", text)
        self.ask(at, "Who had more power?")
        self.assertIn("home runs", _sidebar_text(at))
        self.assertTrue(any(e.label == "Earlier in this conversation" for e in at.sidebar.expander))
        next(b for b in at.sidebar.button if b.label == "Clear conversation").click()
        at.run()
        self.assertNotIn("You asked:", _sidebar_text(at))
        self.assertNotIn("_ami_assistant_conversation", at.session_state)

    def test_empty_question_warns(self) -> None:
        at = AppTest.from_function(_panel_app, default_timeout=60)
        at.run()
        next(b for b in at.sidebar.button if b.label == "Ask AMI").click()
        at.run()
        self.assertTrue(any("Type a question" in w.value for w in at.sidebar.warning))

    def test_a_panel_failure_never_breaks_the_page(self) -> None:
        at = AppTest.from_function(_broken_app, default_timeout=60)
        at.run()
        self.assertFalse(at.exception)
        self.assertTrue(any("page still renders" in m.value for m in at.markdown))


if __name__ == "__main__":
    unittest.main()
