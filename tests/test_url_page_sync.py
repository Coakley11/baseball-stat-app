"""Address bar follows the page shown; Back/Forward walk visited pages without loops."""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import patch

import url_page_sync as ups

ROOT = Path(__file__).resolve().parents[1]
PAGES = frozenset({"Historical Explorer", "Leaderboards", "Valuation", "Live Draft Room"})


def _normalize(raw: str) -> str:
    return {"🏆 Leaderboards": "Leaderboards"}.get(raw, raw)


def _target(session, current):
    return ups.history_navigation_target(session, current_page=current, valid_pages=PAGES, normalize=_normalize)


class FakeQueryParams(dict):
    def __init__(self):
        super().__init__()
        self.writes = []

    def __setitem__(self, key, value):
        self.writes.append((key, value))
        super().__setitem__(key, value)


class FakeSt:
    def __init__(self):
        self.session_state = {}
        self.query_params = FakeQueryParams()


def _run(st, page):
    with patch("url_page_sync_component.mount_url_page_sync") as mount:
        mode = ups.sync_address_bar(st, page)
    mount.assert_called_once_with(page, mode=mode, key=ups.EVENT_KEY)
    return mode


class AddressBarModeTests(unittest.TestCase):
    def test_first_run_replaces_then_navigation_pushes_once(self):
        st = FakeSt()
        self.assertEqual(_run(st, "Historical Explorer"), ups.MODE_REPLACE)
        self.assertEqual(st.query_params.writes, [])  # no history entry for the landing page
        self.assertEqual(_run(st, "Historical Explorer"), ups.MODE_NONE)
        self.assertEqual(_run(st, "Leaderboards"), ups.MODE_PUSH)
        self.assertEqual(st.query_params.writes, [("active_page", "Leaderboards")])
        self.assertEqual(_run(st, "Leaderboards"), ups.MODE_NONE)  # reruns on a page add nothing
        self.assertEqual(len(st.query_params.writes), 1)

    def test_back_navigates_without_pushing(self):
        st = FakeSt()
        for page in ("Historical Explorer", "Leaderboards", "Valuation"):
            _run(st, page)
        st.session_state[ups.EVENT_KEY] = {"page": "Leaderboards", "seq": "1"}
        self.assertEqual(_target(st.session_state, "Valuation"), "Leaderboards")
        writes = len(st.query_params.writes)
        self.assertEqual(_run(st, "Leaderboards"), ups.MODE_NONE)  # bar already shows it — Forward kept
        self.assertEqual(len(st.query_params.writes), writes)

    def test_each_popstate_is_handled_once(self):
        session = {ups.EVENT_KEY: {"page": "Leaderboards", "seq": "7"}}
        self.assertEqual(_target(session, "Valuation"), "Leaderboards")
        self.assertIsNone(_target(session, "Valuation"))  # same event on later reruns: no loop
        session[ups.EVENT_KEY] = {"page": "Valuation", "seq": "8"}
        self.assertEqual(_target(session, "Leaderboards"), "Valuation")

    def test_popstate_to_the_page_already_shown_does_nothing(self):
        session = {ups.EVENT_KEY: {"page": "Valuation", "seq": "1"}}
        self.assertIsNone(_target(session, "Valuation"))
        self.assertEqual(session[ups.BAR_PAGE_KEY], "Valuation")

    def test_unknown_or_missing_pages_are_ignored(self):
        for page in ("", "No Such Page", None):
            session = {ups.EVENT_KEY: {"page": page, "seq": f"x{page}"}}
            self.assertIsNone(_target(session, "Valuation"))
            self.assertNotIn(ups.BAR_PAGE_KEY, session)
        self.assertIsNone(_target({ups.EVENT_KEY: "garbage"}, "Valuation"))
        self.assertIsNone(_target({}, "Valuation"))

    def test_labels_are_normalized(self):
        session = {ups.EVENT_KEY: {"page": "🏆 Leaderboards", "seq": "1"}}
        self.assertEqual(_target(session, "Valuation"), "Leaderboards")

    def test_failed_push_falls_back_to_replace(self):
        st = FakeSt()
        _run(st, "Historical Explorer")

        class Boom(dict):
            def __setitem__(self, k, v):
                raise RuntimeError("no query params")

        st.query_params = Boom()
        self.assertEqual(_run(st, "Valuation"), ups.MODE_REPLACE)


class WiringTests(unittest.TestCase):
    def test_app_wires_history_and_sync(self):
        src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
        self.assertIn("history_navigation_target(", src)
        self.assertRegex(src, re.compile(r'if _history_nav_target:\s+#[^\n]*\n\s+st.session_state\["_navigate_to_page"\] = _history_nav_target'))
        self.assertIn('st.session_state["_skip_page_restore_for"] = _history_nav_target', src)
        self.assertIn("st.session_state[EXPLICIT_PAGE_NAV_KEY] = _history_nav_target", src)
        # Back/Forward must not pre-set active_page (the scheduled nav would be ignored as
        # same-page and sidebar alignment would snap back) — Live Draft Room included.
        block = src[src.index("if _history_nav_target:"):src.index("_consumed_nav_target = _consume_scheduled_navigation()")]
        self.assertNotIn('st.session_state["active_page"] =', block)
        # Sync runs on the requested page, before the entitlement/paywall stand-ins replace it.
        sync_at = src.index("sync_address_bar(st, active_page)")
        self.assertLess(sync_at, src.index('active_page = "__ENTITLEMENT_LOADING__"'))
        # The deep link is read on a session's first run only, even when that URL had no page:
        # later runs see the page this session pushed, not a link to follow.
        deep = src.index('if not st.session_state.get("_qp_active_page_nav_consumed")')
        latch = src.index('st.session_state["_qp_active_page_nav_consumed"] = True\n# Browser Back/Forward')
        self.assertLess(deep, latch)
        self.assertLess(latch, src.index("_consumed_nav_target = _consume_scheduled_navigation()"))
        # Back/Forward is handled after the one-time deep link and before scheduled navigation is consumed.
        self.assertLess(src.index('st.session_state["_qp_active_page_nav_consumed"] = True'), src.index("history_navigation_target("))
        self.assertLess(src.index("history_navigation_target("), src.index("_consumed_nav_target = _consume_scheduled_navigation()"))

    def test_component_frontend_never_pushes(self):
        html = (ROOT / "url_page_sync_component" / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn("replaceState", html)
        self.assertNotIn("pushState(", html)
        self.assertIn('addEventListener("popstate"', html)


if __name__ == "__main__":
    unittest.main()
