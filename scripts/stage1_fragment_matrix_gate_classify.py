"""Fragment identity matrix gate — setup vs observability vs architectural Cases I–V."""

from __future__ import annotations

from typing import Any

ABORTED_FRAGMENT_MATRIX_UI_NOT_EXPOSED = "ABORTED_FRAGMENT_MATRIX_UI_NOT_EXPOSED"
ABORTED_FRAGMENT_MATRIX_CLICK_OBSERVABILITY = "ABORTED_FRAGMENT_MATRIX_CLICK_OBSERVABILITY"

MATRIX_CONTROL_ORDER = ("S0", "S1", "D0", "D1")


def _step(by: dict[str, dict[str, Any]], control: str) -> dict[str, Any]:
    row = by.get(control) or {}
    return row if isinstance(row, dict) else {}


def classify_matrix_steps(
    steps: list[dict[str, Any]],
    *,
    expander: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Classify only after valid click evidence; never Case V without trusted S0 click."""
    by = {str(s.get("control") or ""): s for s in steps if isinstance(s, dict)}

    if expander is not None:
        if not expander.get("matrix_expander_found"):
            return ABORTED_FRAGMENT_MATRIX_UI_NOT_EXPOSED, "matrix_expander_not_found"
        if not expander.get("matrix_expander_open_after"):
            return ABORTED_FRAGMENT_MATRIX_UI_NOT_EXPOSED, "matrix_expander_not_open"

    for ctrl in MATRIX_CONTROL_ORDER:
        st = _step(by, ctrl)
        if st.get("setup_abort") == "UI_NOT_EXPOSED" or st.get("target_visible") is False:
            return ABORTED_FRAGMENT_MATRIX_UI_NOT_EXPOSED, f"{ctrl}:not_visible"
        if not st.get("click_dispatched"):
            return ABORTED_FRAGMENT_MATRIX_UI_NOT_EXPOSED, f"{ctrl}:click_not_dispatched"

    for ctrl in MATRIX_CONTROL_ORDER:
        st = _step(by, ctrl)
        if st.get("click_dispatched") and not st.get("trusted_dom_click"):
            return ABORTED_FRAGMENT_MATRIX_CLICK_OBSERVABILITY, f"{ctrl}:no_trusted_dom_click"

    def callback_pass(c: str) -> bool:
        return bool(_step(by, c).get("callback_entered"))

    s0, s1, d0, d1 = callback_pass("S0"), callback_pass("S1"), callback_pass("D0"), callback_pass("D1")

    subcodes: list[str] = []
    for c in MATRIX_CONTROL_ORDER:
        own = _step(by, c).get("pre_click_ownership") or {}
        if isinstance(own, dict) and own.get("ownership_subcode") == "FRAGMENT_WIDGET_OWNER_STALE":
            subcodes.append(f"{c}:FRAGMENT_WIDGET_OWNER_STALE")
    ownership_note = ";".join(subcodes) if subcodes else ""

    s0_step = _step(by, "S0")
    if s0_step.get("trusted_dom_click") and not s0:
        return "FRAGMENT_MATRIX_CASE_V_S0_FAIL", ownership_note
    if s0 and s1 and not d0 and not d1:
        return "FRAGMENT_MATRIX_CASE_I_DYNAMIC_CONSTRUCTION", ownership_note
    if s0 and not s1 and d0 and not d1:
        return "FRAGMENT_MATRIX_CASE_II_RUN_EVERY", ownership_note
    if s0 and s1 and d0 and not d1:
        return "FRAGMENT_MATRIX_CASE_III_DYNAMIC_PLUS_TIMER", ownership_note
    if s0 and s1 and d0 and d1:
        return "FRAGMENT_MATRIX_CASE_IV_ALL_PASS", ownership_note
    return "FRAGMENT_MATRIX_MIXED_PARTIAL", ownership_note


def recommended_next_fix(case: str) -> str:
    mapping = {
        ABORTED_FRAGMENT_MATRIX_UI_NOT_EXPOSED: "Fix matrix expander exposure in harness (or solo-diag expanded=True) before architectural classification.",
        ABORTED_FRAGMENT_MATRIX_CLICK_OBSERVABILITY: "Repair isolated DOM capture / target binding; do not infer fragment architecture yet.",
        "FRAGMENT_MATRIX_CASE_I_DYNAMIC_CONSTRUCTION": "Replace dynamic fragment(run_every)(nested)() with stable module-level @st.fragment for live widgets.",
        "FRAGMENT_MATRIX_CASE_II_RUN_EVERY": "Remove run_every=1 from interactive fragment; isolate timer refresh from widget registration.",
        "FRAGMENT_MATRIX_CASE_III_DYNAMIC_PLUS_TIMER": "Stable module-level fragment + drop run_every on interactive surface (matches recommendation wrapper).",
        "FRAGMENT_MATRIX_CASE_IV_ALL_PASS": "Compare recommendation fragment mount/ownership vs D1; do not change generic fragment architecture yet.",
        "FRAGMENT_MATRIX_CASE_V_S0_FAIL": "Stop recommendation refactor; build minimal Streamlit 1.59.1 fragment reproduction.",
    }
    return mapping.get(case, "Review per-control ownership table before architecture change.")
