"""Solo expire loop — page poll gating, ordinary Solo path, no recurring Supabase I/O."""

from __future__ import annotations

import time
import unittest
from unittest import mock

from live_draft_solo_heartbeat import (
    get_solo_timer_idle_egress_report,
    note_solo_timer_poll_tick,
    run_solo_expire_tick,
    schedule_solo_cloud_expire_poll,
    solo_cloud_page_poll_active,
    solo_page_expire_poll_active,
)
from live_draft_solo_timer import expire_current_pick_and_advance, solo_clock_expired
from live_draft_timer_logic import live_draft_reset_timer, live_draft_seconds_remaining
from tests.test_live_draft_solo_timer_expire import _four_pick_solo_room


def _in_progress_solo_room() -> dict:
    room = _four_pick_solo_room(timer_seconds=15)
    live_draft_reset_timer(room)
    return room


class TestSoloPagePollGating(unittest.TestCase):
    def test_local_ordinary_solo_uses_fragment_not_page_poll(self) -> None:
        room = _in_progress_solo_room()
        session = {"live_draft_setup_mode": "solo", "live_draft_room": room}
        with mock.patch("live_draft_cloud_diagnostics.streamlit_cloud_runtime", return_value=False):
            self.assertFalse(solo_page_expire_poll_active(session, room))
            self.assertFalse(solo_cloud_page_poll_active(session, room))

    def test_streamlit_cloud_solo_uses_wake_owner_not_page_poll(self) -> None:
        room = _in_progress_solo_room()
        session = {"live_draft_setup_mode": "solo", "live_draft_room": room}
        with mock.patch("live_draft_cloud_diagnostics.streamlit_cloud_runtime", return_value=True):
            self.assertFalse(solo_page_expire_poll_active(session, room))
            from live_draft_solo_expire_chain import solo_expire_owner

            self.assertEqual(solo_expire_owner(session), "wake")

    def test_local_solo_uses_fragment_owner(self) -> None:
        room = _in_progress_solo_room()
        session = {"live_draft_setup_mode": "solo", "live_draft_room": room}
        with mock.patch("live_draft_cloud_diagnostics.streamlit_cloud_runtime", return_value=False):
            from live_draft_solo_expire_chain import solo_expire_owner

            self.assertEqual(solo_expire_owner(session), "fragment")


class TestOrdinarySoloExpirePipeline(unittest.TestCase):
    def test_run_solo_expire_tick_advances_four_picks_without_ld_accept(self) -> None:
        room = _in_progress_solo_room()
        session = {"live_draft_setup_mode": "solo", "live_draft_room": room, "draft_queue": []}
        st = mock.MagicMock()

        for expected in (1, 2, 3, 4):
            room["timer_deadline"] = time.time() - 0.05
            self.assertTrue(solo_clock_expired(room))
            result = run_solo_expire_tick(st, session, source="heartbeat")
            self.assertIsNotNone(result)
            assert result is not None
            self.assertTrue(result.ok, getattr(result, "error", result.reason))
            self.assertEqual(result.committed_picks, expected)
            if expected < 4:
                self.assertFalse(solo_clock_expired(room))
                self.assertGreater(live_draft_seconds_remaining(room), 0)

        self.assertEqual(str(room.get("status") or ""), "complete")

    def test_expire_engine_matches_production_helper(self) -> None:
        room = _in_progress_solo_room()
        session = {"live_draft_setup_mode": "solo", "live_draft_room": room, "draft_queue": []}
        room["timer_deadline"] = time.time() - 0.05
        direct = expire_current_pick_and_advance(room, session=session)
        self.assertTrue(direct.ok)
        self.assertEqual(direct.committed_picks, 1)


