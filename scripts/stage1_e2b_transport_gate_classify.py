"""Relaxed E2B transport classifier — non-authoritative; superseded by strict BackMsg decode."""

from __future__ import annotations

from typing import Any

from stage1_e2b_strict_backmsg_classify import BUTTON_DISPATCH_E2B_T0_STRICT_WIDGET_STATE_UNRESOLVED

# Deprecated — do not use for production conclusions.
BUTTON_DISPATCH_E2B_T0_TRANSPORT_OBSERVABILITY_ABORT = "BUTTON_DISPATCH_E2B_T0_TRANSPORT_OBSERVABILITY_ABORT"
BUTTON_DISPATCH_E2B_T1_CLIENT_WIDGET_ACTIVATION = "BUTTON_DISPATCH_E2B_T1_CLIENT_WIDGET_ACTIVATION"
BUTTON_DISPATCH_E2B_T2_SERVER_WIDGET_ROUTING = "BUTTON_DISPATCH_E2B_T2_SERVER_WIDGET_ROUTING"
BUTTON_DISPATCH_E2B_T3_WIDGET_STATE_NOT_TRIGGERED = "BUTTON_DISPATCH_E2B_T3_WIDGET_STATE_NOT_TRIGGERED"
BUTTON_DISPATCH_E2B_T4_NONDETERMINISTIC_DELIVERY = "BUTTON_DISPATCH_E2B_T4_NONDETERMINISTIC_DELIVERY"


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
    """
    Legacy relaxed classifier. Any conclusion besides observability abort defers to
    ``BUTTON_DISPATCH_E2B_T0_STRICT_WIDGET_STATE_UNRESOLVED`` — run strict BackMsg gate.
    """
    strict_s = dict(sibling_transport.get("strict_backmsg") or {})
    strict_p = dict(pause_transport.get("strict_backmsg") or {})
    if strict_s.get("protobuf_decode_available") and strict_p.get("protobuf_decode_available"):
        from stage1_e2b_strict_backmsg_classify import classify_strict_backmsg_ab

        return classify_strict_backmsg_ab(
            sibling_strict=strict_s,
            pause_strict=strict_p,
            sibling_python_effect=sibling_python_effect,
            pause_resolved=pause_resolved,
        )

    if not sibling_trusted_click or not pause_trusted_click:
        return BUTTON_DISPATCH_E2B_T0_TRANSPORT_OBSERVABILITY_ABORT, "missing_trusted_dom_click"

    sib_bm = sibling_transport.get("streamlit_backmsg_sent")
    pause_bm = pause_transport.get("streamlit_backmsg_sent")
    if sib_bm is None or pause_bm is None:
        return BUTTON_DISPATCH_E2B_T0_TRANSPORT_OBSERVABILITY_ABORT, "transport_authority_unavailable"

    if sibling_python_effect:
        return BUTTON_DISPATCH_E2B_T4_NONDETERMINISTIC_DELIVERY, "sibling_counter_relaxed_path"

    # Relaxed outbound/component heuristics cannot authorize T1–T3.
    return BUTTON_DISPATCH_E2B_T0_STRICT_WIDGET_STATE_UNRESOLVED, "relaxed_grader_insufficient_run_strict_gate"


def recommended_e2b_transport_fix(case: str) -> str:
    from stage1_e2b_strict_backmsg_classify import recommended_strict_backmsg_fix

    return recommended_strict_backmsg_fix(case)
