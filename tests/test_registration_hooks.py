"""Registration hook self-test and Gate A classification."""

from __future__ import annotations

from live_draft_streamlit_registration_hooks import (
    HOOKS_INSTALLED,
    REG_HOOK_ENTERED,
    discover_registration_runtime_map,
    run_local_case_a_hook_self_test,
)
from scripts.p8_callback_metadata_classify import (
    INVALID_CLOUD_REGISTRATION_HOOK_INSTALLATION,
    evaluate_case_a_gate_a,
)


def test_local_case_a_registration_hook_self_test() -> None:
    result = run_local_case_a_hook_self_test()
    assert result.get("ok") is True
    assert result.get("hooks_installed_count", 0) >= 1
    assert result.get("hook_entered_count", 0) >= 1


def test_discover_registration_runtime_map_has_targets() -> None:
    mapping = discover_registration_runtime_map()
    targets = mapping.get("targets") or {}
    assert "streamlit.runtime.state.widgets.register_widget" in targets or targets


def test_gate_a_invalid_cloud_hook_installation() -> None:
    peak = [
        {
            "event": "production_stage1_control_on_change_entered",
            "widget_key": "minimal_wake_repro_0",
            "expected_token": "repro|0|1.0",
            "callback_function_identity": "_on_change",
        },
        {
            "event": "production_stage1_callback_dispatch_evaluated",
            "diagnostic_surface": "case_a_control",
            "widget_key": "minimal_wake_repro_0",
            "widget_changed_result": True,
            "callback_selected": True,
            "metadata_callback_present": True,
            "new_value_repr": "repro|0|1.0",
            "authoritative_widget_id": "$$ID-x",
        },
        {"event": HOOKS_INSTALLED},
    ]
    gate = evaluate_case_a_gate_a(
        peak_rows=peak,
        case_a_delivery_proven=True,
        control_entered=[peak[0]],
        control_exited=[{"event": "production_stage1_control_on_change_exited"}],
        local_hook_self_test_ok=True,
    )
    assert gate.get("failure_boundary") == INVALID_CLOUD_REGISTRATION_HOOK_INSTALLATION
