"""An apply later in a session keeps the page the user is on (QA 2026-11-05).

Creating or joining a Shared Draft room saves, the save merges with a newer cloud copy (Stage B
merge-on-stale) and the merged state is re-applied on the next run. That copy's saved page was
"Home", so the user landed on Home instead of the room's lobby. Only the first restore of a session
returns to the saved page.
"""

from __future__ import annotations

import unittest

import tests.test_hosted_autosave_reliability as h


def _page_applying(harness: h.Harness):
    """apply_state as the Baseball app does it: the blob's saved page becomes the session's page."""
    def apply(st, state):
        harness.applied.append(dict(state))
        if state.get("active_page"):
            st.session_state["active_page"] = state["active_page"]
            st.session_state["main_sidebar_page"] = state["active_page"]
    return apply


class ReapplyKeepsPageTests(unittest.TestCase):
    def test_first_restore_returns_to_the_saved_page(self) -> None:
        store = h.FakeStore(blob={"active_page": "Fantasy Standings Tracker", "league": "L"})
        with h.Harness(store) as harness:
            h.sup.sync_workspace_protocol(harness.st, h.APP, apply_state=_page_applying(harness))
            self.assertEqual(harness.session.get("active_page"), "Fantasy Standings Tracker")

    def test_a_later_apply_keeps_the_page_the_user_is_on(self) -> None:
        store = h.FakeStore(blob={"active_page": "Home", "league": "L"})
        with h.Harness(store) as harness:
            h.sup.sync_workspace_protocol(harness.st, h.APP, apply_state=_page_applying(harness))
            self.assertEqual(harness.session["active_page"], "Home")  # first restore
            harness.session["active_page"] = "Live Draft Room"     # the user went to the room
            harness.session["main_sidebar_page"] = "Live Draft Room"
            harness.end_run()
            store.blob = {"active_page": "Home", "league": "L", "room": "MDFZ2X"}  # newer cloud copy
            store.updated_at = "2026-10-17T10:00:00+00:00"
            h.sup.sync_workspace_protocol(harness.st, h.APP, apply_state=_page_applying(harness))
            self.assertGreaterEqual(len(harness.applied), 2)       # the newer copy was applied
            self.assertEqual(harness.session["active_page"], "Live Draft Room")
            self.assertEqual(harness.session["main_sidebar_page"], "Live Draft Room")


if __name__ == "__main__":
    unittest.main()
