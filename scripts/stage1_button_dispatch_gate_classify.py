"""Button dispatch gate — Dispatch Cases A–E and observability aborts."""

from __future__ import annotations

from typing import Any

ABORTED_BUTTON_DISPATCH_UI_NOT_EXPOSED = "ABORTED_BUTTON_DISPATCH_UI_NOT_EXPOSED"
ABORTED_BUTTON_DISPATCH_CLICK_OBSERVABILITY = "ABORTED_BUTTON_DISPATCH_CLICK_OBSERVABILITY"
ABORTED_BUTTON_DISPATCH_LEDGER_NOT_EXPOSED = "ABORTED_BUTTON_DISPATCH_LEDGER_NOT_EXPOSED"
ABORTED_BUTTON_DISPATCH_OBSERVABILITY = "ABORTED_BUTTON_DISPATCH_OBSERVABILITY"
DISPATCH_LEDGER_DOM_NOT_OBSERVED = "DISPATCH_LEDGER_DOM_NOT_OBSERVED"
DISPATCH_PROBE_LOST_AFTER_RERUN = "DISPATCH_PROBE_LOST_AFTER_RERUN"

DISPATCH_ORDER = ("R0", "O0", "O1", "O2")


def _step(by: dict[str, dict[str, Any]], mode: str) -> dict[str, Any]:
    row = by.get(mode) or {}
    return row if isinstance(row, dict) else {}


def classify_dispatch_gate_report(
    report: dict[str, Any],
    steps: list[dict[str, Any]],
    *,
    pause_resolved: bool,
    ledger_before_r0: dict[str, Any] | None,
) -> tuple[str, str]:
    pre = ledger_before_r0 or report.get("dispatch_ledger_before_r0") or {}
    if not pre.get("probe_found"):
        return ABORTED_BUTTON_DISPATCH_LEDGER_NOT_EXPOSED, "ledger_not_visible_before_r0"

    by = {str(s.get("mode") or ""): s for s in steps if isinstance(s, dict)}

    for mode in DISPATCH_ORDER:
        st = _step(by, mode)
        if st.get("observability_abort") == DISPATCH_PROBE_LOST_AFTER_RERUN:
            return ABORTED_BUTTON_DISPATCH_OBSERVABILITY, f"{mode}:probe_lost_after_rerun"
        if st.get("observability_abort"):
            return ABORTED_BUTTON_DISPATCH_OBSERVABILITY, f"{mode}:{st.get('observability_abort')}"

    for mode in DISPATCH_ORDER:
        st = _step(by, mode)
        if not st:
            continue
        if st.get("setup_abort") == "UI_NOT_EXPOSED" or st.get("target_visible") is False:
            return ABORTED_BUTTON_DISPATCH_UI_NOT_EXPOSED, f"{mode}:not_visible"
        if st.get("click_dispatched") is False and mode in by:
            return ABORTED_BUTTON_DISPATCH_UI_NOT_EXPOSED, f"{mode}:click_not_dispatched"

    for mode in DISPATCH_ORDER:
        st = _step(by, mode)
        if st.get("click_dispatched") and not st.get("trusted_dom_click"):
            return ABORTED_BUTTON_DISPATCH_CLICK_OBSERVABILITY, f"{mode}:no_trusted_dom_click"

    for mode in DISPATCH_ORDER:
        st = _step(by, mode)
        delta = st.get("dispatch_delta") if isinstance(st.get("dispatch_delta"), dict) else {}
        if delta.get("observability_abort"):
            return ABORTED_BUTTON_DISPATCH_OBSERVABILITY, f"{mode}:{delta.get('observability_abort')}"

    if len(by) < 4:
        return ABORTED_BUTTON_DISPATCH_UI_NOT_EXPOSED, "incomplete_control_sequence"

    def passed(mode: str) -> bool:
        return bool(_step(by, mode).get("dispatch_pass"))

    r0, o0, o1, o2 = passed("R0"), passed("O0"), passed("O1"), passed("O2")

    if pause_resolved and not r0:
        return "BUTTON_DISPATCH_CASE_E_R0_FAIL_PAUSE_PASS", "return_value_probe_failed_while_pause_passed"

    if r0 and not o0 and not o1 and not o2:
        return "BUTTON_DISPATCH_CASE_A_ON_CLICK_FAIL", ""
    if r0 and o0 and o1 and not o2:
        return "BUTTON_DISPATCH_CASE_B_CLOSURE_FAIL", ""
    if r0 and o0 and not o1:
        return "BUTTON_DISPATCH_CASE_C_ARGS_FAIL", ""
    if r0 and o0 and o1 and o2:
        return "BUTTON_DISPATCH_CASE_D_ALL_PASS", ""
    return "BUTTON_DISPATCH_MIXED_PARTIAL", ""


def classify_dispatch_steps(
    steps: list[dict[str, Any]],
    *,
    pause_resolved: bool,
    ledger_before_r0: dict[str, Any] | None = None,
) -> tuple[str, str]:
    return classify_dispatch_gate_report(
        {},
        steps,
        pause_resolved=pause_resolved,
        ledger_before_r0=ledger_before_r0,
    )


def recommended_dispatch_fix(case: str) -> str:
    mapping = {
        ABORTED_BUTTON_DISPATCH_UI_NOT_EXPOSED: "Fix dispatch probe visibility/harness before classification.",
        ABORTED_BUTTON_DISPATCH_CLICK_OBSERVABILITY: "Repair DOM capture; do not infer on_click vs return-value yet.",
        ABORTED_BUTTON_DISPATCH_LEDGER_NOT_EXPOSED: "Dispatch ledger DOM not in app frame before R0; fix mount/scrape frame.",
        ABORTED_BUTTON_DISPATCH_OBSERVABILITY: "Harness could not read authoritative dispatch ledger; not a dispatch mechanism result.",
        DISPATCH_LEDGER_DOM_NOT_OBSERVED: "Dedicated dispatch ledger never observed in app frame.",
        DISPATCH_PROBE_LOST_AFTER_RERUN: "Dispatch probe lost after rerun; surface continuity issue, not callback failure.",
        "BUTTON_DISPATCH_CASE_A_ON_CLICK_FAIL": (
            "on_click execution is the differentiator; next minimal test is Francisco return-value wiring under solo diag."
        ),
        "BUTTON_DISPATCH_CASE_B_CLOSURE_FAIL": "Nested closure on_click registration is causal; compare Francisco callback shape.",
        "BUTTON_DISPATCH_CASE_C_ARGS_FAIL": "Callback args registration/shape is causal; inspect Francisco callback args.",
        "BUTTON_DISPATCH_CASE_D_ALL_PASS": (
            "Callback mechanics exonerated for this mount; prior C3 failure was instrumentation/mount-specific."
        ),
        "BUTTON_DISPATCH_CASE_E_R0_FAIL_PAUSE_PASS": (
            "Compare render ownership/container between Pause and page-level return-value probe."
        ),
    }
    return mapping.get(case, "Review R0/O0/O1/O2 dispatch table.")
