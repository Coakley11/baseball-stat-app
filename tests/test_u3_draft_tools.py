"""U3A: each draft tool says what it is for, links to the others, and Home offers the four ways
into drafting without a separate page. Live Draft shows the switcher only in its intro."""

import re
import unittest
from pathlib import Path

import draft_tools
import home_page

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")


class FakeCol:
    def __init__(self, log):
        self.log = log

    def button(self, label, **kw):
        self.log.append((label, kw))
        return False


class FakeSt:
    def __init__(self):
        self.buttons = []
        self.markdowns = []

    def markdown(self, text, **_kw):
        self.markdowns.append(text)

    def columns(self, n):
        return [FakeCol(self.buttons) for _ in range(n)]

    def container(self, **_kw):
        import contextlib

        return contextlib.nullcontext()


class DraftToolTests(unittest.TestCase):
    def test_every_tool_has_a_distinct_purpose(self):
        pages = [p for p, *_ in draft_tools.DRAFT_TOOLS]
        self.assertEqual(pages, ["Live Draft Room", "Draft Room Simulator", "Draft Assistant Simulator",
                                 "Draft Lab / Simulation", "Saved Draft Library"])
        purposes = [draft_tools.purpose(p) for p in pages]
        self.assertTrue(all(purposes))
        self.assertEqual(len(set(purposes)), len(purposes))

    def test_switcher_links_the_other_four_and_only_navigates(self):
        st = FakeSt()
        calls = []
        draft_tools.render_draft_tool_nav(st, "Draft Room Simulator", lambda page: (lambda: calls.append(page)))
        self.assertEqual(len(st.buttons), 4)
        labels = [label for label, _kw in st.buttons]
        self.assertNotIn("🧾 Draft Room Simulator", labels)
        for _label, kw in st.buttons:
            self.assertTrue(kw["key"].startswith("u3dt_"), "button keys must not use a persisted page prefix")
            self.assertEqual(kw["type"], "tertiary")
            kw["on_click"]()
        self.assertEqual(calls, ["Live Draft Room", "Draft Assistant Simulator", "Draft Lab / Simulation", "Saved Draft Library"])

    def test_each_draft_page_uses_shared_purpose_and_switcher(self):
        for page in ('"Draft Assistant Simulator"', '"Draft Room Simulator"', "DRAFT_LAB_PAGE", '"Saved Draft Library"'):
            start = APP.index(f"elif active_page == {page}:")
            body = APP[start:start + 2500]
            with self.subTest(page=page):
                self.assertIn("draft_tools.purpose(active_page)", body)
                self.assertIn("draft_tools.render_draft_tool_nav(st, active_page, _u1_nav_cb)", body)

    def test_live_draft_switcher_only_in_intro(self):
        start = APP.index('elif active_page == "Live Draft Room":')
        body = APP[start:APP.index("elif active_page ==", start + 10)]
        self.assertEqual(body.count("draft_tools.render_draft_tool_nav("), 1)
        intro = body[body.index("if _show_ldr_guide:"):body.index("else:", body.index("if _show_ldr_guide:"))]
        self.assertIn("draft_tools.render_draft_tool_nav(", intro)

    def test_home_draft_landing(self):
        self.assertEqual([label for label, _p in draft_tools.HOME_DRAFT_CHOICES],
                         ["Run a Live Draft", "Simulate a Draft", "Analyze Draft Strategy", "Open Saved Drafts"])
        st = FakeSt()
        went = []
        home_page._render_draft_choices(st, lambda page: (lambda: went.append(page)))
        for _label, kw in st.buttons:
            kw["on_click"]()
        self.assertEqual(went, [p for _l, p in draft_tools.HOME_DRAFT_CHOICES])
        self.assertTrue(any(t[1] == home_page.DRAFT_TASK for t in home_page.TASKS))

    def test_guides_no_longer_say_multi_user_is_missing(self):
        self.assertNotIn("before multi-user sync is added", APP)
        self.assertNotIn('st.subheader("Live draft board")', APP, "Draft Room Simulator's board is not the Live Draft Room")


if __name__ == "__main__":
    unittest.main()
