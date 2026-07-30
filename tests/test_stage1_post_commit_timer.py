"""Post-commit next-timer continuity: stale pending token must not block pick-1 mount."""

from __future__ import annotations

import time
from unittest import mock

from live_draft_solo_persistent_wake import (
    SOLO_PERSISTENT_WAKE_LATCH_KEY,
    SOLO_PERSISTENT_WAKE_PICK_LATCH_KEY,
    SOLO_PERSISTENT_WAKE_TOKEN_KEY,
    resolve_persistent_wake_mount,
)
from live_draft_stage1_expire_audit import (
    SOLO_STAGE1_ACTION_COMPLETE_KEY,
    mark_token_action_complete,
)
from live_draft_stage1_post_commit_timer import (
    compute_next_pick_timer_state,
    finalize_post_commit_timer_continuity,
    pending_mount_token_usable,
)
from solo_countdown_component import build_solo_expire_token


def _room(*, pick: int = 0, draft_id: str = "ROOM1234") -> dict:
    deadline = time.time() + 30.0
    return {
        "draft_room_id": draft_id,
        "current_pick_index": pick,
        "status": "in_progress",
        "timer_deadline": deadline,
        "config": {"timer_seconds": 30, "draft_setup_mode": "solo"},
    }


def test_pending_mount_rejects_stale_pick_zero_after_advance() -> None:
    room0 = _room(pick=0)
    room1 = _room(pick=1)
    token0 = build_solo_expire_token(room0)
    session: dict = {}
    assert pending_mount_token_usable(session, room0, token0, pending_raw=token0)
    assert not pending_mount_token_usable(session, room1, token0, pending_raw=token0)


def test_action_complete_does_not_block_new_pick_one_token() -> None:
    room0 = _room(pick=0)
    room1 = _room(pick=1)
    token0 = build_solo_expire_token(room0)
    token1 = build_solo_expire_token(room1)
    session: dict = {}
    mark_token_action_complete(session, token0, pick_index_before=0, pick_index_after=1)
    assert not pending_mount_token_usable(session, room1, token0, pending_raw=token0)
    new_token, dl = compute_next_pick_timer_state(room1)
    assert new_token == token1
    assert dl is not None
    assert token1 != token0
    assert "|1|" in token1


def test_finalize_sets_next_wake_token_and_pick_latch() -> None:
    room0 = _room(pick=0)
    room1 = dict(_room(pick=1))
    room1["timer_deadline"] = time.time() + 25.0
    token0 = build_solo_expire_token(room0)
    token1 = build_solo_expire_token(room1)
    st = mock.MagicMock()
    st.session_state = {SOLO_PERSISTENT_WAKE_TOKEN_KEY: token0, "solo_countdown_wake_solo_persistent": token0}
    session: dict = {
        SOLO_PERSISTENT_WAKE_TOKEN_KEY: token0,
        SOLO_PERSISTENT_WAKE_LATCH_KEY: True,
    }
    with mock.patch(
        "live_draft_safe_mode.request_live_draft_rerun",
        return_value=True,
    ):
        out = finalize_post_commit_timer_continuity(
            st,
            session,
            room1,
            completed_token=token0,
            result=None,
        )
    assert out["ok"] is True
    assert out["next_token"] == token1
    assert session[SOLO_PERSISTENT_WAKE_TOKEN_KEY] == token1
    assert session[SOLO_PERSISTENT_WAKE_PICK_LATCH_KEY] == 1


def test_resolve_mount_after_advance_yields_pick_one_token() -> None:
    room1 = _room(pick=1)
    session: dict = {SOLO_PERSISTENT_WAKE_LATCH_KEY: True}
    actionable, token, props, phase = resolve_persistent_wake_mount(session, room1)
    assert actionable is True
    assert phase == "active"
    assert "|1|" in token
    assert int(props.get("current_pick_index") or 0) == 1
