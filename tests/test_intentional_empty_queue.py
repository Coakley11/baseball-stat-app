"""Removing the last Global Queue player must stay removed after a refresh (owner, 2026-11-08).

Root cause: workspace_cloud_guard._preserve_workspace (the July anti-wipe protection) copied the
stored non-empty draft_queue back over every outgoing empty one unless the save reason was an
explicit clear. Removing the last player saves as "draft_edit", so the saved copy kept the player
(draft_queue=['Aaron Judge'] next to draft_state.queue=[]) and the next load restored it.

Fix: a user action that empties a populated queue records draft_state.queue_cleared_at; every real
queue change records queue_changed_at. An empty queue WITH a marker not older than the stored
queue's last change is written and restored as empty; an empty queue WITHOUT a marker (hydration,
reconnect, stale session, failed load) is still protected exactly as before.
"""

from __future__ import annotations

import copy
import os
import time
import unittest
from unittest import mock

os.environ.setdefault("SUITE_STORAGE_ISOLATED", "1")

import baseball_persistent_state as bps  # noqa: E402
import draft_state as ds  # noqa: E402
import workspace_cloud_guard as guard  # noqa: E402


class _St:
    def __init__(self, session=None):
        self.session_state = session if session is not None else {}
        self.query_params = {}

    def __getattr__(self, _name):
        return lambda *a, **k: None


def _settle(session: dict) -> None:
    """What a successful save does to the session's 'unsaved' markers."""
    for key in [k for k in session if str(k).endswith(("_dirty", "_pending_sync"))]:
        session.pop(key)


def _saved(st: _St) -> dict:
    return copy.deepcopy(bps.build_baseball_disk_state(st))


def _cloud_write(outgoing: dict, cloud: dict, reason: str = "draft_edit") -> dict:
    """The cloud guard's view of a save: returns what would actually be written."""
    out = copy.deepcopy(outgoing)
    guard._preserve_workspace(out, cloud, reason)
    return out


def _restored_queue(state: dict) -> list:
    st = _St()
    bps.apply_baseball_disk_state(st, copy.deepcopy(state))
    return list(st.session_state.get("draft_queue") or [])


class IntentionalClearTests(unittest.TestCase):
    def setUp(self) -> None:
        self.st = _St()
        self.s = self.st.session_state
        ds.add_player_to_draft_queue(self.s, "Aaron Judge")
        _settle(self.s)
        self.stored = _saved(self.st)  # the account's saved copy, with the player

    def _remove_last(self) -> dict:
        ds.remove_player_from_user_draft_queue(self.s, "Aaron Judge")
        return _saved(self.st)

    def test_removing_the_last_player_records_the_clear(self) -> None:
        self._remove_last()
        meta = self.s["draft_state"]
        self.assertEqual(meta["queue"], [])
        self.assertTrue(ds.intentionally_cleared(meta))
        self.assertTrue(meta.get(ds.QUEUE_CHANGED_AT))

    def test_the_cloud_write_keeps_the_empty_queue(self) -> None:
        written = _cloud_write(self._remove_last(), self.stored)
        self.assertEqual(written["draft_queue"], [])
        self.assertEqual(written["draft_state"]["queue"], [])

    def test_before_the_fix_the_stored_player_came_back(self) -> None:
        outgoing = self._remove_last()
        outgoing["draft_state"].pop(ds.QUEUE_CLEARED_AT)  # what the July code saw: no intent
        written = _cloud_write(outgoing, self.stored)
        self.assertEqual(written["draft_queue"], ["Aaron Judge"])  # the reported bug
        self.assertEqual(_restored_queue(written), ["Aaron Judge"])

    def test_refresh_restores_an_empty_queue(self) -> None:
        written = _cloud_write(self._remove_last(), self.stored)
        self.assertEqual(_restored_queue(written), [])

    def test_navigation_saves_keep_it_empty(self) -> None:
        written = _cloud_write(self._remove_last(), self.stored)
        st2 = _St()
        bps.apply_baseball_disk_state(st2, copy.deepcopy(written))
        for reason in ("page_change", "autosave", "draft_strategy_queue_loaded"):
            again = _cloud_write(_saved(st2), written, reason)
            self.assertEqual(again["draft_queue"], [], reason)
            written = again
        self.assertEqual(_restored_queue(written), [])

    def test_a_stale_older_copy_does_not_win_on_restore(self) -> None:
        written = _cloud_write(self._remove_last(), self.stored)
        # an older envelope / page block still listing the player must not be used as a fallback
        written["baseball_workspace_state"] = copy.deepcopy(self.stored.get("baseball_workspace_state"))
        written.setdefault("baseball_workspace_state", {})["draft_workflow"] = {
            "queue": ["Aaron Judge"], "watchlist_focus": [], "watchlist_favorites": []}
        self.assertEqual(ds._draft_workflow_from_blob(written)["queue"], [])

    def test_cloud_apply_writes_the_clear_over_a_stale_session(self) -> None:
        written = _cloud_write(self._remove_last(), self.stored)
        stale = {}
        ds.add_player_to_draft_queue(stale, "Aaron Judge")
        _settle(stale)
        stale["draft_state"].pop(ds.QUEUE_CHANGED_AT, None)  # loaded earlier, not edited here
        self.assertTrue(ds.apply_cloud_draft_state_if_allowed(stale, written))
        self.assertEqual(stale["draft_queue"], [])
        self.assertTrue(ds.intentionally_cleared(stale["draft_state"]))

    def test_adding_again_ends_the_clear(self) -> None:
        self._remove_last()
        ds.add_player_to_draft_queue(self.s, "Juan Soto")
        self.assertFalse(ds.intentionally_cleared(self.s["draft_state"]))
        self.assertNotIn(ds.QUEUE_CLEARED_AT, self.s["draft_state"])


