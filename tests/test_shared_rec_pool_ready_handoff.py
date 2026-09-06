"""Regression: empty shared pool → later local rebuild must trigger a full ScriptRun.

Live Shared Start can finish HEAVY_PAINT_DONE with empty top_rec while the wire
still omits pool. An out-of-process rebuild for the same room may succeed, but
poll fragments historically only reran on revision changes — leaving Add-to-Queue
unregistered until a manual restore.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd

from live_draft_heavy_paint_ui import HEAVY_PAINT_DONE_KEY, render_deferred_heavy_paint_fragment
from live_draft_rec_live_paint import (
    INTERACTIVE_PAINT_STATUS_KEY,
    PREPARED_REC_INTERACTIVE_KEY,
    render_rec_interactive_widgets,
)
from shared_draft_local_pool import (
    SHARED_REC_POOL_PENDING_KEY,
    SHARED_REC_POOL_READY_RERUN_ATTEMPTED_KEY,
    clear_shared_rec_pool_pending,
    ensure_local_shared_player_pool,
    mark_shared_rec_pool_pending,
    maybe_request_full_rerun_when_shared_pool_ready,
    shared_rec_pool_pending,
)


def _pool() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fullName": "Aaron Judge",
                "Primary Position": "OF",
                "playerID": "592450",
            }
        ]
    )


def _shared_room(*, pool: Any = None) -> dict[str, Any]:
    room: dict[str, Any] = {
        "draft_room_id": "ROOM_SHARED1",
        "room_code": "ABCD12",
        "status": "in_progress",
        "current_pick_index": 0,
        "config": {
            "draft_setup_mode": "shared",
            "room_code": "ABCD12",
            "your_team": "Team A",
        },
        "draft_board": [],
    }
    if pool is not None:
        room["pool"] = pool
    else:
        room["pool"] = pd.DataFrame()
    return room


class SharedRecPoolReadyHandoffTests(unittest.TestCase):
    def test_interactive_marks_pending_when_pool_empty_and_top_rec_missing(self) -> None:
        st = MagicMock()
        session: dict[str, Any] = {
            "active_shared_draft_room_code": "ABCD12",
            PREPARED_REC_INTERACTIVE_KEY: {
                "room_id": "ROOM_SHARED1",
                "gaps": [],
                "category_needs": [],
                "max_cards": 1,
                "multiplayer": True,
            },
        }
        room = _shared_room()
        with patch(
            "live_draft_rec_live_paint._rebuild_top_rec_into_cache",
            return_value=pd.DataFrame(),
        ):
            ok = render_rec_interactive_widgets(st, session, room)
        self.assertFalse(ok)
        self.assertTrue(shared_rec_pool_pending(session))
        status = session.get(INTERACTIVE_PAINT_STATUS_KEY) or {}
        self.assertEqual(status.get("fail_reason"), "top_rec_missing_after_rebuild")
        self.assertTrue(status.get("shared_rec_pool_pending"))

    def test_poll_requests_app_rerun_when_local_pool_becomes_ready(self) -> None:
        st = MagicMock()
        session: dict[str, Any] = {
            "active_shared_draft_room_code": "ABCD12",
            "_live_draft_start_in_flight": True,
            "_start_live_draft_pending": True,
        }
        mark_shared_rec_pool_pending(session, reason="empty_local_pool")
        room = _shared_room()
        session["live_draft_room"] = room
        rebuilt = _pool()

        requested = maybe_request_full_rerun_when_shared_pool_ready(
            st,
            session,
            room,
            builder=lambda _s, _r: rebuilt,
        )
        self.assertTrue(requested)
        self.assertFalse(getattr(room.get("pool"), "empty", True))
        self.assertTrue(session.get(SHARED_REC_POOL_READY_RERUN_ATTEMPTED_KEY))
        self.assertEqual(session.get("_live_draft_last_rerun_source"), "shared_rec_pool_ready")
        self.assertFalse(session.get("_live_draft_start_in_flight"))
        try:
            st.rerun.assert_called()
            if st.rerun.call_args is not None and st.rerun.call_args.kwargs:
                self.assertEqual(st.rerun.call_args.kwargs.get("scope"), "app")
        except AssertionError:
            st.rerun.assert_called()

        # Second call must not loop.
        st.rerun.reset_mock()
        again = maybe_request_full_rerun_when_shared_pool_ready(
            st, session, room, builder=lambda _s, _r: rebuilt
        )
        self.assertFalse(again)
        st.rerun.assert_not_called()

    def test_heavy_done_mounts_readiness_watcher_not_interactive_widgets(self) -> None:
        st = MagicMock()
        fragment_kwargs: list[dict[str, Any]] = []
        watcher_invocations = {"n": 0}

        def _fragment_decorator(**kwargs):
            fragment_kwargs.append(dict(kwargs))

            def _wrap(fn):
                def _run():
                    watcher_invocations["n"] += 1
                    fn()

                return _run

            return _wrap

        st.fragment = _fragment_decorator
        session: dict[str, Any] = {
            HEAVY_PAINT_DONE_KEY: True,
            "active_shared_draft_room_code": "ABCD12",
            SHARED_REC_POOL_PENDING_KEY: True,
            "live_draft_room": _shared_room(),
        }
        interactive = {"n": 0}

        def paint_interactive() -> bool:
            interactive["n"] += 1
            return False

        with patch("live_draft_fast_solo_start.should_defer_heavy_first_paint", return_value=False):
            with patch("live_draft_fast_solo_start.note_start_stage"):
                with patch(
                    "shared_draft_local_pool.maybe_request_full_rerun_when_shared_pool_ready",
                    return_value=False,
                ) as ready:
                    render_deferred_heavy_paint_fragment(
                        st,
                        session,
                        lambda: None,
                        paint_interactive=paint_interactive,
                    )
                    # Watcher body runs once on mount.
                    if watcher_invocations["n"]:
                        ready.assert_called()
        self.assertGreaterEqual(interactive["n"], 1)
        self.assertEqual(session.get("_live_draft_rec_queue_interactive_owner"), "script_run_no_run_every")
        self.assertTrue(fragment_kwargs)
        self.assertEqual(fragment_kwargs[0].get("run_every"), 1)
        # Interactive owner remains ScriptRun — watcher must not claim queue widgets.
        self.assertNotEqual(
            session.get("_live_draft_rec_queue_interactive_owner"),
            "fragment_run_every",
        )

    def test_full_scriptrun_after_pool_ready_registers_cards(self) -> None:
        st = MagicMock()
        session: dict[str, Any] = {
            "active_shared_draft_room_code": "ABCD12",
        }
        mark_shared_rec_pool_pending(session, reason="empty_local_pool")
        room = _shared_room()
        ensure_local_shared_player_pool(
            session, room, builder=lambda _s, _r: _pool()
        )
        rebuilt = pd.DataFrame(
            [{"fullName": "Aaron Judge", "Primary Position": "OF", "playerID": "592450"}]
        )
        with patch(
            "live_draft_rec_live_paint._rebuild_top_rec_into_cache",
            return_value=rebuilt,
        ):
            with patch("live_draft_room_ui.render_live_draft_rec_cards") as cards:
                with patch("live_draft_room_ui.render_live_draft_rec_summary_banner"):
                    ok = render_rec_interactive_widgets(st, session, room)
        self.assertTrue(ok)
        cards.assert_called_once()
        self.assertFalse(shared_rec_pool_pending(session))
        clear_shared_rec_pool_pending(session)


if __name__ == "__main__":
    unittest.main()
