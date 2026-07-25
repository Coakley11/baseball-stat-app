"""Micro-isolation diagnostic recorder (query-gated harness only)."""

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from live_draft_solo_delivery_diag import SOLO_DELIVERY_LOG_KEY
from live_draft_solo_placement_micro import _record_stage_factory


def test_record_stage_strips_reserved_keys_before_note_delivery_stage() -> None:
    session: dict = {}
    record = _record_stage_factory(session, "P1")
    record(
        "component_declaration_loaded",
        {
            "placement": "OVERRIDE",
            "micro_isolation": False,
            "stage": "wrong",
            "session": {"bad": True},
            "widget_key": "solo_countdown_wake_micro_p1",
            "component_name": "solo_countdown_wake",
        },
    )
    log = session[SOLO_DELIVERY_LOG_KEY]
    assert len(log) == 1
    row = log[0]
    assert row["stage"] == "component_declaration_loaded"
    assert row["placement"] == "P1"
    assert row["micro_isolation"] is True
    assert row["widget_key"] == "solo_countdown_wake_micro_p1"
    assert row["component_name"] == "solo_countdown_wake"
    assert "OVERRIDE" not in row.values()


def test_record_stage_accepts_none_fields() -> None:
    session: dict = {}
    record = _record_stage_factory(session, "P2A")
    record("micro_complete_frozen", None)
    row = session[SOLO_DELIVERY_LOG_KEY][0]
    assert row["placement"] == "P2A"
    assert row["micro_isolation"] is True


def test_micro_start_success_criteria() -> None:
    from solo_draft_start_harness import _micro_start_success

    flags = {
        "setup_page_disappeared": False,
        "success_toast_or_room_id": False,
        "room_in_progress": False,
    }
    seen: dict = {"room_id_detected": True, "micro_observation_active": False}
    state = {
        "room_id": "ABCD1234",
        "latch_probe": {"requested": "P2A"},
        "micro_probe": {
            "placement": "P2A",
            "key": "solo_countdown_wake_micro_p2a",
            "token": "DIAGP2A|0|1.0",
            "source": "live_draft_solo_placement_micro.try_micro_p2a_before_early_reconcile",
        },
    }
    assert _micro_start_success("P2A", flags, seen, state)


def test_p2a_readiness_post_create_active_room_allowed(monkeypatch) -> None:
    from live_draft_creation_trace import POST_CREATE_OPEN_KEY
    from live_draft_solo_p2a_path_diag import (
        p2a_allowance_note,
        p2a_defer_until_draft_surface,
        p2a_hook_ready_reason,
    )

    session = {POST_CREATE_OPEN_KEY: True}
    room = {"status": "in_progress", "draft_room_id": "330F831E"}
    monkeypatch.setattr(
        "live_draft_solo_p2a_path_diag._resolve_lifecycle", lambda _s, _r: "active_draft"
    )
    monkeypatch.setattr(
        "live_draft_solo_p2a_path_diag._solo_in_progress_room", lambda _s, _r: True
    )
    monkeypatch.setattr(
        "live_draft_solo_p2a_path_diag.current_micro_placement", lambda _st, _s: "P2A"
    )

    assert p2a_defer_until_draft_surface(session, room) is False
    assert p2a_allowance_note(session, room) == "post_create_open_but_active_room_allowed"
    assert p2a_hook_ready_reason(object(), session, room) == ""


def test_p2a_readiness_start_pending_defer(monkeypatch) -> None:
    from live_draft_solo_p2a_path_diag import p2a_hook_ready_reason

    session = {"_start_live_draft_pending": True}
    room = {"status": "in_progress"}
    monkeypatch.setattr(
        "live_draft_solo_p2a_path_diag.current_micro_placement", lambda _st, _s: "P2A"
    )
    assert p2a_hook_ready_reason(object(), session, room) == "start_pending"


def test_micro_isolation_persistent_never_stops() -> None:
    from solo_countdown_wake_micro_core import MicroCycleResult

    r = MicroCycleResult(
        widget_key="solo_countdown_wake_micro_bridge",
        token="DIAGBRIDGE|0|1.0",
        delivered=False,
        raw_received=False,
        on_change_fired=False,
        stages=[],
        should_stop=False,
    )
    assert r.should_stop is False
