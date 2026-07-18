"""Release-blocking Live Draft reliability: discard, reattach, queue X, timer zero."""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from draft_room_participant_state import (
    ACTIVE_PARTICIPANT_ID_KEY,
    ACTIVE_SHARED_ROOM_CODE_KEY,
    MEMBERSHIP_KEY,
    PARTICIPANT_STATE_KEY,
    clear_participant_left_room,
    mark_participant_left_room,
    participant_has_left_room,
    restore_persisted_shared_room_membership,
)
from draft_state import DRAFT_QUEUE_KEY, remove_player_from_user_draft_queue
from live_draft_completion import (
    LIFECYCLE_ACTIVE_DRAFT,
    LIFECYCLE_DELETING,
    LIFECYCLE_SETUP,
    resolve_live_draft_lifecycle,
)
from live_draft_expired_pick import (
    TIMER_ZERO_RERUN_LATCH_KEY,
    TIMER_ZERO_RERUN_LATCH_TS_KEY,
    claim_timer_zero_rerun,
    expire_pick_and_advance,
    timer_zero_rerun_already_latched,
)
from live_draft_poll_ui import _poll_suppressed_reason
from live_draft_termination import (
    DELETING_STATUS_KEY,
    SUPPRESS_FRAGMENTS_KEY,
    discard_live_draft_and_start_over,
    live_draft_fragments_suppressed,
)
from live_draft_timer_logic import live_draft_reset_timer


class DiscardExclusivityTests(unittest.TestCase):
    def test_discard_suppresses_fragments_and_stays_setup(self) -> None:
        session = {
            "live_draft_room": {
                "status": "in_progress",
                "draft_room_id": "dr-1",
                "room_id": "dr-1",
                "current_pick_index": 3,
                "draft_board": [{"player": "A"}],
                "config": {"timer_seconds": 30},
                "sync": {"room_code": "ABC123"},
            },
            ACTIVE_SHARED_ROOM_CODE_KEY: "ABC123",
            DRAFT_QUEUE_KEY: ["Player One"],
            "live_queue_sortable_ABC123_user_e1": ["Player One"],
        }
        with patch("live_draft_termination._close_backend_room"), patch(
            "live_draft_termination.persist_durable_tombstones"
        ), patch("live_draft_termination._clear_query_room_params"):
            result = discard_live_draft_and_start_over(session, st=None)
        self.assertTrue(result.get("ok"))
        self.assertEqual(session.get(DELETING_STATUS_KEY), "done")
        self.assertTrue(live_draft_fragments_suppressed(session))
        self.assertEqual(resolve_live_draft_lifecycle(session), LIFECYCLE_SETUP)
        self.assertFalse(isinstance(session.get("live_draft_room"), dict))
        # After discard, fragments are suppressed (and/or page gate blocks them).
        reason = _poll_suppressed_reason(session)
        self.assertIn(
            reason,
            ("fragments_suppressed_or_deleting", "page_mismatch", "lifecycle_setup"),
        )
        self.assertFalse(
            any(str(k).startswith("live_queue_sortable") for k in session.keys())
        )

    def test_deleting_lifecycle_exclusive(self) -> None:
        session = {
            DELETING_STATUS_KEY: "in_progress",
            "live_draft_room": {"status": "in_progress"},
        }
        self.assertEqual(resolve_live_draft_lifecycle(session), LIFECYCLE_DELETING)
        self.assertTrue(live_draft_fragments_suppressed(session))


