"""Strict Gate A registration metadata selection (classifier-only)."""

from __future__ import annotations

from scripts.p8_callback_metadata_classify import (
    METADATA_AT_REGISTRATION,
    evaluate_case_a_gate_a,
    select_authoritative_metadata_at_registration,
)


def _control_entered(**extra: object) -> dict:
    base = {
        "event": "production_stage1_control_on_change_entered",
        "widget_key": "minimal_wake_repro_3",
        "expected_token": "repro|3|1785598916.972",
        "callback_function_identity": "_on_change",
        "diagnostic_run_id": "run123",
        "run_id": "run123",
        "diagnostic_surface": "case_a_control",
    }
    base.update(extra)
    return base


def _meta_at_reg(**extra: object) -> dict:
    base = {
        "event": METADATA_AT_REGISTRATION,
        "diagnostic_surface": "case_a_control",
        "widget_key": "minimal_wake_repro_3",
        "diagnostic_run_id": "run123",
        "run_id": "run123",
        "metadata_callback_present": True,
        "metadata_callback_identity": "minimal_component_wake_repro_core._on_change",
        "authoritative_widget_id": "$$ID-abc-minimal_wake_repro_3",
    }
    base.update(extra)
    return base


def _dispatch_ref() -> dict:
    return {
        "event": "production_stage1_widget_metadata_at_dispatch",
        "diagnostic_surface": "case_a_control",
        "widget_key": "minimal_wake_repro_3",
        "diagnostic_run_id": "run123",
        "authoritative_widget_id": "$$ID-abc-minimal_wake_repro_3",
        "metadata_callback_present": True,
        "callback_selected": True,
        "widget_changed_result": True,
        "new_value_repr": "'repro|3|1785598916.972'",
        "callback_identity": "minimal_component_wake_repro_core._on_change",
    }


def test_select_authoritative_metadata_at_registration_passes() -> None:
    peak = [_meta_at_reg()]
    control = [_control_entered()]
    row, audit = select_authoritative_metadata_at_registration(
        peak_rows=peak,
        control_entered=control,
        dispatch_reference=_dispatch_ref(),
    )
    assert audit.get("ok") is True
    assert row.get("metadata_callback_present") is True


def test_select_rejects_wrong_widget_key() -> None:
    peak = [_meta_at_reg(widget_key="minimal_wake_repro_0")]
    row, audit = select_authoritative_metadata_at_registration(
        peak_rows=peak,
        control_entered=[_control_entered()],
        dispatch_reference=_dispatch_ref(),
    )
    assert not row
    assert audit.get("ok") is False


def test_select_rejects_production_surface() -> None:
    peak = [_meta_at_reg(diagnostic_surface="production")]
    row, audit = select_authoritative_metadata_at_registration(
        peak_rows=peak,
        control_entered=[_control_entered()],
        dispatch_reference=_dispatch_ref(),
    )
    assert not row
    assert audit.get("ok") is False


def test_select_rejects_identity_only_without_metadata_flag() -> None:
    peak = [
        _meta_at_reg(
            metadata_callback_present=False,
            metadata_callback_identity="minimal_component_wake_repro_core._on_change",
        )
    ]
    row, audit = select_authoritative_metadata_at_registration(
        peak_rows=peak,
        control_entered=[_control_entered()],
        dispatch_reference=_dispatch_ref(),
    )
    assert not row
    assert audit.get("ok") is False


def test_gate_a_authoritative_with_metadata_at_registration() -> None:
    control = _control_entered()
    dispatch = _dispatch_ref()
    peak = [
        control,
        _meta_at_reg(),
        dispatch,
        {"event": "production_stage1_registration_hooks_installed"},
        {"event": "production_stage1_registration_hook_entered", "diagnostic_surface": "case_a_control"},
        {"event": "production_stage1_control_on_change_exited"},
    ]
    gate = evaluate_case_a_gate_a(
        peak_rows=peak,
        case_a_delivery_proven=True,
        control_entered=[control],
        control_exited=[{"event": "production_stage1_control_on_change_exited"}],
        local_hook_self_test_ok=True,
    )
    assert gate.get("authoritative") is True
    assert gate.get("checks", {}).get("registration_callback_present") is True
