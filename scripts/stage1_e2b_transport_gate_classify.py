"""E2B Pause-vs-sibling transport A/B classifications (T0–T4)."""

from __future__ import annotations

from typing import Any

BUTTON_DISPATCH_E2B_T0_TRANSPORT_OBSERVABILITY_ABORT = "BUTTON_DISPATCH_E2B_T0_TRANSPORT_OBSERVABILITY_ABORT"
BUTTON_DISPATCH_E2B_T1_CLIENT_WIDGET_ACTIVATION = "BUTTON_DISPATCH_E2B_T1_CLIENT_WIDGET_ACTIVATION"
BUTTON_DISPATCH_E2B_T2_SERVER_WIDGET_ROUTING = "BUTTON_DISPATCH_E2B_T2_SERVER_WIDGET_ROUTING"
BUTTON_DISPATCH_E2B_T3_WIDGET_STATE_NOT_TRIGGERED = "BUTTON_DISPATCH_E2B_T3_WIDGET_STATE_NOT_TRIGGERED"
BUTTON_DISPATCH_E2B_T4_NONDETERMINISTIC_DELIVERY = "BUTTON_DISPATCH_E2B_T4_NONDETERMINISTIC_DELIVERY"
BUTTON_DISPATCH_E2B_TRANSPORT_UNCLASSIFIED = "BUTTON_DISPATCH_E2B_TRANSPORT_UNCLASSIFIED"


def _backmsg_sent(transport: dict[str, Any] | None) -> bool | None:
    if not isinstance(transport, dict):
        return None
    if transport.get("transport_authority") == "unavailable":
        return None
    val = transport.get("streamlit_backmsg_sent")
    if val is None:
        return None
    return bool(val)


def classify_e2b_transport_ab(
    *,
    sibling_trusted_click: bool,
    sibling_transport: dict[str, Any],
    sibling_python_effect: bool,
    pause_trusted_click: bool,
    pause_transport: dict[str, Any],
    pause_resolved: bool,
    sibling_server_execution_hint: bool = False,
) -> tuple[str, str]:
    sib_bm = _backmsg_sent(sibling_transport)
    pause_bm = _backmsg_sent(pause_transport)

    if not sibling_trusted_click or not pause_trusted_click:
        return BUTTON_DISPATCH_E2B_TRANSPORT_UNCLASSIFIED, "missing_trusted_dom_click"

    if sib_bm is None or pause_bm is None:
        return BUTTON_DISPATCH_E2B_T0_TRANSPORT_OBSERVABILITY_ABORT, "transport_authority_unavailable"

    if sibling_python_effect:
        return BUTTON_DISPATCH_E2B_T4_NONDETERMINISTIC_DELIVERY, "sibling_counter_incremented"

    if not sib_bm and pause_bm and pause_resolved:
        return BUTTON_DISPATCH_E2B_T1_CLIENT_WIDGET_ACTIVATION, "sibling_no_backmsg_pause_backmsg"

    if sib_bm and pause_bm and not sibling_python_effect and pause_resolved:
        if sibling_server_execution_hint and not sibling_python_effect:
            return BUTTON_DISPATCH_E2B_T3_WIDGET_STATE_NOT_TRIGGERED, "backmsg_with_execution_no_button_true"
        return BUTTON_DISPATCH_E2B_T2_SERVER_WIDGET_ROUTING, "both_backmsg_sibling_no_python_effect"

    if sib_bm and not pause_bm:
        return BUTTON_DISPATCH_E2B_TRANSPORT_UNCLASSIFIED, "pause_backmsg_missing_control_anomaly"

    if not sib_bm and not pause_bm:
        return BUTTON_DISPATCH_E2B_T0_TRANSPORT_OBSERVABILITY_ABORT, "neither_backmsg_observed"

    return BUTTON_DISPATCH_E2B_TRANSPORT_UNCLASSIFIED, "pattern_not_matched"


def recommended_e2b_transport_fix(case: str) -> str:
    return {
        BUTTON_DISPATCH_E2B_T1_CLIENT_WIDGET_ACTIVATION: (
            "Sibling click does not produce Streamlit BackMsg — focus widget registration/identity (static key first)."
        ),
        BUTTON_DISPATCH_E2B_T2_SERVER_WIDGET_ROUTING: (
            "Sibling BackMsg sent but no session effect — compare widget/element IDs and server registry vs Pause."
        ),
        BUTTON_DISPATCH_E2B_T3_WIDGET_STATE_NOT_TRIGGERED: (
            "Inspect widget-state payload: widget ID, trigger value, fragment ID, stale generation."
        ),
        BUTTON_DISPATCH_E2B_T4_NONDETERMINISTIC_DELIVERY: "Reproduce transport gate before architecture changes.",
        BUTTON_DISPATCH_E2B_T0_TRANSPORT_OBSERVABILITY_ABORT: "Fix WS boundary hooks before T1/T2 inference.",
    }.get(case, "Review E2B transport artifact.")
