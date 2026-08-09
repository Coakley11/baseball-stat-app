"""Pause-sibling PRE/POST Pause order gate — E2 ORDER A–E."""

from __future__ import annotations

ABORTED_PAUSE_SIBLING_ORDER_INCOMPLETE = "ABORTED_PAUSE_SIBLING_ORDER_INCOMPLETE"
ABORTED_PAUSE_SIBLING_ORDER_SETUP = "ABORTED_PAUSE_SIBLING_ORDER_SETUP"
ABORTED_PAUSE_SIBLING_LEDGER = "ABORTED_PAUSE_SIBLING_LEDGER_NOT_EXPOSED"

BUTTON_DISPATCH_E2A_POST_PAUSE_GENERATION_CAUSAL = "BUTTON_DISPATCH_E2A_POST_PAUSE_GENERATION_CAUSAL"
BUTTON_DISPATCH_E2B_PAUSE_WIDGET_SPECIFIC = "BUTTON_DISPATCH_E2B_PAUSE_WIDGET_SPECIFIC"
BUTTON_DISPATCH_E2C_SIBLING_DELIVERY_NOT_STABLY_BROKEN = "BUTTON_DISPATCH_E2C_SIBLING_DELIVERY_NOT_STABLY_BROKEN"
BUTTON_DISPATCH_E2D_PAUSE_FAIL_ABORT = "BUTTON_DISPATCH_E2D_PAUSE_FAIL_ABORT"
BUTTON_DISPATCH_E2E_SETUP_ABORT = "BUTTON_DISPATCH_E2E_SETUP_ABORT"
BUTTON_DISPATCH_E2_ORDER_UNCLASSIFIED = "BUTTON_DISPATCH_E2_ORDER_UNCLASSIFIED"


def classify_pause_sibling_order(
    *,
    pre_pass: bool | None,
    pause_resolved: bool,
    post_pass: bool | None,
    pre_evaluated: bool = True,
    post_evaluated: bool = True,
    setup_abort: str = "",
) -> tuple[str, str]:
    if setup_abort:
        return ABORTED_PAUSE_SIBLING_ORDER_SETUP, setup_abort
    if pre_pass is False and not pause_resolved:
        return BUTTON_DISPATCH_E2E_SETUP_ABORT, "pre_fail_and_pause_fail"
    if pre_pass is True and not pause_resolved:
        return BUTTON_DISPATCH_E2D_PAUSE_FAIL_ABORT, "pre_pass_pause_fail"
    if not pause_resolved:
        return BUTTON_DISPATCH_E2D_PAUSE_FAIL_ABORT, "pause_not_resolved"
    if not pre_evaluated or not post_evaluated:
        return ABORTED_PAUSE_SIBLING_ORDER_INCOMPLETE, "pre_or_post_not_evaluated"
    if pre_pass is None or post_pass is None:
        return ABORTED_PAUSE_SIBLING_ORDER_INCOMPLETE, "missing_pre_or_post_pass"
    if pre_pass and post_pass:
        return BUTTON_DISPATCH_E2C_SIBLING_DELIVERY_NOT_STABLY_BROKEN, "pre_and_post_pass"
    if pre_pass and not post_pass:
        return BUTTON_DISPATCH_E2A_POST_PAUSE_GENERATION_CAUSAL, "pre_pass_post_fail"
    if not pre_pass and not post_pass:
        return BUTTON_DISPATCH_E2B_PAUSE_WIDGET_SPECIFIC, "pre_fail_post_fail"
    # PRE fail, POST pass — prior failure not stable
    return BUTTON_DISPATCH_E2C_SIBLING_DELIVERY_NOT_STABLY_BROKEN, "pre_fail_post_pass_reproduce"


def recommended_pause_sibling_order_fix(case: str) -> str:
    return {
        BUTTON_DISPATCH_E2A_POST_PAUSE_GENERATION_CAUSAL: (
            "Sibling delivers before Pause; fails after Pause rerun — inspect Pause transition and post-Pause widget generation."
        ),
        BUTTON_DISPATCH_E2B_PAUSE_WIDGET_SPECIFIC: (
            "Sibling fails before and after Pause while Pause works — begin Pause-vs-sibling micro-diff (keys, placement, help, disabled)."
        ),
        BUTTON_DISPATCH_E2C_SIBLING_DELIVERY_NOT_STABLY_BROKEN: (
            "Reproduce sibling order gate once more before architecture conclusions."
        ),
        BUTTON_DISPATCH_E2D_PAUSE_FAIL_ABORT: (
            "Restore Pause delivery before order comparison."
        ),
        BUTTON_DISPATCH_E2E_SETUP_ABORT: (
            "Fix session/setup (auth, start, sibling ledger) before E2 order comparison."
        ),
    }.get(case, "Review pause-sibling order artifact.")
