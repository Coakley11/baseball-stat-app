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

PRODUCTION_WIDGET_KEY = "solo_countdown_wake_solo_persistent"
CLASSIFIER_FIX_SHA = "a20d281-replay-v1"

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


def _raw_matches_exact(raw_repr: Any, exact: str) -> bool:
    if not exact:
        return False
    return _unwrap(str(raw_repr or "")) == exact


def _mutation_clears_widget_key(
    mutation: dict[str, Any], *, widget_key: str, exact: str
) -> bool:
    key = str(mutation.get("key") or mutation.get("widget_key") or "")
    if key != widget_key:
        return False
    op = str(mutation.get("mutation_op") or "")
    if op in ("pop", "delete", "clear"):
        return True
    if op in ("set", "update"):
        prev = str(mutation.get("previous_value_repr") or "")
        new = _unwrap(mutation.get("new_value_repr"))
        if exact in prev and new != exact:
            return True
    return False


def _timeline_widget_value_rows(
    filtered_rows: list[dict[str, Any]],
    *,
    widget_key: str,
) -> list[dict[str, Any]]:
    """Chronological rows that carry widget-key raw values for transition replay."""
    out: list[dict[str, Any]] = []
    for r in filtered_rows:
        if not isinstance(r, dict):
            continue
        ev = str(r.get("event") or "")
        ts = float(r.get("ts") or 0)
        eid = str(r.get("event_id") or ev)
        if ev == SNAPSHOT_EVENT and str(r.get("widget_key") or "") == widget_key:
            out.append(
                {
                    "ts": ts,
                    "event_id": eid,
                    "event": ev,
                    "phase": str(r.get("phase") or ""),
                    "raw_repr": r.get("raw_value_repr"),
                    "key_exists": r.get("session_state_key_exists"),
                }
            )
        elif ev == VALUE_OP_EVENT and str(r.get("widget_key") or "") == widget_key:
            out.append(
                {
                    "ts": ts,
                    "event_id": eid,
                    "event": ev,
                    "phase": str(r.get("operation_label") or ""),
                    "raw_repr": r.get("new_raw_value"),
                    "key_exists": None,
                }
            )
        elif ev == "production_stage1_prod_on_change_entered" and str(r.get("widget_key") or "") == widget_key:
            out.append(
                {
                    "ts": ts,
                    "event_id": eid,
                    "event": ev,
                    "phase": "callback_entered",
                    "raw_repr": r.get("session_state_value_repr"),
                    "key_exists": r.get("session_state_key_exists"),
                }
            )
        elif ev == "production_stage1_prod_on_change_exited" and str(r.get("widget_key") or "") == widget_key:
            out.append(
                {
                    "ts": ts,
                    "event_id": eid,
                    "event": ev,
                    "phase": "callback_exited",
                    "raw_repr": r.get("session_state_value_at_exit_repr"),
                    "key_exists": r.get("session_state_key_exists_at_exit"),
                }
            )
    out.sort(key=lambda x: (float(x["ts"]), str(x["event_id"])))
    return out


def _first_proven_loss_transition(
    timeline: list[dict[str, Any]], exact: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    last_true: dict[str, Any] | None = None
    first_false: dict[str, Any] | None = None
    for row in timeline:
        if _raw_matches_exact(row.get("raw_repr"), exact):
            last_true = row
            first_false = None
        elif last_true is not None and not _raw_matches_exact(row.get("raw_repr"), exact):
            first_false = row
            break
    return last_true, first_false


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
    production_widget_key: str = PRODUCTION_WIDGET_KEY,
) -> dict[str, Any]:
    exact = str(exact_token or "").strip()
    widget_key = str(production_widget_key or PRODUCTION_WIDGET_KEY)
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
        if _mutation_clears_widget_key(m, widget_key=widget_key, exact=exact):
            op = str(m.get("mutation_op") or "")
            key = str(m.get("key") or "")
            return _out(VALUE1, audit, f"mutation:{op}:{key}", VALUE1)

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

    widget_clear_mutations = [
        m for m in mutations if _mutation_clears_widget_key(m, widget_key=widget_key, exact=exact)
    ]
    app_cleared_widget_key = bool(widget_clear_mutations)

    timeline = _timeline_widget_value_rows(filtered_rows, widget_key=widget_key)
    last_true, first_false = _first_proven_loss_transition(timeline, exact)
    audit["value_transition_timeline_count"] = len(timeline)
    if last_true:
        audit["last_equals_expected_event_id"] = last_true.get("event_id")
        audit["last_equals_expected_phase"] = last_true.get("phase")
    if first_false:
        audit["first_loss_event_id"] = first_false.get("event_id")
        audit["first_loss_phase"] = first_false.get("phase")

    exit_phase_loss = (
        first_false is not None
        and str(first_false.get("phase") or "") == "callback_exit"
        and last_true is not None
        and str(last_true.get("phase") or "") in (
            "callback_entry",
            "read_session_state_widget_key",
            "after_read_session_state_widget_key",
            "callback_entered",
        )
    )

    if exit_phase_loss and not app_cleared_widget_key:
        loss_ref = (
            f"{last_true.get('event_id')}->{first_false.get('event_id')}"
            if last_true and first_false
            else "framework_clear_after_callback_no_app_mutation"
        )
        post_cb = _unwrap(raw.get("post_callback_session_value_raw"))
        wrapper = _unwrap(raw.get("wrapper_read_value_raw"))
        same_key_unavailable = not post_cb and not wrapper
        if same_key_unavailable:
            return _out(
                VALUE4,
                audit,
                loss_ref,
                VALUE9,
                mechanism=VALUE4,
                correction_boundary=VALUE9,
            )
        return _out(VALUE4, audit, loss_ref, VALUE4, mechanism=VALUE4)

    if exact and exact in entry_repr and exact not in exit_repr and not app_cleared_widget_key:
        post_cb = _unwrap(raw.get("post_callback_session_value_raw"))
        wrapper = _unwrap(raw.get("wrapper_read_value_raw") or "")
        if not post_cb and not wrapper and handoffs:
            return _out(VALUE4, audit, "framework_clear_after_callback_no_app_mutation", VALUE4)
        if not post_cb and not wrapper:
            return _out(VALUE9, audit, "transient_trigger_handoff_required", VALUE9)

    if last_true and first_false:
        pending = (
            f"VALUE_CLASSIFICATION_PENDING — FIRST LOSS OCCURS BETWEEN "
            f"{last_true.get('event_id')} AND {first_false.get('event_id')}"
        )
        return {
            "classification": pending,
            "first_value_loss": f"{last_true.get('event_id')}->{first_false.get('event_id')}",
            "smallest_correction_boundary": pending,
            "audit": audit,
            "provisional_inference_authoritative": False,
        }

    return _out(VALUE10, audit, "unmapped_value_loss", VALUE10)


def _out(
    code: str,
    audit: dict[str, Any],
    missing: str,
    boundary: str,
    *,
    mechanism: str = "",
    correction_boundary: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "classification": code,
        "first_value_loss": missing,
        "smallest_correction_boundary": boundary,
        "audit": audit,
        "provisional_inference_authoritative": True,
        "classifier_fix_sha": CLASSIFIER_FIX_SHA,
    }
    if mechanism:
        result["mechanism"] = mechanism
    if correction_boundary:
        result["correction_boundary"] = correction_boundary
    return result
