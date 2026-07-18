"""Regression: _timer_tick must not UnboundLocalError on should_fragment_trigger_full_rerun."""

from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest import mock

from live_draft_expired_pick import should_fragment_trigger_full_rerun
from live_draft_timer_logic import live_draft_reset_timer, live_draft_seconds_remaining


def _room(*, status: str = "in_progress", remaining: float | None = 30.0, pick: int = 0) -> dict:
    room = {
        "status": status,
        "current_pick_index": pick,
        "timer_handled_index": -1,
        "config": {"timer_seconds": 30, "num_teams": 2},
        "draft_board": [],
        "pick_order": [
            {"Pick": 1, "Round": 1, "Team": "Team A"},
            {"Pick": 2, "Round": 1, "Team": "Team B"},
        ],
        "teams": ["Team A", "Team B"],
        "rosters": {"Team A": [], "Team B": []},
        "drafted_player_ids": [],
    }
    if remaining is None:
        room["timer_deadline"] = None
        room["timer_started_at"] = None
    elif remaining <= 0:
        room["timer_deadline"] = time.time() - 1
        room["timer_started_at"] = time.time() - 31
    else:
        live_draft_reset_timer(room)
        # Force exact remaining for display/expiry checks.
        now = time.time()
        room["timer_started_at"] = now - (30 - remaining)
        room["timer_deadline"] = now + remaining
    return room


class _FakeSt:
    def __init__(self) -> None:
        self.captions: list[str] = []
        self.markdowns: list[str] = []
        self.rerun_calls = 0

    def caption(self, text: str) -> None:
        self.captions.append(str(text))

    def markdown(self, text: str, **_kwargs: object) -> None:
        self.markdowns.append(str(text))

    def rerun(self) -> None:
        self.rerun_calls += 1

    def fragment(self, run_every: int = 1):  # noqa: ARG002
        def decorator(fn):
            return fn

        return decorator


def _run_tick_body(session: dict, room: dict, *, poll_changed: bool = False) -> None:
    """Execute the same control flow as _timer_tick without Streamlit fragment wrapping."""
    from live_draft_timer_ui import (
        TIMER_LAST_TICK_TS_KEY,
        TIMER_TICK_COUNT_KEY,
        _guest_waiting_for_host_autopick,
        _render_timer_static,
        _sync_room_on_timer_tick,
    )
    from live_draft_expired_pick import (
        EXPIRED_PICK_PENDING_KEY,
        handle_expired_pick_on_page,
        should_attach_timer_fragment,
        should_fragment_trigger_full_rerun as sftfr,
    )

    st = _FakeSt()
    session[TIMER_TICK_COUNT_KEY] = int(session.get(TIMER_TICK_COUNT_KEY) or 0) + 1
    session[TIMER_LAST_TICK_TS_KEY] = time.time()
    with mock.patch(
        "live_draft_timer_ui._sync_room_on_timer_tick",
        return_value=(room, poll_changed),
    ):
        tick_room, poll_changed = _sync_room_on_timer_tick(session, room)
    if not isinstance(tick_room, dict) or not tick_room:
        return
    if not should_attach_timer_fragment(session, tick_room):
        session[EXPIRED_PICK_PENDING_KEY] = True
        if sftfr(session, tick_room):
            handle_expired_pick_on_page(session, tick_room, source="timer_fragment_zero")
        _render_timer_static(st, session, tick_room, source="fragment_tick_expired")
        if sftfr(session, tick_room):
            session["_test_requested_zero_rerun"] = True
        return
    _render_timer_static(st, session, tick_room, source="fragment_tick")
    if poll_changed:
        session["_test_poll_rerun"] = True
    elif _guest_waiting_for_host_autopick(session, tick_room):
        st.caption("Auto-picking…")
    elif sftfr(session, tick_room):
        session[EXPIRED_PICK_PENDING_KEY] = True
        session["_test_requested_fragment_rerun"] = True


