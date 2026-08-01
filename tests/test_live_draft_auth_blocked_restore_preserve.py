"""Regression: auth-blocked empty restore must not wipe in-session active room."""

from __future__ import annotations

import time

import pytest


def _runtime_room(*, room_id: str = "ABC123", pick: int = 0) -> dict:
    import pandas as pd

    return {
        "draft_room_id": room_id,
        "status": "in_progress",
        "current_pick_index": pick,
        "timer_deadline": time.time() + 60,
        "config": {"timer_seconds": 60},
        "draft_board": [],
        "pool": pd.DataFrame(),
    }


def test_preserve_in_progress_room_on_auth_required() -> None:
    from live_draft_creation_trace import protect_new_room
    from live_draft_state import (
        LIVE_DRAFT_ROOM_KEY,
        LIVE_DRAFT_STATE_KEY,
        prepare_live_draft_state,
        should_preserve_in_session_room_on_auth_blocked_restore,
        write_canonical_live_draft_state,
    )

    session: dict = {}
    room = _runtime_room()
    write_canonical_live_draft_state(session, room, reason="test_create", local_edit=True)
    protect_new_room(session)
    assert should_preserve_in_session_room_on_auth_blocked_restore(session, block_reason="auth_required")

    session[LIVE_DRAFT_STATE_KEY] = {"draft_room_id": "OTHER", "status": "in_progress", "pool_records": []}
    out = prepare_live_draft_state(session)
    assert out is not None
    assert str(session[LIVE_DRAFT_ROOM_KEY]["draft_room_id"]).upper() == "ABC123"
    assert session[LIVE_DRAFT_ROOM_KEY]["status"] == "in_progress"
    assert session[LIVE_DRAFT_ROOM_KEY]["current_pick_index"] == 0
    assert session[LIVE_DRAFT_ROOM_KEY].get("timer_deadline")


def test_no_runtime_room_cannot_preserve_on_auth_block() -> None:
    from live_draft_state import should_preserve_in_session_room_on_auth_blocked_restore

    assert not should_preserve_in_session_room_on_auth_blocked_restore({}, block_reason="auth_required")


def test_auth_user_mismatch_does_not_preserve_foreign_runtime() -> None:
    from live_draft_state import should_preserve_in_session_room_on_auth_blocked_restore, write_canonical_live_draft_state

    session: dict = {}
    write_canonical_live_draft_state(session, _runtime_room(room_id="FOREIGN"), reason="test", local_edit=True)
    assert not should_preserve_in_session_room_on_auth_blocked_restore(session, block_reason="auth_user_mismatch")


def test_authorized_restore_still_applies_when_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    from live_draft_state import (
        LIVE_DRAFT_ROOM_KEY,
        live_draft_restore_allowed,
        prepare_live_draft_state,
        room_from_persist_dict,
        write_canonical_live_draft_state,
    )

    session: dict = {LIVE_DRAFT_ROOM_KEY: None}
    blob = {
        "draft_room_id": "RESTORE1",
        "status": "in_progress",
        "current_pick_index": 0,
        "pool_records": [],
        "pool_columns": [],
        "config": {"timer_seconds": 60},
    }
    write_canonical_live_draft_state(session, None, reason="clear", local_edit=True)
    session["live_draft_state"] = blob

    monkeypatch.setattr(
        "live_draft_state.live_draft_restore_allowed",
        lambda s, b, source="": (True, "test_allowed"),
    )
    allowed, _ = live_draft_restore_allowed(session, blob)
    assert allowed
    restored = prepare_live_draft_state(session)
    assert restored is not None
    assert str(restored.get("draft_room_id")).upper() == "RESTORE1"
