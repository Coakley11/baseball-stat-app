"""A signed-out guest's work never carries into the account that signs in (D4J review 2026-11-08).

Reproduced on the QA app: a guest added Aaron Judge and Shohei Ohtani, signed in as qa_barry, and
Barry's saved queue (Matt Olson, Pete Alonso) was replaced by the guest's two players, in the
session and then in his saved workspace. The guest's queue edits kept their "unsaved" markers
through sign-in, so the restore skipped the account's queue and the next save wrote the guest's.
"""

from __future__ import annotations

import types
import unittest
from unittest.mock import MagicMock, patch

import baseball_persistent_state  # noqa: F401  registers the account-workspace clearer, as the app does

GUEST_QUEUE = ["Aaron Judge", "Shohei Ohtani"]
ACCOUNT_QUEUE = ["Matt Olson", "Pete Alonso"]


def _guest_session() -> dict:
    return {
        "active_page": "Draft Strategy Assistant",
        "main_sidebar_page": "Draft Strategy Assistant",
        "draft_queue": list(GUEST_QUEUE),
        "draft_state": {"queue": list(GUEST_QUEUE)},
        "_live_draft_queue_last_good": list(GUEST_QUEUE),
        "draft_state_dirty": True,
        "_draft_workflow_pending_sync": True,
        "_draft_queue_persist_dirty": True,
        "_draft_queue_persist_dirty_ts": 1.0,
        "draft_queue_plan": {"notes": {"aaron judge": "guest note"}, "pins": [], "moves": []},
        "draft_strategy_approach": "roster_aware",
        "draft_queue_mode": "adaptive",
        "watchlist_favorites": ["Juan Soto"],
        "page_filter_state": {"Draft Workflow": {"queue": list(GUEST_QUEUE)}},
    }


def _sign_in(session: dict, uid: str = "auth-barry") -> None:
    from suite_auth import _persist_auth_session

    user = MagicMock()
    user.id = uid
    user.email = "qa@example.com"
    user.user_metadata = {}
    with patch("suite_auth.is_auth_enabled", return_value=True), \
            patch("suite_auth._apply_authenticated_user") as apply_user, \
            patch("suite_storage_supabase.ensure_user_row", return_value="suite-uuid"), \
            patch("suite_workspace_registry.ensure_owned_workspace_for_session"), \
            patch("suite_auth.enforce_workspace_ownership"), \
            patch("suite_user.reset_account_cache"):
        apply_user.side_effect = lambda ss, _u, **_kw: ss.update(
            {"_suite_auth_session": {"access_token": "a"}, "_suite_auth_user_id": uid,
             "_suite_auth_user_email": "qa@example.com"})
        _persist_auth_session(session, user=user, tokens={"access_token": "a", "refresh_token": "r"})


def _account_saved_workspace() -> dict:
    """The account's workspace exactly as the app saves it (build_baseball_disk_state)."""
    import json

    from baseball_persistent_state import build_baseball_disk_state
    from draft_state import write_canonical_draft_state

    acct: dict = {"draft_strategy_approach": "value_based"}
    write_canonical_draft_state(acct, queue=list(ACCOUNT_QUEUE), watchlist_focus=[], watchlist_favorites=[],
                                reason="test_account_saved", local_edit=False, sync_widget_keys=True,
                                sync_participant=False)
    return json.loads(json.dumps(build_baseball_disk_state(types.SimpleNamespace(session_state=acct)), default=str))


class GuestSignInTests(unittest.TestCase):
    def test_guest_work_is_dropped_at_sign_in(self) -> None:
        s = _guest_session()
        _sign_in(s)
        self.assertFalse(s.get("draft_queue"))
        for key in ("draft_state_dirty", "_draft_workflow_pending_sync", "_draft_queue_persist_dirty",
                    "_live_draft_queue_last_good", "draft_queue_plan", "draft_strategy_approach",
                    "draft_queue_mode", "watchlist_favorites"):
            self.assertFalse(s.get(key), key)
        self.assertNotIn("guest note", str(s.get("page_filter_state") or {}))
        self.assertNotIn("Aaron Judge", str(s.get("page_filter_state") or {}))
        self.assertEqual(s.get("active_page"), "Draft Strategy Assistant")  # the page is kept

    def test_nothing_left_that_would_make_the_restore_skip_the_accounts_queue(self) -> None:
        # The restore keeps the session queue (skips the account's) while any of these is set.
        from draft_state import is_draft_locally_dirty
        from live_draft_queue_persist import is_draft_queue_persist_dirty

        s = _guest_session()
        _sign_in(s)
        self.assertFalse(is_draft_locally_dirty(s))
        self.assertFalse(s.get("_draft_workflow_pending_sync"))
        self.assertFalse(is_draft_queue_persist_dirty(s))
        self.assertTrue(s.get("_suite_workspace_force_sync"))  # the account's workspace is re-read

    def test_without_the_markers_reset_the_restore_would_keep_the_guest_queue(self) -> None:
        # Documents the mechanism: "unsaved" markers make the restore keep the session queue.
        from baseball_persistent_state import apply_baseball_disk_state

        s = _guest_session()
        st = types.SimpleNamespace(session_state=s)
        with patch("workflow_persist_guard.merge_protected_workflow_on_restore"):
            apply_baseball_disk_state(st, _account_saved_workspace())
        self.assertEqual(s.get("draft_queue"), GUEST_QUEUE)

    def test_re_signing_in_the_same_account_keeps_its_work(self) -> None:
        s = {"_suite_auth_session": {"access_token": "a"}, "_suite_auth_user_id": "auth-barry",
             "draft_queue": list(ACCOUNT_QUEUE), "draft_strategy_approach": "value_based",
             "active_page": "Live Draft Room"}
        _sign_in(s, uid="auth-barry")
        self.assertEqual(s.get("draft_queue"), ACCOUNT_QUEUE)
        self.assertEqual(s.get("draft_strategy_approach"), "value_based")

    def test_switching_accounts_still_drops_the_previous_accounts_work(self) -> None:
        s = {"_suite_auth_session": {"access_token": "a"}, "_suite_auth_user_id": "auth-danny",
             "draft_queue": ["Cal Raleigh"], "draft_queue_plan": {"notes": {"cal raleigh": "danny only"}},
             "active_page": "Live Draft Room"}
        _sign_in(s, uid="auth-barry")
        self.assertFalse(s.get("draft_queue"))
        self.assertNotIn("danny only", str(s))


if __name__ == "__main__":
    unittest.main()