class TimerTickUnboundLocalRegressionTests(unittest.TestCase):
    def test_module_import_resolves(self) -> None:
        self.assertTrue(callable(should_fragment_trigger_full_rerun))

    def test_no_local_reimport_in_timer_tick_source(self) -> None:
        import inspect
        import live_draft_timer_ui as mod

        src = inspect.getsource(mod.render_live_draft_timer_bar)
        # Nested tick must not re-bind the name (causes UnboundLocalError).
        self.assertNotIn(
            "from live_draft_expired_pick import (\n                            handle_expired_pick_on_page,\n                            should_fragment_trigger_full_rerun,",
            src,
        )
        self.assertIn("should_fragment_trigger_full_rerun(session, tick_room)", src)

    def test_tick_above_zero_solo(self) -> None:
        session = {"auth_user_id": "daniel"}
        room = _room(remaining=20)
        _run_tick_body(session, room)
        self.assertNotIn("_test_requested_zero_rerun", session)

    def test_tick_zero_triggers_path(self) -> None:
        session = {"auth_user_id": "daniel"}
        room = _room(remaining=0)
        with mock.patch(
            "live_draft_expired_pick.handle_expired_pick_on_page",
            return_value=SimpleNamespace(ok=True, handled=True, should_rerun=True, message="", error=""),
        ) as autopick:
            with mock.patch(
                "live_draft_expired_pick.should_fragment_trigger_full_rerun",
                return_value=True,
            ):
                with mock.patch(
                    "live_draft_expired_pick.should_attach_timer_fragment",
                    return_value=False,
                ):
                    _run_tick_body(session, room)
        autopick.assert_called()
        self.assertTrue(session.get("_test_requested_zero_rerun") or session.get("_live_draft_timer_expired_pending"))

    def test_invalid_tick_room_safe(self) -> None:
        session = {}
        # Empty / non-dict must not raise.
        _run_tick_body(session, {})  # type: ignore[arg-type]
        with mock.patch(
            "live_draft_timer_ui._sync_room_on_timer_tick",
            return_value=(None, False),
        ):
            from live_draft_timer_ui import TIMER_LAST_TICK_TS_KEY, TIMER_TICK_COUNT_KEY

            session[TIMER_TICK_COUNT_KEY] = 1
            session[TIMER_LAST_TICK_TS_KEY] = time.time()
            tick_room, _ = (None, False)
            if not isinstance(tick_room, dict) or not tick_room:
                return

    def test_paused_and_deleted_do_not_crash(self) -> None:
        for status in ("paused", "complete", "ended", "deleted"):
            session = {"auth_user_id": "daniel"}
            room = _room(status=status, remaining=0)
            _run_tick_body(session, room)

    def test_fresh_deadline_after_reset(self) -> None:
        room = _room(remaining=0)
        before = time.time()
        live_draft_reset_timer(room)
        remaining = live_draft_seconds_remaining(room)
        self.assertGreaterEqual(remaining, 29)
        self.assertLessEqual(remaining, 30)
        self.assertGreaterEqual(float(room["timer_deadline"]), before + 29)

    def test_render_timer_bar_above_zero_no_unbound(self) -> None:
        import live_draft_timer_ui as mod

        st = _FakeSt()
        session = {"auth_user_id": "daniel", "active_page": "Live Draft Room"}
        room = _room(remaining=25)
        with mock.patch.object(mod, "_sync_room_on_timer_tick", return_value=(room, False)):
            with mock.patch.object(mod, "should_attach_timer_fragment", return_value=True):
                with mock.patch.object(mod, "should_fragment_trigger_full_rerun", return_value=False):
                    with mock.patch.object(mod, "sync_live_draft_timer_state", side_effect=lambda s, r: r):
                        with mock.patch.object(mod, "_render_js_countdown"):
                            mod.render_live_draft_timer_bar(st, session, room)

    def test_render_timer_bar_zero_branch_no_unbound(self) -> None:
        import live_draft_timer_ui as mod

        st = _FakeSt()
        session = {"auth_user_id": "daniel", "active_page": "Live Draft Room"}
        room = _room(remaining=0)
        with mock.patch.object(mod, "_sync_room_on_timer_tick", return_value=(room, False)):
            with mock.patch.object(mod, "should_attach_timer_fragment", side_effect=[False, False]):
                with mock.patch.object(mod, "should_fragment_trigger_full_rerun", return_value=False):
                    with mock.patch.object(mod, "sync_live_draft_timer_state", side_effect=lambda s, r: r):
                        with mock.patch.object(mod, "handle_expired_pick_on_page") as hep:
                            hep.return_value = SimpleNamespace(
                                ok=False, handled=False, should_rerun=False, message="", error=""
                            )
                            # Expired path: should_attach False → recovery fragment, not _timer_tick.
                            # Force active fragment path with attach True then expired inside tick.
                            pass
        # Directly exercise the previously crashing branch: attach False inside tick.
        with mock.patch.object(mod, "should_attach_timer_fragment", return_value=True):
            with mock.patch.object(mod, "should_fragment_trigger_full_rerun", return_value=True):
                with mock.patch.object(mod, "_sync_room_on_timer_tick", return_value=(room, False)):
                    with mock.patch.object(mod, "sync_live_draft_timer_state", side_effect=lambda s, r: r):
                        with mock.patch.object(mod, "_render_js_countdown"):
                            with mock.patch.object(
                                mod,
                                "handle_expired_pick_on_page",
                                return_value=SimpleNamespace(
                                    ok=True, handled=True, should_rerun=True, message="", error=""
                                ),
                            ):
                                # First call: attach True so fragment is defined; then tick uses room at 0.
                                # should_attach inside tick returns False via a side_effect sequence.
                                with mock.patch.object(
                                    mod,
                                    "should_attach_timer_fragment",
                                    side_effect=[True, False, False],
                                ):
                                    with mock.patch(
                                        "live_draft_safe_mode.request_live_draft_rerun",
                                        return_value=True,
                                    ):
                                        mod.render_live_draft_timer_bar(st, session, room)


if __name__ == "__main__":
    unittest.main()
