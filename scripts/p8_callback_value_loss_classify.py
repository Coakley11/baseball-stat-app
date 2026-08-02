"""VALUE1–VALUE10 callback/post-callback value-loss classification (harness)."""

from __future__ import annotations

from typing import Any

VALUE1 = "VALUE1 — CALLBACK_EXPLICITLY_CLEARS_WIDGET_KEY"
VALUE2 = "VALUE2 — CALLBACK_HELPER_CLEARS_VALUE"
VALUE3 = "VALUE3 — TOKEN_COPIED_BUT_WRAPPER_READS_WRONG_KEY"
VALUE4 = "VALUE4 — STREAMLIT_FRAMEWORK_CLEARS_TRIGGER_STATE_AFTER_CALLBACK"
VALUE5 = "VALUE5 — WRAPPER_NORMALIZATION_CONVERTS_TOKEN_TO_EMPTY"
VALUE6 = "VALUE6 — RAW_RETURN_CACHE_OVERWRITES_TOKEN"
VALUE7 = "VALUE7 — CALLBACK_AND_WRAPPER_RUN_ORDER_MISMATCH"
VALUE8 = "VALUE8 — CALLBACK_RERUN_OR_EARLY_EXIT_PREVENTS_CONSUMPTION"
VALUE9 = "VALUE9 — TRANSIENT_TRIGGER_REQUIRES_CALLBACK_HANDOFF"
VALUE10 = "VALUE10 — OTHER"
VALUE_PENDING = (
    "VALUE_CLASSIFICATION_PENDING — INSUFFICIENT_LIFECYCLE_LEDGER_EVIDENCE"
)

MUTATION_EVENT = "production_stage1_session_state_mutation"
VALUE_OP_EVENT = "production_stage1_prod_on_change_value_op"
HANDOFF_EVENT = "production_stage1_post_callback_handoff_boundary"
SNAPSHOT_EVENT = "production_stage1_prod_on_change_value_snapshot"


def _rows(rows: list[dict[str, Any]], event: str) -> list[dict[str, Any]]:
    return [r for r in rows if isinstance(r, dict) and str(r.get("event") or "") == event]


def _unwrap(repr_str: Any) -> str:
    s = str(repr_str or "").strip()
    if s in ("None", "missing", "NoneType"):
        return ""
    if s.startswith("'") and s.endswith("'") and len(s) > 2:
        return s[1:-1]
    return s