class ReattachMembershipTests(unittest.TestCase):
    def test_has_left_is_per_participant_not_any_slot(self) -> None:
        session = {
            ACTIVE_PARTICIPANT_ID_KEY: "coakley",
            PARTICIPANT_STATE_KEY: {
                "ROOM01": {
                    "by_participant": {
                        "daniel": {"left_at": "2026-07-01T00:00:00+00:00"},
                        "coakley": {"joined_at": "2026-07-01T00:00:00+00:00"},
                    }
                }
            },
        }
        with patch(
            "draft_room_participant_state.resolve_participant_id",
            return_value="coakley",
        ):
            self.assertFalse(participant_has_left_room(session, "ROOM01"))
            mark_participant_left_room(session, "ROOM01", participant_id="coakley")
            self.assertTrue(participant_has_left_room(session, "ROOM01"))
            clear_participant_left_room(session, "ROOM01")
            self.assertFalse(participant_has_left_room(session, "ROOM01"))

    def test_soft_offline_keeps_room_code_and_membership(self) -> None:
        session = {
            ACTIVE_SHARED_ROOM_CODE_KEY: "TEAMBB",
            ACTIVE_PARTICIPANT_ID_KEY: "auth-coakley",
            MEMBERSHIP_KEY: {
                "TEAMBB": {
                    "auth-coakley": {
                        "participant_id": "auth-coakley",
                        "assigned_team": "Team B",
                    }
                }
            },
            "live_draft_room": {"status": "in_progress", "sync": {"room_code": "TEAMBB"}},
        }
        with patch("suite_auth.is_auth_enabled", return_value=True), patch(
            "suite_auth.is_authenticated", return_value=False
        ):
            code = restore_persisted_shared_room_membership(session)
        self.assertEqual(code, "TEAMBB")
        self.assertEqual(session.get(ACTIVE_SHARED_ROOM_CODE_KEY), "TEAMBB")
        self.assertTrue(session.get("_live_draft_presence_offline"))
        self.assertNotIn("live_draft_room", session)
        self.assertIn("TEAMBB", session.get(MEMBERSHIP_KEY) or {})


class QueueRemoveTests(unittest.TestCase):
    def test_remove_busts_scoped_sortable_keys(self) -> None:
        session = {
            DRAFT_QUEUE_KEY: ["Alpha", "Beta", "Gamma"],
            "live_queue_sortable_room1_user1_e3": ["Alpha", "Beta", "Gamma"],
            "sidebar_queue_sortable_room1_user1_e3": ["Alpha", "Beta", "Gamma"],
            "_draft_queue_widget_epoch": 3,
        }
        with patch("draft_state._queue_scope_ids", return_value=("room1", "user1")):
            q, changed = remove_player_from_user_draft_queue(session, "Beta", reason="test_x")
        self.assertTrue(changed)
        self.assertEqual(q, ["Alpha", "Gamma"])
        self.assertTrue(session.get("_draft_queue_skip_sortable_once"))
        self.assertEqual(int(session.get("_draft_queue_widget_epoch") or 0), 4)
        self.assertFalse(
            any(str(k).startswith("live_queue_sortable") for k in session.keys())
        )
        self.assertFalse(
            any(str(k).startswith("sidebar_queue_sortable") for k in session.keys())
        )


class TimerZeroLatchTests(unittest.TestCase):
    def test_expire_pick_and_advance_callable(self) -> None:
        room = {
            "status": "in_progress",
            "current_pick_index": 0,
            "draft_board": [],
            "config": {"timer_seconds": 30},
            "pick_order": [{"Team": "A"}, {"Team": "B"}],
        }
        live_draft_reset_timer(room)
        room["timer_deadline"] = time.time() - 1
        session = {"live_draft_room": room}
        with patch(
            "live_draft_expired_pick.handle_expired_pick_on_page",
            return_value=type(
                "R",
                (),
                {"handled": True, "ok": True, "should_rerun": True, "message": "ok", "error": ""},
            )(),
        ):
            result = expire_pick_and_advance(
                session,
                expected_pick_number=0,
                expected_deadline=room["timer_deadline"],
            )
        self.assertTrue(result.ok)

    def test_zero_latch_ttl_allows_retry(self) -> None:
        room = {
            "status": "in_progress",
            "current_pick_index": 2,
            "config": {"timer_seconds": 30},
        }
        live_draft_reset_timer(room)
        room["timer_deadline"] = time.time() - 5
        session = {"live_draft_room": room}
        self.assertTrue(claim_timer_zero_rerun(session, room))
        self.assertFalse(claim_timer_zero_rerun(session, room))
        # Expire the latch TTL so another wake can fire.
        session[TIMER_ZERO_RERUN_LATCH_TS_KEY] = time.time() - 5.0
        self.assertFalse(timer_zero_rerun_already_latched(session, room))
        self.assertTrue(claim_timer_zero_rerun(session, room))


class LifecycleActiveClearsSuppress(unittest.TestCase):
    def test_active_lifecycle_when_room_present(self) -> None:
        session = {
            "live_draft_room": {
                "status": "in_progress",
                "config": {"timer_seconds": 30},
            },
            ACTIVE_SHARED_ROOM_CODE_KEY: "ZZZZZZ",
            SUPPRESS_FRAGMENTS_KEY: 9,
            DELETING_STATUS_KEY: "done",
        }
        self.assertEqual(resolve_live_draft_lifecycle(session), LIFECYCLE_ACTIVE_DRAFT)


if __name__ == "__main__":
    unittest.main()
