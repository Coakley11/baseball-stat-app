"""Two-tier Case A authority: dispatch vs registration trace."""

from __future__ import annotations

from scripts.p8_callback_metadata_classify import (
    CASE_A_DISPATCH_AUTHORITY_PASS,
    CASE_A_DISPATCH_AUTHORITY_PASS_WITH_REGISTRATION_TRACE_UNAVAILABLE,
    CM_REGISTRATION_CAUSE_UNRESOLVED,
    GATEA1,
    METADATA_AT_REGISTRATION,
    classify_callback_metadata_boundary,
    evaluate_case_a_gate_a,
)


def _control_entered(**extra: object) -> dict:
    base = {
        "event": "production_stage1_control_on_change_entered",
        "widget_key": "minimal_wake_repro_3",
        "expected_token": "repro|3|1.0",
        "callback_function_identity": "_on_change",
        "callback_source_module": "minimal_component_wake_repro_core",
        "diagnostic_run_id": "run123",
        "diagnostic_surface": "case_a_control",
        "session_state_value_repr": "'repro|3|1.0'",
    }
    base.update(extra)
    return base


def _control_exited(**extra: object) -> dict:
    base = {
        "event": "production_stage1_control_on_change_exited",
        "widget_key": "minimal_wake_repro_3",
        "session_state_value_at_exit_repr": "'repro|3|1.0'",
    }
    base.update(extra)
    return base


def _dispatch(**extra: object) -> dict:
    base = {
        "event": "production_stage1_widget_metadata_at_dispatch",
        "diagnostic_surface": "case_a_control",
        "widget_key": "minimal_wake_repro_3",
        "diagnostic_run_id": "run123",
        "authoritative_widget_id": "$$ID-abc-minimal_wake_repro_3",
        "metadata_callback_present": True,
        "callback_selected": True,
        "widget_changed_result": True,
        "new_value_repr": "'repro|3|1.0'",
        "callback_identity": "minimal_component_wake_repro_core._on_change",
    }
    base.update(extra)
    return base


def _replace_dispatch(peak: list[dict], **extra: object) -> list[dict]:
    return [
        _dispatch(**extra) if r.get("event") == "production_stage1_widget_metadata_at_dispatch" else r
        for r in peak
    ]


def _hooks_peak(*, include_meta: bool) -> list[dict]:
    control = _control_entered()
    peak = [
        {"event": "production_stage1_registration_hooks_installed"},
        {
            "event": "production_stage1_registration_hook_entered",
            "diagnostic_surface": "case_a_control",
        },
        control,
        _dispatch(),
        _control_exited(),
    ]
    if include_meta:
        peak.insert(
            3,
            {
                "event": METADATA_AT_REGISTRATION,
                "diagnostic_surface": "case_a_control",
                "widget_key": "minimal_wake_repro_3",
                "diagnostic_run_id": "run123",
                "metadata_callback_present": True,
                "metadata_callback_identity": "minimal_component_wake_repro_core._on_change",
                "authoritative_widget_id": "$$ID-abc-minimal_wake_repro_3",
            },
        )
    return peak


def test_dispatch_authority_without_registration_metadata_event() -> None:
    control = _control_entered()
    gate = evaluate_case_a_gate_a(
        peak_rows=_hooks_peak(include_meta=False),
        case_a_delivery_proven=True,
        control_entered=[control],
        control_exited=[_control_exited()],
        local_hook_self_test_ok=True,
    )
    assert gate.get("case_a_dispatch_authority") is True
    assert gate.get("case_a_registration_trace_available") is False
    assert gate.get("registration_trace_boundary") == GATEA1
    assert gate.get("authoritative") is False
    assert (
        gate.get("gate_a_outcome")
        == CASE_A_DISPATCH_AUTHORITY_PASS_WITH_REGISTRATION_TRACE_UNAVAILABLE
    )


