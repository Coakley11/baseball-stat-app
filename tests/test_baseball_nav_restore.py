"""Tests for workspace restore not clobbering scheduled page navigation."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from baseball_persistent_state import EXPLICIT_PAGE_NAV_KEY, apply_baseball_disk_state


class BaseballNavRestoreTests(unittest.TestCase):
    def test_apply_preserves_scheduled_navigation_target(self) -> None:
        ss = {
            "active_page": "Waiver Wire / Add-Drop Center",
            "main_sidebar_page": "Waiver Wire / Add-Drop Center",
            "_navigate_to_page": "Saved Draft Library",
            "_skip_page_restore_for": "Saved Draft Library",
            "_suite_page_user_nav": True,
        }
        st_obj = SimpleNamespace(session_state=ss)
        apply_baseball_disk_state(
            st_obj,
            {"active_page": "Waiver Wire / Add-Drop Center"},
        )
        self.assertEqual(ss["active_page"], "Saved Draft Library")
        self.assertEqual(ss["_navigate_to_page"], "Saved Draft Library")
        self.assertEqual(ss.get("_suite_page_overwrite_source"), "scheduled_navigation_preserved")

    def test_apply_honors_consumed_navigation_target(self) -> None:
        ss = {
            "active_page": "Waiver Wire / Add-Drop Center",
            "main_sidebar_page": "Waiver Wire / Add-Drop Center",
            "_suite_nav_consumed_target": "Saved Draft Library",
            "_suite_nav_consumed_this_run": True,
        }
        st_obj = SimpleNamespace(session_state=ss)
        apply_baseball_disk_state(
            st_obj,
            {"active_page": "Waiver Wire / Add-Drop Center"},
        )
        self.assertEqual(ss["active_page"], "Saved Draft Library")
        self.assertEqual(ss["main_sidebar_page"], "Saved Draft Library")
        self.assertEqual(ss.get("_suite_page_overwrite_source"), "nav_consumed_preserved")

    def test_apply_clears_sticky_same_page_navigate(self) -> None:
        ss = {
            "active_page": "Historical Explorer",
            "main_sidebar_page": "Historical Explorer",
            "_navigate_to_page": "Historical Explorer",
        }
        st_obj = SimpleNamespace(session_state=ss)
        apply_baseball_disk_state(
            st_obj,
            {"active_page": "Historical Explorer"},
        )
        self.assertEqual(ss["active_page"], "Historical Explorer")
        self.assertNotIn("_navigate_to_page", ss)

    def test_sidebar_nav_beats_stale_skip_for_historical_explorer(self) -> None:
        """Daniel-style workspace: durable skip must not override a sidebar hop."""
        ss = {
            "active_page": "Live Draft Room",
            "main_sidebar_page": "Live Draft Room",
            "_suite_page_user_nav": True,
            "_suite_user_owned_page": "Live Draft Room",
            "active_page_source": "user_sidebar",
            # Leftover skip from an old full_session / prior restore.
            "_skip_page_restore_for": "Historical Explorer",
            "_suite_last_persisted_page": "Historical Explorer",
        }
        st_obj = SimpleNamespace(session_state=ss)
        apply_baseball_disk_state(
            st_obj,
            {
                "active_page": "Historical Explorer",
                "_skip_page_restore_for": "Historical Explorer",
            },
        )
        self.assertEqual(ss["active_page"], "Live Draft Room")
        self.assertEqual(ss["main_sidebar_page"], "Live Draft Room")
        self.assertEqual(ss.get("_suite_page_overwrite_source"), "user_page_preserved")
        self.assertNotEqual(ss.get("_skip_page_restore_for"), "Historical Explorer")

    def test_explicit_deep_link_beats_stale_owned_page(self) -> None:
        """M2 regression: ?active_page=... must win over a stale owned/blob restore.

        Reproduces the bug M1 flagged: an explicit deep link (already consumed this
        rerun by _consume_scheduled_navigation, hence active_page/_suite_nav_consumed
        already reflect it) was getting silently overridden by an unrelated
        owned_page left over from earlier in-session navigation, because any
        consumed nav — deep link or ordinary sidebar click — sets
        `_suite_page_user_nav=True`, which alone was enough to promote a stale
        owned_page to `preferred_page` (top precedence) regardless of the deep link.
        """
        ss = {
            "active_page": "Live Draft Room",
            "main_sidebar_page": "Live Draft Room",
            "_skip_page_restore_for": "Live Draft Room",
            "_suite_nav_consumed_target": "Live Draft Room",
            "_suite_nav_consumed_this_run": True,
            "_suite_page_user_nav": True,
            "_suite_user_owned_page": "Fantasy Standings Tracker",
            "_suite_last_persisted_page": "Fantasy Standings Tracker",
            EXPLICIT_PAGE_NAV_KEY: "Live Draft Room",
        }
        st_obj = SimpleNamespace(session_state=ss)
        apply_baseball_disk_state(st_obj, {"active_page": "Fantasy Standings Tracker"})
        self.assertEqual(ss["active_page"], "Live Draft Room")
        # Single-rerun scoped: the flag must not linger for a later, unrelated rerun.
        self.assertNotIn(EXPLICIT_PAGE_NAV_KEY, ss)

    def test_explicit_deep_link_wins_in_isolation(self) -> None:
        """Same as above with no consumed-target cross-check in play, to pin the
        dedicated overwrite_source label used for diagnostics."""
        ss = {
            "active_page": "Live Draft Room",
            "main_sidebar_page": "Live Draft Room",
            "_suite_user_owned_page": "Fantasy Standings Tracker",
            "_suite_last_persisted_page": "Fantasy Standings Tracker",
            EXPLICIT_PAGE_NAV_KEY: "Live Draft Room",
        }
        st_obj = SimpleNamespace(session_state=ss)
        apply_baseball_disk_state(st_obj, {"active_page": "Fantasy Standings Tracker"})
        self.assertEqual(ss["active_page"], "Live Draft Room")
        self.assertEqual(ss.get("_suite_page_overwrite_source"), "explicit_deep_link_preserved")

    def test_normal_restore_unaffected_without_explicit_nav(self) -> None:
        """No deep link this rerun: ordinary owned_page restore behaves exactly as
        before the M2 fix — the explicit-nav key must never change this path."""
        ss = {
            "active_page": "Live Draft Room",
            "main_sidebar_page": "Live Draft Room",
            "_suite_page_user_nav": True,
            "_suite_user_owned_page": "Fantasy Standings Tracker",
            "_suite_last_persisted_page": "Fantasy Standings Tracker",
        }
        st_obj = SimpleNamespace(session_state=ss)
        apply_baseball_disk_state(st_obj, {"active_page": "Fantasy Standings Tracker"})
        self.assertEqual(ss["active_page"], "Fantasy Standings Tracker")
        self.assertEqual(ss.get("_suite_page_overwrite_source"), "user_page_preserved")

    def test_stale_explicit_nav_key_ignored_after_page_moved_on(self) -> None:
        """A deep-link flag left over from a rerun where this function never ran
        (warm_skip) must not force-navigate once active_page has since changed —
        it is popped either way so it can never resurface on a later rerun."""
        ss = {
            "active_page": "Career Totals",
            "main_sidebar_page": "Career Totals",
            "_suite_page_user_nav": True,
            "_suite_user_owned_page": "Career Totals",
            "_suite_last_persisted_page": "Career Totals",
            EXPLICIT_PAGE_NAV_KEY: "Live Draft Room",
        }
        st_obj = SimpleNamespace(session_state=ss)
        apply_baseball_disk_state(st_obj, {"active_page": "Career Totals"})
        self.assertEqual(ss["active_page"], "Career Totals")
        self.assertNotIn(EXPLICIT_PAGE_NAV_KEY, ss)


class DeepLinkPageValueNormalizationTests(unittest.TestCase):
    """Invalid/unknown ?active_page= values must fail safely to the existing
    default page rather than raising or leaving navigation in a broken state."""

    def test_unknown_query_value_normalizes_to_default_page(self) -> None:
        import streamlit_app as app

        self.assertEqual(app.get_sidebar_page_value("Not A Real Page"), "Historical Explorer")
        self.assertEqual(app.get_sidebar_page_value(""), "Historical Explorer")
        self.assertEqual(app.get_sidebar_page_value(None), "Historical Explorer")

    def test_known_query_value_round_trips(self) -> None:
        import streamlit_app as app

        self.assertEqual(app.get_sidebar_page_value("Live Draft Room"), "Live Draft Room")
        # Sidebar display label (emoji-prefixed) must also resolve to its page key.
        self.assertEqual(
            app.get_sidebar_page_value(app.page_option_label("Live Draft Room")),
            "Live Draft Room",
        )


if __name__ == "__main__":
    unittest.main()