class ProtectionStillWorksTests(unittest.TestCase):
    """The July protection: accidental empties never wipe a saved queue."""

    def setUp(self) -> None:
        st = _St()
        ds.add_player_to_draft_queue(st.session_state, "Aaron Judge")
        _settle(st.session_state)
        self.stored = _saved(st)

    def test_an_unhydrated_empty_session_does_not_wipe_the_saved_queue(self) -> None:
        fresh = _saved(_St())  # a session that never loaded the account (no marker)
        self.assertEqual(_cloud_write(fresh, self.stored)["draft_queue"], ["Aaron Judge"])

    def test_a_hydration_empty_sets_no_marker(self) -> None:
        s: dict = {}
        ds.add_player_to_draft_queue(s, "Aaron Judge")
        _settle(s)
        ds.write_canonical_draft_state(s, queue=[], reason="participant_hydrate", local_edit=False)
        self.assertFalse(ds.intentionally_cleared(s.get("draft_state")))

    def test_an_empty_saved_copy_without_a_marker_does_not_wipe_a_live_session(self) -> None:
        live = {}
        ds.add_player_to_draft_queue(live, "Aaron Judge")
        _settle(live)
        empty_no_marker = _saved(_St())
        st = _St(live)
        bps.apply_baseball_disk_state(st, copy.deepcopy(empty_no_marker))
        self.assertEqual(live.get("draft_queue"), ["Aaron Judge"])

    def test_a_newer_add_on_another_device_is_not_erased_by_an_older_clear(self) -> None:
        mine = _St()
        ds.add_player_to_draft_queue(mine.session_state, "Aaron Judge")
        _settle(mine.session_state)
        ds.remove_player_from_user_draft_queue(mine.session_state, "Aaron Judge")
        my_clear = _saved(mine)
        time.sleep(0.01)
        other = _St()
        ds.add_player_to_draft_queue(other.session_state, "Juan Soto")  # later, elsewhere
        newer_cloud = _saved(other)
        self.assertEqual(_cloud_write(my_clear, newer_cloud)["draft_queue"], ["Juan Soto"])

    def test_other_protected_keys_are_still_preserved(self) -> None:
        stored = copy.deepcopy(self.stored)
        stored["draft_archive_teams"] = [{"draft_id": "d1"}]
        st = _St()
        ds.add_player_to_draft_queue(st.session_state, "Aaron Judge")
        _settle(st.session_state)
        ds.remove_player_from_user_draft_queue(st.session_state, "Aaron Judge")
        written = _cloud_write(_saved(st), stored)
        self.assertEqual(written["draft_queue"], [])
        self.assertEqual(written["draft_archive_teams"], [{"draft_id": "d1"}])  # saved drafts kept


class IsolationTests(unittest.TestCase):
    def test_draft_working_copies_are_not_touched(self) -> None:
        s: dict = {"draft_queue_plan": ["Aaron Judge"], "draft_queue_adaptive": {"order": ["Aaron Judge"]}}
        ds.add_player_to_draft_queue(s, "Aaron Judge")
        _settle(s)
        ds.remove_player_from_user_draft_queue(s, "Aaron Judge")
        self.assertEqual(s["draft_queue_plan"], ["Aaron Judge"])
        self.assertEqual(s["draft_queue_adaptive"], {"order": ["Aaron Judge"]})

    def test_the_marker_lives_in_the_account_state_only(self) -> None:
        with mock.patch("draft_state._precise_now_iso", return_value="2026-11-08T12:00:00.000001+00:00"):
            s: dict = {}
            ds.add_player_to_draft_queue(s, "Aaron Judge")
            _settle(s)
            ds.remove_player_from_user_draft_queue(s, "Aaron Judge")
        self.assertEqual(s["draft_state"][ds.QUEUE_CLEARED_AT], "2026-11-08T12:00:00.000001+00:00")
        other_account: dict = {}
        self.assertFalse(ds.intentionally_cleared(other_account.get("draft_state")))


if __name__ == "__main__":
    unittest.main()