def test_full_authoritative_when_registration_row_present() -> None:
    control = _control_entered()
    gate = evaluate_case_a_gate_a(
        peak_rows=_hooks_peak(include_meta=True),
        case_a_delivery_proven=True,
        control_entered=[control],
        control_exited=[_control_exited()],
        local_hook_self_test_ok=True,
    )
    assert gate.get("case_a_dispatch_authority") is True
    assert gate.get("case_a_registration_trace_available") is True
    assert gate.get("authoritative") is True
    assert gate.get("gate_a_outcome") == CASE_A_DISPATCH_AUTHORITY_PASS


def test_dispatch_fails_without_callback_at_dispatch() -> None:
    control = _control_entered()
    peak = _replace_dispatch(
        _hooks_peak(include_meta=False),
        metadata_callback_present=False,
        callback_selected=False,
        widget_changed_result=False,
    )
    gate = evaluate_case_a_gate_a(
        peak_rows=peak,
        case_a_delivery_proven=True,
        control_entered=[control],
        control_exited=[_control_exited()],
    )
    assert gate.get("case_a_dispatch_authority") is False


def test_dispatch_fails_on_callback_identity_mismatch() -> None:
    control = _control_entered()
    peak = _replace_dispatch(_hooks_peak(include_meta=False), callback_identity="other._on_change")
    gate = evaluate_case_a_gate_a(
        peak_rows=peak,
        case_a_delivery_proven=True,
        control_entered=[control],
        control_exited=[_control_exited()],
    )
    assert gate.get("case_a_dispatch_authority") is False


def test_dispatch_fails_when_widget_unchanged() -> None:
    control = _control_entered()
    peak = _replace_dispatch(_hooks_peak(include_meta=False), widget_changed_result=False)
    gate = evaluate_case_a_gate_a(
        peak_rows=peak,
        case_a_delivery_proven=True,
        control_entered=[control],
        control_exited=[_control_exited()],
    )
    assert gate.get("case_a_dispatch_authority") is False


def test_dispatch_fails_when_callback_not_selected() -> None:
    control = _control_entered()
    peak = _replace_dispatch(_hooks_peak(include_meta=False), callback_selected=False)
    gate = evaluate_case_a_gate_a(
        peak_rows=peak,
        case_a_delivery_proven=True,
        control_entered=[control],
        control_exited=[_control_exited()],
    )
    assert gate.get("case_a_dispatch_authority") is False


def test_dispatch_fails_without_callback_exit() -> None:
    control = _control_entered()
    gate = evaluate_case_a_gate_a(
        peak_rows=_hooks_peak(include_meta=False),
        case_a_delivery_proven=True,
        control_entered=[control],
        control_exited=[],
    )
    assert gate.get("case_a_dispatch_authority") is False


def test_cm1_blocked_without_registration_trace() -> None:
    rows = [
        {
            "event": "production_stage1_internal_widget_metadata_registered",
            "diagnostic_surface": "production",
            "widget_key": "solo_countdown_wake_solo_persistent",
            "application_on_change_argument_present": True,
            "metadata_callback_present": False,
        }
    ]
    out = classify_callback_metadata_boundary(
        filtered_rows=rows,
        exact_token="R|0|1.0",
        production_widget_key="solo_countdown_wake_solo_persistent",
    )
    assert out["classification"] == CM_REGISTRATION_CAUSE_UNRESOLVED


def test_cm1_allowed_with_registration_metadata_row() -> None:
    rows = [
        {
            "event": METADATA_AT_REGISTRATION,
            "diagnostic_surface": "production",
            "widget_key": "solo_countdown_wake_solo_persistent",
            "application_on_change_argument_present": True,
            "metadata_callback_present": False,
        }
    ]
    out = classify_callback_metadata_boundary(
        filtered_rows=rows,
        exact_token="R|0|1.0",
        production_widget_key="solo_countdown_wake_solo_persistent",
    )
    assert out["classification"].startswith("CM1")
