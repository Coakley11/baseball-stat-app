"""Pause-sibling localization gate — Case E1–E4."""

from __future__ import annotations

from typing import Any

ABORTED_PAUSE_SIBLING_UI = "ABORTED_PAUSE_SIBLING_UI_NOT_EXPOSED"
ABORTED_PAUSE_SIBLING_OBSERVABILITY = "ABORTED_PAUSE_SIBLING_OBSERVABILITY"
ABORTED_PAUSE_DELIVERY = "ABORTED_PAUSE_NOT_RESOLVED"

BUTTON_DISPATCH_E1_CONTROL_CENTER_OWNERSHIP_CAUSAL = "BUTTON_DISPATCH_E1_CONTROL_CENTER_OWNERSHIP_CAUSAL"
BUTTON_DISPATCH_E2_PAUSE_SPECIFIC_DIFFERENCE = "BUTTON_DISPATCH_E2_PAUSE_SPECIFIC_DIFFERENCE"
BUTTON_DISPATCH_E3_R0_UNSTABLE = "BUTTON_DISPATCH_E3_R0_UNSTABLE"
BUTTON_DISPATCH_E4_PAUSE_FAIL = "BUTTON_DISPATCH_E4_PAUSE_FAIL"


def classify_pause_sibling_run(
    *,
    pause_resolved: bool,
    sibling_pass: bool,
    sibling_trusted_click: bool,
    r0_optional_pass: bool | None,
    observability_abort: str = "",
) -> tuple[str, str]:
    if not pause_resolved:
        return BUTTON_DISPATCH_E4_PAUSE_FAIL, "pause_not_resolved"
    if observability_abort:
        return ABORTED_PAUSE_SIBLING_OBSERVABILITY, observability_abort
    if not sibling_trusted_click:
        return ABORTED_PAUSE_SIBLING_UI, "sibling_click_not_trusted"
    if sibling_pass:
        if r0_optional_pass is True:
            return BUTTON_DISPATCH_E3_R0_UNSTABLE, "sibling_and_r0_both_pass"
        return BUTTON_DISPATCH_E1_CONTROL_CENTER_OWNERSHIP_CAUSAL, "sibling_pass_r0_negative_boundary"
    return BUTTON_DISPATCH_E2_PAUSE_SPECIFIC_DIFFERENCE, "sibling_fail_pause_pass"


def recommended_pause_sibling_fix(case: str) -> str:
    return {
        BUTTON_DISPATCH_E1_CONTROL_CENTER_OWNERSHIP_CAUSAL: (
            "Return-value delivery works in Control Center fragment; relocate or re-own page-level diagnostics."
        ),
        BUTTON_DISPATCH_E2_PAUSE_SPECIFIC_DIFFERENCE: (
            "Compare Pause vs sibling: key lifetime, delta position, rerun handling, widget generation."
        ),
        BUTTON_DISPATCH_E3_R0_UNSTABLE: "Reproduce R0/sibling stability before architecture conclusions.",
        BUTTON_DISPATCH_E4_PAUSE_FAIL: "Fix Pause delivery before sibling localization.",
        ABORTED_PAUSE_SIBLING_OBSERVABILITY: "Fix sibling probe scrape/wait; not an ownership conclusion.",
        ABORTED_PAUSE_SIBLING_UI: "Sibling button not exposed to harness.",
    }.get(case, "Review pause-sibling artifact.")
