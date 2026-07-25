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
