"""Tests for Stage 1 widget identity snapshots."""

from __future__ import annotations

from live_draft_stage1_widget_identity import (
    predict_solo_countdown_component_element_id,
    record_declaration_registry_entry,
    latest_declaration_identity,
    declaration_supersede_after_ts,
)


def test_predict_widget_id_stable_for_key():
    a = predict_solo_countdown_component_element_id("solo_countdown_wake_solo_persistent")
    b = predict_solo_countdown_component_element_id("solo_countdown_wake_solo_persistent")
    assert a == b
    assert "solo_countdown_wake_solo_persistent" in a


def test_declaration_registry_supersede():
    session: dict = {}
    ts0 = 1000.0
    id0 = {
        "user_widget_key": "solo_countdown_wake_solo_persistent",
        "generated_internal_widget_id": "$$ID-abc-solo_countdown_wake_solo_persistent",
        "declaration_ts": ts0,
    }
    record_declaration_registry_entry(session, id0)
    id1 = {**id0, "declaration_ts": ts0 + 5, "generated_internal_widget_id": "$$ID-def-solo_countdown_wake_solo_persistent"}
    record_declaration_registry_entry(session, id1)
    latest = latest_declaration_identity(session, "solo_countdown_wake_solo_persistent")
    assert "def" in latest.get("generated_internal_widget_id", "")
    later = declaration_supersede_after_ts(session, "solo_countdown_wake_solo_persistent", after_ts=ts0 + 1)
    assert len(later) == 1
