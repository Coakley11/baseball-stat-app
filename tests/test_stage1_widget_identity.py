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


def test_snapshot_separates_predicted_and_actual():
    from live_draft_stage1_widget_identity import stage1_widget_identity_snapshot

    session: dict = {"_solo_stage1_script_run_seq": 1, "active_page": "Live Draft Room"}
    snap = stage1_widget_identity_snapshot(
        None,
        session,
        user_key="solo_countdown_wake_solo_persistent",
        after_mount=False,
    )
    assert snap.get("predicted_element_id")
    assert snap.get("registered_widget_id_authority") in (
        "predicted_id_pre_mount",
        "predicted_id",
        "missing",
    )
    assert "actual_registered_widget_id" in snap


def test_declaration_registry_supersede():
    session: dict = {}
    ts0 = 1000.0
    id0 = {
        "user_widget_key": "solo_countdown_wake_solo_persistent",
        "generated_internal_widget_id": "$$ID-abc-solo_countdown_wake_solo_persistent",
        "declaration_ts": ts0,
    }
    record_declaration_registry_entry(session, id0)
    id1 = {
        **id0,
        "declaration_ts": ts0 + 5,
        "predicted_element_id": "$$ID-def-solo_countdown_wake_solo_persistent",
        "actual_registered_widget_id": "$$ID-def-solo_countdown_wake_solo_persistent",
    }
    record_declaration_registry_entry(session, id1)
    latest = latest_declaration_identity(session, "solo_countdown_wake_solo_persistent")
    assert "def" in latest.get("actual_registered_widget_id", "")
    later = declaration_supersede_after_ts(session, "solo_countdown_wake_solo_persistent", after_ts=ts0 + 1)
    assert len(later) == 1
