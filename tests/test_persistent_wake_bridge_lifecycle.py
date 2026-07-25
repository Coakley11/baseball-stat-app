"""Bridge vs production persistent wake lifecycle parity (unit)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def test_production_always_declares_at_early_entry_not_deferred_to_active() -> None:
    """b36026d deferred mount removed: setup must still call render_micro_isolation_once."""
    src = (ROOT / "live_draft_solo_persistent_wake.py").read_text(encoding="utf-8")
    assert "_actionable_solo_timer(session, room_dict):" not in src.split("try_solo_persistent_wake_ldr_entry")[1][:1200]
    assert "return True" in src.split("try_solo_persistent_wake_ldr_entry")[1]
    assert "render_micro_isolation_once(" in src.split("try_solo_persistent_wake_ldr_entry")[1]
    assert "SOLO_INERT_EXPIRE_TOKEN" in src


def test_bridge_declares_on_entry_without_actionable_gate() -> None:
    bridge = (ROOT / "live_draft_solo_early_bridge_diag.py").read_text(encoding="utf-8")
    assert "render_micro_isolation_once(" in bridge
    assert "_actionable_solo_timer" not in bridge


def test_resolve_persistent_wake_setup_is_inert_same_key() -> None:
    from live_draft_solo_persistent_wake import (
        SOLO_INERT_EXPIRE_TOKEN,
        SOLO_PERSISTENT_WAKE_WIDGET_KEY,
        resolve_persistent_wake_mount,
        solo_persistent_wake_widget_key,
    )

    session: dict = {"live_draft_setup_mode": "solo"}
    actionable, token, _props, phase = resolve_persistent_wake_mount(session, None)
    assert actionable is False
    assert token == SOLO_INERT_EXPIRE_TOKEN
    assert phase == "setup"
    assert solo_persistent_wake_widget_key(session) == SOLO_PERSISTENT_WAKE_WIDGET_KEY


def test_same_key_before_and_after_activation() -> None:
    import time

    from live_draft_solo_persistent_wake import (
        SOLO_PERSISTENT_WAKE_WIDGET_KEY,
        resolve_persistent_wake_mount,
        solo_persistent_wake_widget_key,
    )

    session = {"live_draft_setup_mode": "solo"}
    key_setup = solo_persistent_wake_widget_key(session)
    _a0, _t0, _, phase0 = resolve_persistent_wake_mount(session, None)
    room = {
        "draft_room_id": "ABCD1234",
        "current_pick_index": 0,
        "status": "in_progress",
        "timer_deadline": time.time() + 30,
        "config": {"draft_setup_mode": "solo", "timer_seconds": 30},
    }
    actionable, token, _, phase1 = resolve_persistent_wake_mount(session, room)
    key_active = solo_persistent_wake_widget_key(session)
    assert key_setup == key_active == SOLO_PERSISTENT_WAKE_WIDGET_KEY
    assert phase0 == "setup"
    assert phase1 == "active"
    assert actionable is True
    assert token and "|" in token


def test_actionable_hold_keeps_active_through_transient_inert() -> None:
    from live_draft_solo_persistent_wake import (
        SOLO_INERT_EXPIRE_TOKEN,
        SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY,
        SOLO_PERSISTENT_WAKE_TOKEN_KEY,
        _apply_actionable_hold,
        resolve_persistent_wake_mount,
    )

    session = {
        "live_draft_setup_mode": "solo",
        SOLO_PERSISTENT_WAKE_ACTIONABLE_KEY: True,
        SOLO_PERSISTENT_WAKE_TOKEN_KEY: "R1|0|100.000",
    }
    room = {
        "draft_room_id": "R1",
        "current_pick_index": 0,
        "status": "in_progress",
        "config": {"draft_setup_mode": "solo"},
    }
    a0, t0, props0, _ = resolve_persistent_wake_mount(session, room)
    assert a0 is True
    session[SOLO_PERSISTENT_WAKE_TOKEN_KEY] = t0
    _apply_actionable_hold(session, room, True, t0, props0, "active")
    held = _apply_actionable_hold(session, room, False, SOLO_INERT_EXPIRE_TOKEN, room, "setup")
    assert held[0] is True
    assert held[1] == t0


def test_pending_session_token_skips_inert_remount() -> None:
    from live_draft_solo_persistent_wake import (
        SOLO_PERSISTENT_WAKE_WIDGET_KEY,
        try_solo_persistent_wake_ldr_entry,
    )

    session: dict = {}
    st = mock.MagicMock()
    st.session_state = {SOLO_PERSISTENT_WAKE_WIDGET_KEY: "R1|0|100.000"}
    with mock.patch(
        "live_draft_solo_persistent_wake._should_mount_persistent_wake", return_value=True
    ):
        with mock.patch("solo_countdown_wake_micro_core.render_micro_isolation_once") as mount:
            assert try_solo_persistent_wake_ldr_entry(st, session, {}) is True
            assert mount.call_args.kwargs.get("production_actionable") is True
            assert mount.call_args.kwargs.get("production_expire_token") == "R1|0|100.000"


def test_try_persistent_wake_invokes_mount_on_setup() -> None:
    from live_draft_solo_persistent_wake import try_solo_persistent_wake_ldr_entry

    session: dict = {}
    st = mock.MagicMock()
    st.session_state = {}
    with mock.patch(
        "live_draft_solo_persistent_wake._should_mount_persistent_wake", return_value=True
    ):
        with mock.patch("solo_countdown_wake_micro_core.render_micro_isolation_once") as mount:
            assert try_solo_persistent_wake_ldr_entry(st, session, {}) is True
            mount.assert_called_once()
            kwargs = mount.call_args.kwargs
            assert kwargs.get("widget_key") == "solo_countdown_wake_solo_persistent"
            assert kwargs.get("production_actionable") is False
            assert kwargs.get("production_expire_token") == ""
