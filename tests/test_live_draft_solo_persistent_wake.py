"""Unit tests for early-route persistent Solo wake (production)."""

from __future__ import annotations

import time
from unittest import mock

import pytest

from live_draft_solo_heartbeat import SOLO_COMPONENT_WAKE_SEEN_KEY, process_solo_component_wake
from live_draft_solo_persistent_wake import (
    SOLO_PERSISTENT_WAKE_WIDGET_KEY,
    build_solo_idle_expire_token,
    expire_token_for_persistent_wake,
    solo_persistent_wake_active,
    solo_persistent_wake_widget_key,
)
from solo_countdown_component import build_solo_expire_token, parse_solo_expire_token


def test_stable_widget_key_constant() -> None:
    assert solo_persistent_wake_widget_key({}) == SOLO_PERSISTENT_WAKE_WIDGET_KEY
    room = {"draft_room_id": "ABCD1234", "current_pick_index": 3}
    assert solo_persistent_wake_widget_key({}) == solo_persistent_wake_widget_key({"live_draft_room": room})


def test_token_changes_when_pick_and_deadline_change() -> None:
    deadline_a = time.time() + 60
    deadline_b = time.time() + 90
    room_a = {
        "draft_room_id": "R1",
        "current_pick_index": 0,
        "status": "in_progress",
        "timer_deadline": deadline_a,
        "config": {"timer_seconds": 60, "draft_setup_mode": "solo"},
    }
    room_b = {**room_a, "current_pick_index": 1, "timer_deadline": deadline_b}
    tok_a, _ = expire_token_for_persistent_wake({"live_draft_setup_mode": "solo"}, room_a)
    tok_b, _ = expire_token_for_persistent_wake({"live_draft_setup_mode": "solo"}, room_b)
    assert tok_a != tok_b
    assert parse_solo_expire_token(tok_a)["pick_index"] == 0
    assert parse_solo_expire_token(tok_b)["pick_index"] == 1


def test_idle_setup_cannot_commit_pick() -> None:
    session: dict = {"live_draft_setup_mode": "solo"}
    room = {
        "draft_room_id": "R1",
        "current_pick_index": 0,
        "status": "in_progress",
        "timer_deadline": time.time() + 30,
        "config": {"timer_seconds": 30, "draft_setup_mode": "solo"},
    }
    idle = build_solo_idle_expire_token()
    st = mock.MagicMock()
    with mock.patch("live_draft_solo_expire_chain.solo_expire_owner", return_value="wake"):
        assert process_solo_component_wake(st, session, room, idle, delivery_via="on_change") is False


def test_stale_token_rejected_pick_mismatch() -> None:
    session: dict = {"live_draft_setup_mode": "solo"}
    room = {
        "draft_room_id": "R1",
        "current_pick_index": 2,
        "status": "in_progress",
        "timer_deadline": time.time() + 10,
    }
    stale = build_solo_expire_token({**room, "current_pick_index": 1})
    st = mock.MagicMock()
    with mock.patch("live_draft_solo_expire_chain.solo_expire_owner", return_value="wake"):
        assert process_solo_component_wake(st, session, room, stale, delivery_via="on_change") is False


def test_duplicate_token_cannot_draft_twice() -> None:
    session: dict = {}
    room = {
        "draft_room_id": "R1",
        "current_pick_index": 0,
        "status": "in_progress",
        "timer_deadline": time.time() + 10,
    }
    token = build_solo_expire_token(room)
    session[SOLO_COMPONENT_WAKE_SEEN_KEY] = token
    st = mock.MagicMock()
    with mock.patch("live_draft_solo_expire_chain.solo_expire_owner", return_value="wake"):
        assert process_solo_component_wake(st, session, room, token, delivery_via="on_change") is False


def test_pause_idle_token_not_actionable() -> None:
    room = {
        "draft_room_id": "R1",
        "current_pick_index": 0,
        "status": "paused",
        "paused_remaining_seconds": 42,
        "config": {"draft_setup_mode": "solo", "timer_seconds": 60},
    }
    session = {"live_draft_setup_mode": "solo"}
    tok, props = expire_token_for_persistent_wake(session, room)
    assert tok == ""
    assert props.get("status") == "paused"


def test_solo_persistent_wake_active_requires_latch_and_wake_owner() -> None:
    from live_draft_solo_persistent_wake import SOLO_PERSISTENT_WAKE_LATCH_KEY

    session = {SOLO_PERSISTENT_WAKE_LATCH_KEY: True}
    with mock.patch("live_draft_solo_expire_chain.solo_expire_owner", return_value="wake"):
        assert solo_persistent_wake_active(session) is True
    with mock.patch("live_draft_solo_expire_chain.solo_expire_owner", return_value="fragment"):
        assert solo_persistent_wake_active(session) is False


def test_no_legacy_per_pick_key_in_persistent_module() -> None:
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "live_draft_solo_persistent_wake.py"
    text = src.read_text(encoding="utf-8")
    assert "current_pick_index" not in text.split("solo_persistent_wake_widget_key")[1][:200]
    assert "solo_countdown_wake_{draft_id}_{pick_index}" not in text


def test_resume_installs_fresh_deadline_token() -> None:
    deadline_paused = time.time() + 40
    room = {
        "draft_room_id": "R1",
        "current_pick_index": 0,
        "status": "in_progress",
        "timer_deadline": deadline_paused,
        "config": {"timer_seconds": 60, "draft_setup_mode": "solo"},
    }
    session = {"live_draft_setup_mode": "solo"}
    tok_before, _ = expire_token_for_persistent_wake(session, room)
    room_resumed = {
        **room,
        "timer_deadline": time.time() + 55,
        "timer_started_at": time.time(),
    }
    tok_after, _ = expire_token_for_persistent_wake(session, room_resumed)
    assert tok_before != tok_after
    assert float(parse_solo_expire_token(tok_after)["deadline"]) > float(
        parse_solo_expire_token(tok_before)["deadline"]
    )


def test_render_solo_expire_owner_skips_when_persistent_active() -> None:
    from live_draft_solo_heartbeat import render_solo_expire_owner

    session = {"_solo_persistent_wake_early_latch": True}
    st = mock.MagicMock()
    room = {"status": "in_progress", "config": {"draft_setup_mode": "solo"}}
    with mock.patch("live_draft_solo_persistent_wake.solo_persistent_wake_active", return_value=True):
        with mock.patch("live_draft_solo_heartbeat.render_solo_countdown_wake_component") as late:
            render_solo_expire_owner(st, session, room)
            late.assert_not_called()
