"""Strict E2B BackMsg classifications S0–S4 (protobuf-authoritative)."""

from __future__ import annotations

from typing import Any

# Prior relaxed transport run (fb0deff / T3) is NOT authoritative — use this label instead.
BUTTON_DISPATCH_E2B_T0_STRICT_WIDGET_STATE_UNRESOLVED = "BUTTON_DISPATCH_E2B_T0_STRICT_WIDGET_STATE_UNRESOLVED"

BUTTON_DISPATCH_E2B_S0_PROTO_OBSERVABILITY_ABORT = "BUTTON_DISPATCH_E2B_S0_PROTO_OBSERVABILITY_ABORT"
BUTTON_DISPATCH_E2B_S1_NATIVE_RERUN_NOT_SENT = "BUTTON_DISPATCH_E2B_S1_NATIVE_RERUN_NOT_SENT"
BUTTON_DISPATCH_E2B_S2_TRIGGER_STATE_NOT_ENCODED = "BUTTON_DISPATCH_E2B_S2_TRIGGER_STATE_NOT_ENCODED"
BUTTON_DISPATCH_E2B_S3_TRIGGER_SENT_SERVER_NOT_APPLIED = "BUTTON_DISPATCH_E2B_S3_TRIGGER_SENT_SERVER_NOT_APPLIED"
BUTTON_DISPATCH_E2B_S4_NONDETERMINISTIC_DELIVERY = "BUTTON_DISPATCH_E2B_S4_NONDETERMINISTIC_DELIVERY"


def classify_strict_backmsg_ab(
    *,
    sibling_strict: dict[str, Any],
    pause_strict: dict[str, Any],
    sibling_python_effect: bool,
    pause_resolved: bool,
) -> tuple[str, str]:
    if not sibling_strict.get("protobuf_decode_available") or not pause_strict.get("protobuf_decode_available"):
        return BUTTON_DISPATCH_E2B_S0_PROTO_OBSERVABILITY_ABORT, "protobuf_or_payload_capture_unavailable"

    s_rerun = bool(sibling_strict.get("rerun_script_backmsg_seen"))
    p_rerun = bool(pause_strict.get("rerun_script_backmsg_seen"))
    s_act = bool(sibling_strict.get("activated_widget_state_present"))

    if sibling_python_effect:
        return BUTTON_DISPATCH_E2B_S4_NONDETERMINISTIC_DELIVERY, "sibling_counter_incremented"

    if not s_rerun and p_rerun and pause_resolved:
        return BUTTON_DISPATCH_E2B_S1_NATIVE_RERUN_NOT_SENT, "pause_rerun_script_sibling_none"

    if s_rerun and not s_act:
        return BUTTON_DISPATCH_E2B_S2_TRIGGER_STATE_NOT_ENCODED, "rerun_without_trigger_widget_state"

    if s_rerun and s_act and not sibling_python_effect:
        return BUTTON_DISPATCH_E2B_S3_TRIGGER_SENT_SERVER_NOT_APPLIED, "trigger_present_no_session_effect"

    if not s_rerun and not p_rerun:
        return BUTTON_DISPATCH_E2B_S0_PROTO_OBSERVABILITY_ABORT, "no_rerun_script_either_side"

    return BUTTON_DISPATCH_E2B_S0_PROTO_OBSERVABILITY_ABORT, "strict_pattern_unresolved"


def recommended_strict_backmsg_fix(case: str) -> str:
    return {
        BUTTON_DISPATCH_E2B_S1_NATIVE_RERUN_NOT_SENT: (
            "Sibling WS traffic is not a rerun_script BackMsg — client widget activation/registration (static key next)."
        ),
        BUTTON_DISPATCH_E2B_S2_TRIGGER_STATE_NOT_ENCODED: (
            "rerun_script without trigger WidgetState — frontend widget ID/state generation."
        ),
        BUTTON_DISPATCH_E2B_S3_TRIGGER_SENT_SERVER_NOT_APPLIED: (
            "Triggered WidgetState on wire but no Python effect — server registry / fragment ownership vs widget ID."
        ),
        BUTTON_DISPATCH_E2B_S4_NONDETERMINISTIC_DELIVERY: "Reproduce strict decode gate before architecture changes.",
        BUTTON_DISPATCH_E2B_S0_PROTO_OBSERVABILITY_ABORT: "Fix payload capture/protobuf decode; no S1–S3 inference.",
        BUTTON_DISPATCH_E2B_T0_STRICT_WIDGET_STATE_UNRESOLVED: (
            "Relaxed transport grader could not prove sibling WidgetState — rerun with strict protobuf gate."
        ),
    }.get(case, "Review strict BackMsg artifact.")
