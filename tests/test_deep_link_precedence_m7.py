"""Mobile M7 — explicit ?active_page= deep-link precedence.

Root cause this pins (found in M7, reproduced from M5's report):
``_consume_scheduled_navigation()`` dropped a scheduled page whenever it equalled
the *current* page — but it resolved "current" with ``get_sidebar_page_value()``,
which coerces an **unset** ``active_page`` to ``PAGE_OPTIONS[0]``. On a fresh
session that made a genuine deep link to the default page look like a redundant
same-page schedule: it was dropped, ``active_page``/``main_sidebar_page`` were
never set, and the workspace restore further down then applied its stale saved
page. Deep links to any other page were unaffected, which is why the symptom
only ever appeared as "?active_page=Historical%20Explorer is ignored".

The guard itself is still wanted (it stops sticky same-page schedules left by
older restore paths from skipping sidebar align), so the fix only requires
``active_page`` to actually be set before the guard can fire.

These are fast unit tests against the real function with a fake ``st``; the
end-to-end AppTest coverage lives in ``test_deep_link_precedence_m7_e2e.py``.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace


def _app():
    import streamlit_app as app

    return app


class _FakeSt:
    """Minimal stand-in for the module-global ``st`` used by the nav helpers."""

    def __init__(self, session: dict):
        self.session_state = session


class ConsumeScheduledNavigationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = _app()
        self._real_st = self.app.st

    def tearDown(self) -> None:
        self.app.st = self._real_st

    def _consume(self, session: dict):
        self.app.st = _FakeSt(session)
        return self.app._consume_scheduled_navigation()

    # --- the bug this slice fixed ------------------------------------------------

    def test_fresh_session_deep_link_to_default_page_is_applied(self) -> None:
        """M7 regression: the exact failing case. A fresh session has no
        active_page; the schedule targets the default page; it must still apply."""
        default_page = self.app.PAGE_OPTIONS[0]
        session = {"_navigate_to_page": default_page}
        target = self._consume(session)
        self.assertEqual(target, default_page)
        self.assertEqual(session["active_page"], default_page)
        self.assertEqual(session[self.app.MAIN_SIDEBAR_PAGE_KEY], default_page)
        self.assertEqual(session["_skip_page_restore_for"], default_page)
        self.assertTrue(session["_suite_nav_consumed_this_run"])

    def test_fresh_session_deep_link_to_non_default_page_is_applied(self) -> None:
        """Always worked; kept so the fix can't regress the path that did."""
        target_page = "Leaderboards"
        self.assertIn(target_page, self.app.PAGE_OPTIONS)
        session = {"_navigate_to_page": target_page}
        self.assertEqual(self._consume(session), target_page)
        self.assertEqual(session["active_page"], target_page)

    def test_stale_saved_page_in_session_does_not_block_the_deep_link(self) -> None:
        """Restored workspace page differs from the deep-link target: deep link wins
        at this stage, and restore is told to skip that page."""
        session = {"active_page": "ML Predictions", "_navigate_to_page": "Leaderboards"}
        self.assertEqual(self._consume(session), "Leaderboards")
        self.assertEqual(session["active_page"], "Leaderboards")
        self.assertEqual(session["_skip_page_restore_for"], "Leaderboards")

    # --- the guard's original purpose, still intact -------------------------------

    def test_same_page_schedule_is_still_ignored_when_already_on_that_page(self) -> None:
        """The guard exists to drop sticky same-page schedules; with active_page
        genuinely set it must still fire, or sidebar align gets skipped."""
        session = {"active_page": "Leaderboards", "_navigate_to_page": "Leaderboards"}
        self.assertIsNone(self._consume(session))
        self.assertNotIn("_suite_nav_consumed_this_run", session)

    def test_same_page_guard_fires_for_the_default_page_too_once_set(self) -> None:
        default_page = self.app.PAGE_OPTIONS[0]
        session = {"active_page": default_page, "_navigate_to_page": default_page}
        self.assertIsNone(self._consume(session))

    # --- ordinary navigation / no-request fallback --------------------------------

    def test_no_schedule_leaves_state_untouched(self) -> None:
        """No deep link and no in-app navigation: nothing is consumed, so workspace
        restore stays the fallback that decides the page."""
        session = {"active_page": "ML Predictions"}
        self.assertIsNone(self._consume(session))
        self.assertEqual(session["active_page"], "ML Predictions")
        self.assertNotIn("_skip_page_restore_for", session)

    def test_ordinary_in_app_navigation_still_consumed(self) -> None:
        """A sidebar/quick-nav click schedules the same key; unchanged by the fix."""
        session = {"active_page": "Historical Explorer", "_navigate_to_page": "Trend Value"}
        self.assertEqual(self._consume(session), "Trend Value")
        self.assertEqual(session[self.app.MAIN_SIDEBAR_PAGE_KEY], "Trend Value")
        self.assertTrue(session["_suite_page_user_nav"])

    def test_invalid_schedule_value_falls_back_to_default_page(self) -> None:
        """Unknown page values are coerced by get_sidebar_page_value() — they must
        not raise and must not leave the app on a non-existent page."""
        session = {"active_page": "Leaderboards", "_navigate_to_page": "Not A Real Page"}
        target = self._consume(session)
        self.assertEqual(target, self.app.PAGE_OPTIONS[0])
        self.assertEqual(session["active_page"], self.app.PAGE_OPTIONS[0])

    # --- no oscillation -----------------------------------------------------------

    def test_schedule_is_consumed_once_and_not_resurrected(self) -> None:
        """_navigate_to_page is popped, so a second pass is a no-op — this is what
        keeps a deep link from re-firing every rerun (page oscillation)."""
        session = {"_navigate_to_page": "Leaderboards"}
        self.assertEqual(self._consume(session), "Leaderboards")
        self.assertNotIn("_navigate_to_page", session)
        # Second pass: already on the page, nothing scheduled -> no further writes.
        self.assertIsNone(self._consume(session))
        self.assertEqual(session["active_page"], "Leaderboards")


class DeepLinkHandlerWiringTests(unittest.TestCase):
    """The query-param handler that feeds _consume_scheduled_navigation."""

    def setUp(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        self.src = (root / "streamlit_app.py").read_text(encoding="utf-8")

    def test_handler_sets_schedule_skip_and_explicit_key(self) -> None:
        start = self.src.index('if not st.session_state.get("_qp_active_page_nav_consumed")')
        block = self.src[start:start + 1800]
        self.assertIn('st.session_state["_navigate_to_page"] = _qp_target', block)
        self.assertIn('st.session_state["_skip_page_restore_for"] = _qp_target', block)
        self.assertIn("EXPLICIT_PAGE_NAV_KEY", block)

    def test_same_page_guard_requires_a_set_active_page(self) -> None:
        start = self.src.index("def _consume_scheduled_navigation")
        block = self.src[start:start + 2000]
        self.assertIn("_current_raw", block)
        self.assertIn("if _current_raw and target == current:", block)


if __name__ == "__main__":
    unittest.main()