class TestSoloExpireLoopNoSupabase(unittest.TestCase):
    def _patch_remote_io(self):
        return mock.patch.multiple(
            "draft_room_context",
            poll_shared_draft_room=mock.DEFAULT,
            sync_shared_draft_room=mock.DEFAULT,
        )

    def test_heartbeat_tick_does_not_touch_remote_io(self) -> None:
        room = _in_progress_solo_room()
        session = {
            "live_draft_setup_mode": "solo",
            "live_draft_room": room,
            "draft_queue": [],
        }
        st = mock.MagicMock()
        with mock.patch("draft_room_context.poll_shared_draft_room") as poll, mock.patch(
            "suite_storage_supabase._request"
        ) as supa_req, mock.patch("live_draft_pick_persist.flush_deferred_pick_persist") as flush:
            run_solo_expire_tick(st, session, source="heartbeat")
            poll.assert_not_called()
            supa_req.assert_not_called()
            flush.assert_not_called()

    def test_page_poll_tick_does_not_touch_remote_io_when_not_expired(self) -> None:
        room = _in_progress_solo_room()
        session = {
            "live_draft_setup_mode": "solo",
            "live_draft_room": room,
            "active_page": "Live Draft Room",
            "draft_queue": [],
            "_live_draft_heavy_paint_done": True,
            "_live_draft_control_center_mount_log": [{"run_seq": 1}],
            "_live_draft_cloud_accept_mode": True,
            "_solo_cloud_poll_last_at": time.time(),
        }
        st = mock.MagicMock()
        st.rerun = mock.MagicMock()
        with mock.patch(
            "live_draft_cloud_diagnostics.streamlit_cloud_runtime", return_value=False
        ), mock.patch("live_draft_safe_mode.request_live_draft_rerun", return_value=True) as rerun, mock.patch(
            "draft_room_context.poll_shared_draft_room"
        ) as poll, mock.patch("suite_storage_supabase._request") as supa_req, mock.patch(
            "live_draft_pick_persist.flush_deferred_pick_persist"
        ) as flush:
            scheduled = schedule_solo_cloud_expire_poll(st, session, room)
            self.assertFalse(scheduled)
            rerun.assert_not_called()
            poll.assert_not_called()
            supa_req.assert_not_called()
            flush.assert_not_called()

    def test_page_poll_retired(self) -> None:
        room = _in_progress_solo_room()
        room["timer_deadline"] = time.time() + 1.0
        session = {
            "live_draft_setup_mode": "solo",
            "live_draft_room": room,
            "active_page": "Live Draft Room",
            "draft_queue": [],
            "_live_draft_heavy_paint_done": True,
            "_live_draft_control_center_mount_log": [{"run_seq": 1}],
        }
        st = mock.MagicMock()
        with mock.patch(
            "live_draft_cloud_diagnostics.streamlit_cloud_runtime", return_value=True
        ), mock.patch("live_draft_safe_mode.request_live_draft_rerun", return_value=True) as rerun, mock.patch(
            "draft_room_context.poll_shared_draft_room"
        ) as poll, mock.patch("suite_storage_supabase._request") as supa_req:
            scheduled = schedule_solo_cloud_expire_poll(st, session, room)
            self.assertFalse(scheduled)
            rerun.assert_not_called()
            poll.assert_not_called()
            supa_req.assert_not_called()

    def test_solo_skip_remote_poll_suppresses_shared_poller(self) -> None:
        from live_draft_poll_ui import _poll_suppressed_reason

        room = _in_progress_solo_room()
        session = {"live_draft_setup_mode": "solo", "live_draft_room": room}
        self.assertEqual(_poll_suppressed_reason(session), "solo_skip_remote_poll")

    def test_idle_poll_tick_tracks_zero_egress_deltas(self) -> None:
        room = _in_progress_solo_room()
        session = {"live_draft_setup_mode": "solo", "live_draft_room": room}
        with mock.patch("suite_egress_trace.get_run_egress_summary", return_value={"reads": 0, "writes": 0, "full_room_loads": 0}):
            note_solo_timer_poll_tick(session, expired=False)
            note_solo_timer_poll_tick(session, expired=False)
        report = get_solo_timer_idle_egress_report(session)
        self.assertEqual(report["poll_owner"], "local_page")
        self.assertEqual(report["idle_ticks"], 2)
        self.assertEqual(report["idle_reads_per_min"], 0.0)
        self.assertEqual(report["idle_writes_per_min"], 0.0)


class TestSoloExpireChain(unittest.TestCase):
    def test_expire_chain_records_commit_stages(self) -> None:
        from live_draft_solo_expire_chain import note_solo_expire_chain, solo_expire_chain_summary

        session: dict = {}
        note_solo_expire_chain(session, "deadline_confirmed_expired", source="wake")
        note_solo_expire_chain(session, "expire_entered", source="wake")
        note_solo_expire_chain(session, "autopick_attempted", source="expire")
        note_solo_expire_chain(session, "pick_committed", source="wake", pick_index=2)
        summary = solo_expire_chain_summary(session)
        self.assertEqual(summary["commits"], 1)
        self.assertIn("pick_committed", summary["stages_tail"])


class TestSoloComponentWake(unittest.TestCase):
    def test_build_and_parse_expire_token(self) -> None:
        from live_draft_solo_countdown_component import build_solo_expire_token, parse_solo_expire_token

        room = {"draft_room_id": "abc123", "current_pick_index": 2, "timer_deadline": 1000.5}
        token = build_solo_expire_token(room)
        parsed = parse_solo_expire_token(token)
        assert parsed is not None
        self.assertEqual(parsed["draft_id"], "abc123")
        self.assertEqual(parsed["pick_index"], 2)
        self.assertEqual(parsed["deadline"], 1000.5)

    def test_process_component_wake_runs_expire(self) -> None:
        from live_draft_solo_heartbeat import process_solo_component_wake
        from live_draft_solo_countdown_component import build_solo_expire_token

        room = _in_progress_solo_room()
        room["timer_deadline"] = time.time() - 0.05
        session = {"live_draft_setup_mode": "solo", "live_draft_room": room, "draft_queue": []}
        session["_solo_expire_owner"] = "wake"
        st = mock.MagicMock()
        token = build_solo_expire_token(room)
        ok = process_solo_component_wake(st, session, room, token)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
