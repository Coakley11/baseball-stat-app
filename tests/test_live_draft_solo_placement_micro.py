"""Micro-isolation diagnostic recorder (query-gated harness only)."""

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
