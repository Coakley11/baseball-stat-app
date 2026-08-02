"""VALUE1–VALUE10 callback/post-callback value-loss classification (harness)."""

from __future__ import annotations

from typing import Any

VALUE1 = "VALUE1 — CALLBACK_EXPLICITLY_CLEARS_WIDGET_KEY"
VALUE2 = "VALUE2 — CALLBACK_CLEANUP_HELPER_CLEARS_VALUE"
VALUE3 = "VALUE3 — CALLBACK_COPIES_VALUE_BUT_WRAPPER_READS_WRONG_KEY"
VALUE4 = "VALUE4 — STREAMLIT_CLEARS_TRIGGER_STATE_AFTER_CALLBACK"
VALUE5 = "VALUE5 — WRAPPER_NORMALIZATION_CONVERTS_TOKEN_TO_EMPTY"
VALUE6 = "VALUE6 — SINGLE-MOUNT_RAW_CACHE_OVERWRITES_TOKEN"
VALUE7 = "VALUE7 — CALLBACK_VALUE_EXISTS_IN_ONE_SCRIPT_RUN_WRAPPER_READS_ANOTHER"
VALUE8 = "VALUE8 — CALLBACK_REQUESTS_RERUN_BEFORE_WRAPPER_CONSUMPTION"
VALUE9 = "VALUE9 — SESSION_STATE_WIDGET_KEY_IS_TRANSIENT_CALLBACK_MUST_COPY"
VALUE10 = "VALUE10 — OTHER"

MUTATION_EVENT = "production_stage1_session_state_mutation"
VALUE_OP_EVENT = "production_stage1_prod_on_change_value_op"
HANDOFF_EVENT = "production_stage1_post_callback_handoff_boundary"


def _rows(rows: list[dict[str, Any]], event: str) -> list[dict[str, Any]]:
    return [r for r in rows if isinstance(r, dict) and str(r.get("event") or "") == event]


def _unwrap(repr_str: Any) -> str:
    s = str(repr_str or "").strip()
    if s.startswith("'") and s.endswith("'") and len(s) > 2:
        return s[1:-1]
    return s


def classify_value_loss_boundary(
    *,
    exact_token: str,
    filtered_rows: list[dict[str, Any]],
    callback_boundary: dict[str, Any] | None = None,
    token_raw: dict[str, Any] | None = None,
    return_value_chain: dict[str, Any] | None = None,
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

    entry_repr = _unwrap((entered[-1] if entered else {}).get("session_state_value_repr"))
    exit_repr = _unwrap((exited[-1] if exited else {}).get("session_state_value_at_exit_repr"))
    cb_code = str(cb.get("classification") or "")

    audit: dict[str, Any] = {
        "callback_boundary": cb_code,
        "mutation_count": len(mutations),
        "value_op_count": len(ops),
        "handoff_boundary_count": len(handoffs),
        "token_raw": raw,
    }

    for m in mutations:
        op = str(m.get("mutation_op") or "")
        key = str(m.get("key") or "")
        if op in ("pop", "delete", "clear") and exact and key.endswith("solo_persistent"):
            return _out(VALUE1, audit, f"mutation:{op}:{key}", VALUE1)
        if op in ("set", "update") and m.get("new_value_repr") in ("None", "''", '""', ""):
            if exact in str(m.get("previous_value_repr") or ""):
                return _out(VALUE1, audit, f"explicit_clear:{key}", VALUE1)

    for op in ops:
        label = str(op.get("operation_label") or "")
        if "deliver_callback" in label or "cleanup" in label.lower():
            if exact in str(op.get("previous_raw_value") or "") and not str(op.get("new_raw_value") or ""):
                return _out(VALUE2, audit, label, VALUE2)

    if "CB5" in cb_code:
        return _out(VALUE3, audit, "callback_reads_wrong_key", VALUE3)

    if exact and exact in entry_repr and exact not in exit_repr:
        if str((exited[-1] if exited else {}).get("streamlit_rerun_followed") or "").lower() in ("true", "1"):
            return _out(VALUE8, audit, "rerun_after_callback", VALUE8)
        if cb_code.startswith("CB6"):
            return _out(VALUE4, audit, "token_lost_after_callback_entry", VALUE4)

    wrapper = raw.get("wrapper_read_value_raw") or ""
    if exact and exact in entry_repr and not wrapper:
        if rv.get("wrapper_normalization_empty"):
            return _out(VALUE5, audit, "wrapper_normalization", VALUE5)

    for h in handoffs:
        if str(h.get("boundary") or "") == "raw_return_cache" and exact not in str(h.get("value_raw") or ""):
            return _out(VALUE6, audit, "raw_cache_overwrite", VALUE6)

    entry_seq = (entered[-1] if entered else {}).get("script_run_seq")
    wrapper_seq = None
    if isinstance(rv.get("wrapper"), dict):
        wrapper_seq = rv.get("wrapper", {}).get("script_run_seq")
    if entry_seq is not None and wrapper_seq is not None and int(entry_seq) != int(wrapper_seq):
        return _out(VALUE7, audit, "script_run_seq_mismatch", VALUE7)

    if exact and exact in entry_repr and exact not in exit_repr and not mutations:
        return _out(VALUE9, audit, "transient_widget_key", VALUE9)

    if cb_code.startswith("CB6"):
        return _out(VALUE4, audit, "cb6_default_value_loss", VALUE4)

    return _out(VALUE10, audit, "unmapped_value_loss", VALUE10)


def _out(code: str, audit: dict[str, Any], missing: str, boundary: str) -> dict[str, Any]:
    return {
        "classification": code,
        "first_value_loss": missing,
        "smallest_correction_boundary": boundary,
        "audit": audit,
    }