def _lifecycle_evidence_sufficient(
    mutations: list[dict[str, Any]],
    ops: list[dict[str, Any]],
    handoffs: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> bool:
    return bool(ops or handoffs or snapshots)


def classify_value_loss_boundary(
    *,
    exact_token: str,
    filtered_rows: list[dict[str, Any]],
    callback_boundary: dict[str, Any] | None = None,
    token_raw: dict[str, Any] | None = None,
    return_value_chain: dict[str, Any] | None = None,
    require_lifecycle_evidence: bool = True,
) -> dict[str, Any]:
    exact = str(exact_token or "").strip()
    cb = callback_boundary or {}
    raw = token_raw or {}
    rv = return_value_chain or {}
    entered = _rows(filtered_rows, "production_stage1_prod_on_change_entered")
    exited = _rows(filtered_rows, "production_stage1_prod_on_change_exited")
    mutations = _rows(filtered_rows, MUTATION_EVENT)
    ops = _rows(filtered_rows, VALUE_OP_EVENT)
    handoffs = _rows(filtered_rows, HANDOFF_EVENT)
    snapshots = _rows(filtered_rows, SNAPSHOT_EVENT)

    entry_repr = _unwrap((entered[-1] if entered else {}).get("session_state_value_repr"))
    exit_repr = _unwrap((exited[-1] if exited else {}).get("session_state_value_at_exit_repr"))
    cb_code = str(cb.get("classification") or "")

    audit: dict[str, Any] = {
        "callback_boundary": cb_code,
        "mutation_count": len(mutations),
        "value_op_count": len(ops),
        "handoff_boundary_count": len(handoffs),
        "value_snapshot_count": len(snapshots),
        "token_raw": raw,
        "lifecycle_evidence_sufficient": _lifecycle_evidence_sufficient(
            mutations, ops, handoffs, snapshots
        ),
    }

    for m in mutations:
        op = str(m.get("mutation_op") or "")
        key = str(m.get("key") or "")
        if op in ("pop", "delete", "clear") and exact and "solo_persistent" in key:
            return _out(VALUE1, audit, f"mutation:{op}:{key}", VALUE1)
        if op in ("set", "update") and str(m.get("new_value_repr") or "") in ("None", "''", '""', ""):
            if exact in str(m.get("previous_value_repr") or ""):
                return _out(VALUE1, audit, f"explicit_clear:{key}", VALUE1)

    for op in ops:
        label = str(op.get("operation_label") or "")
        if "deliver_callback" in label or "cleanup" in label.lower():
            prev = str(op.get("previous_raw_value") or "")
            new = str(op.get("new_raw_value") or "")
            if exact in prev and exact not in new and not new:
                return _out(VALUE2, audit, label, VALUE2)

    if require_lifecycle_evidence and not audit["lifecycle_evidence_sufficient"]:
        provisional = ""
        if cb_code.startswith("CB6") and exact and exact in entry_repr and exact not in exit_repr:
            provisional = VALUE4
        return {
            "classification": VALUE_PENDING,
            "provisional_inference": provisional,
            "provisional_inference_authoritative": False,
            "first_value_loss": "insufficient_lifecycle_ledger_rows",
            "smallest_correction_boundary": VALUE_PENDING,
            "audit": audit,
            "rationale": (
                "Legacy CB6 entry/exit pattern alone cannot distinguish VALUE1–VALUE9; "
                "requires value_op, mutation, and/or handoff ledger rows from lifecycle instrumentation."
            ),
        }

    if "CB5" in cb_code:
        return _out(VALUE3, audit, "callback_reads_wrong_key", VALUE3)

    for h in handoffs:
        boundary = str(h.get("boundary") or "")
        val = _unwrap(h.get("value_raw"))
        if exact and exact not in val and boundary == "token_coalescing_normalization":
            prior = [
                _unwrap(x.get("value_raw"))
                for x in handoffs
                if str(x.get("boundary") or "") in ("post_callback_session_state", "same_key_session_state_read")
            ]
            if any(exact in p for p in prior):
                return _out(VALUE5, audit, "coalescing_discarded_token", VALUE5)

    if str((exited[-1] if exited else {}).get("streamlit_rerun_followed") or "").lower() in ("true", "1"):
        return _out(VALUE8, audit, "rerun_after_callback", VALUE8)

    for h in handoffs:
        if str(h.get("boundary") or "") == "raw_return_cache" and exact not in str(h.get("value_raw") or ""):
            for prev_h in handoffs:
                if str(prev_h.get("boundary") or "") == "raw_direct_component_return" and exact in str(
                    prev_h.get("value_raw") or ""
                ):
                    return _out(VALUE6, audit, "raw_cache_overwrite", VALUE6)

    entry_seq = (entered[-1] if entered else {}).get("script_run_seq")
    wrapper_seq = None
    if isinstance(rv.get("wrapper"), dict):
        wrapper_seq = rv.get("wrapper", {}).get("script_run_seq")
    if entry_seq is not None and wrapper_seq is not None and int(entry_seq) != int(wrapper_seq):
        return _out(VALUE7, audit, "script_run_seq_mismatch", VALUE7)

    widget_mutations = [m for m in mutations if "solo_persistent" in str(m.get("key") or "")]
    app_cleared = bool(widget_mutations)

    if exact and exact in entry_repr and exact not in exit_repr and not app_cleared:
        post_cb = _unwrap(raw.get("post_callback_session_value_raw"))
        wrapper = raw.get("wrapper_read_value_raw") or ""
        if not post_cb and not wrapper and handoffs:
            return _out(VALUE4, audit, "framework_clear_after_callback_no_app_mutation", VALUE4)
        if not post_cb and not wrapper:
            return _out(VALUE9, audit, "transient_trigger_handoff_required", VALUE9)

    return _out(VALUE10, audit, "unmapped_value_loss", VALUE10)


def _out(code: str, audit: dict[str, Any], missing: str, boundary: str) -> dict[str, Any]:
    return {
        "classification": code,
        "first_value_loss": missing,
        "smallest_correction_boundary": boundary,
        "audit": audit,
        "provisional_inference_authoritative": True,
    }
