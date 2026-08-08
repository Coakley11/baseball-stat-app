"""Context isolation gate — setup aborts then Context Cases A–E."""

from __future__ import annotations

from typing import Any

ABORTED_FRAGMENT_CONTEXT_UI_NOT_EXPOSED = "ABORTED_FRAGMENT_CONTEXT_UI_NOT_EXPOSED"
ABORTED_FRAGMENT_CONTEXT_CLICK_OBSERVABILITY = "ABORTED_FRAGMENT_CONTEXT_CLICK_OBSERVABILITY"

CONTEXT_ORDER = ("C3", "C0", "C2", "C1")


def _step(by: dict[str, dict[str, Any]], control: str) -> dict[str, Any]:
    row = by.get(control) or {}
    return row if isinstance(row, dict) else {}


def classify_context_steps(
    steps: list[dict[str, Any]],
    *,
    expander: dict[str, Any] | None = None,
) -> tuple[str, str]:
    by = {str(s.get("control") or ""): s for s in steps if isinstance(s, dict)}

    if expander is not None and not expander.get("matrix_expander_open_after"):
        return ABORTED_FRAGMENT_CONTEXT_UI_NOT_EXPOSED, "context_expander_not_open"

    for ctrl in CONTEXT_ORDER:
        st = _step(by, ctrl)
        if st.get("setup_abort") == "UI_NOT_EXPOSED" or st.get("target_visible") is False:
            return ABORTED_FRAGMENT_CONTEXT_UI_NOT_EXPOSED, f"{ctrl}:not_visible"
        if not st.get("click_dispatched"):
            return ABORTED_FRAGMENT_CONTEXT_UI_NOT_EXPOSED, f"{ctrl}:click_not_dispatched"

    for ctrl in CONTEXT_ORDER:
        st = _step(by, ctrl)
        if st.get("click_dispatched") and not st.get("trusted_dom_click"):
            return ABORTED_FRAGMENT_CONTEXT_CLICK_OBSERVABILITY, f"{ctrl}:no_trusted_dom_click"

    def pass_(c: str) -> bool:
        return bool(_step(by, c).get("callback_entered"))

    c0, c1, c2, c3 = pass_("C0"), pass_("C1"), pass_("C2"), pass_("C3")

    if c0 and not c1 and c2 and c3:
        return "FRAGMENT_CONTEXT_CASE_A_EXPANDER_FRAGMENT", ""
    if c0 and c1 and c2 and c3:
        return "FRAGMENT_CONTEXT_CASE_B_ALL_PASS", ""
    if not c0 and c3:
        return "FRAGMENT_CONTEXT_CASE_C_TOP_FRAGMENT_FAIL", ""
    if not c0 and not c3:
        return "FRAGMENT_CONTEXT_CASE_D_TOP_ROUTING_FAIL", ""
    return "FRAGMENT_CONTEXT_MIXED_PARTIAL", ""


def recommended_context_fix(case: str) -> str:
    mapping = {
        ABORTED_FRAGMENT_CONTEXT_UI_NOT_EXPOSED: "Fix context probe visibility/expander harness before classification.",
        ABORTED_FRAGMENT_CONTEXT_CLICK_OBSERVABILITY: "Repair DOM capture; do not infer container vs fragment yet.",
        "FRAGMENT_CONTEXT_CASE_A_EXPANDER_FRAGMENT": "Fragment-in-expander container pattern is causal; avoid recommendation widgets inside collapsed expanders.",
        "FRAGMENT_CONTEXT_CASE_B_ALL_PASS": "Generic fragment + expander exonerated; compare matrix group mount/registration.",
        "FRAGMENT_CONTEXT_CASE_C_TOP_FRAGMENT_FAIL": "Minimal standalone Streamlit 1.59.1 fragment repro on Cloud.",
        "FRAGMENT_CONTEXT_CASE_D_TOP_ROUTING_FAIL": "Investigate Live Draft page widget routing (not fragment-specific).",
        "FRAGMENT_CONTEXT_CASE_E_MATRIX_GROUP_SPECIFIC": "Matrix multi-fragment mount/order likely causal vs container alone.",
    }
    return mapping.get(case, "Review C0–C3 callback table.")
