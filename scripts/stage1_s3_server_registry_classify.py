"""Classify S3 server registry chain R1–R7."""

from __future__ import annotations

from typing import Any

BUTTON_DISPATCH_S3_R1_STALE_FRONTEND_WIDGET_ID = "BUTTON_DISPATCH_S3_R1_STALE_FRONTEND_WIDGET_ID"
BUTTON_DISPATCH_S3_R2_FRAGMENT_OWNER_MISMATCH = "BUTTON_DISPATCH_S3_R2_FRAGMENT_OWNER_MISMATCH"
BUTTON_DISPATCH_S3_R3_RERUN_DROPPED_BEFORE_STATE_APPLY = "BUTTON_DISPATCH_S3_R3_RERUN_DROPPED_BEFORE_STATE_APPLY"
BUTTON_DISPATCH_S3_R4_TRIGGER_LOST_DURING_STATE_APPLY = "BUTTON_DISPATCH_S3_R4_TRIGGER_LOST_DURING_STATE_APPLY"
BUTTON_DISPATCH_S3_R5_REGISTER_WIDGET_VALUE_LOST = "BUTTON_DISPATCH_S3_R5_REGISTER_WIDGET_VALUE_LOST"
BUTTON_DISPATCH_S3_R6_BUTTON_RESULT_PROPAGATION = "BUTTON_DISPATCH_S3_R6_BUTTON_RESULT_PROPAGATION"
BUTTON_DISPATCH_S3_R7_NONDETERMINISTIC_RECOVERY = "BUTTON_DISPATCH_S3_R7_NONDETERMINISTIC_RECOVERY"
BUTTON_DISPATCH_S3_R0_INCOMPLETE_EVIDENCE = "BUTTON_DISPATCH_S3_R0_INCOMPLETE_EVIDENCE"


def _events_by_phase(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        ph = str(r.get("phase") or "")
        out.setdefault(ph, []).append(dict(r))
    return out


def classify_s3_server_registry(
    *,
    wire_widget_id: str,
    wire_fragment_id: str,
    post_registration: dict[str, Any],
    strict_backmsg: dict[str, Any],
    s3_ledger_rows: list[dict[str, Any]],
    sibling_python_effect: bool,
    register_widget_result: bool | None,
    st_button_returned: bool | None,
    pause_resolved: bool,
) -> tuple[str, str]:
    reg_id = str(post_registration.get("registered_widget_id") or "")
    meta = post_registration.get("widget_metadata") if isinstance(post_registration.get("widget_metadata"), dict) else {}
    meta_fid = str(meta.get("fragment_id") or post_registration.get("metadata_fragment_id") or "")
    thread_fid = str(post_registration.get("thread_state_fragment_id") or "")

    if sibling_python_effect and st_button_returned:
        return BUTTON_DISPATCH_S3_R7_NONDETERMINISTIC_RECOVERY, "sibling_delivered"

    if wire_widget_id and reg_id and wire_widget_id != reg_id:
        return BUTTON_DISPATCH_S3_R1_STALE_FRONTEND_WIDGET_ID, "wire_id_ne_registered_id"

    wire_frag = str(wire_fragment_id or "")
    if wire_frag and meta_fid and wire_frag != meta_fid:
        return BUTTON_DISPATCH_S3_R2_FRAGMENT_OWNER_MISMATCH, "wire_frag_ne_metadata_frag"
    if wire_frag and thread_fid and wire_frag != thread_fid:
        return BUTTON_DISPATCH_S3_R2_FRAGMENT_OWNER_MISMATCH, "wire_frag_ne_thread_frag"

    by_phase = _events_by_phase(s3_ledger_rows)
    receive = by_phase.get("SERVER_RECEIVE_ENTRY") or []
    applied = by_phase.get("SERVER_STATE_APPLIED") or []
    recv_hit = any(bool(r.get("sibling_present")) for r in receive)
    strict_trigger = bool(strict_backmsg.get("activated_widget_state_present"))
    strict_rerun = bool(strict_backmsg.get("rerun_script_backmsg_seen"))

    if register_widget_result is True and st_button_returned is False:
        return BUTTON_DISPATCH_S3_R6_BUTTON_RESULT_PROPAGATION, "register_true_button_false"

    if strict_rerun and strict_trigger and not recv_hit:
        return BUTTON_DISPATCH_S3_R3_RERUN_DROPPED_BEFORE_STATE_APPLY, "wire_trigger_not_in_server_receive"

    if recv_hit:
        recv_trig = any(bool((r.get("sibling_proto") or {}).get("trigger_value")) for r in receive)
        if recv_trig:
            applied_ok = any(
                bool(r.get("present_in_new_widget_state")) and bool(r.get("trigger_from_deserialized"))
                for r in applied
            )
            if not applied_ok:
                return BUTTON_DISPATCH_S3_R4_TRIGGER_LOST_DURING_STATE_APPLY, "receive_true_apply_false"

    if (
        strict_trigger
        and recv_hit
        and register_widget_result is False
        and not sibling_python_effect
        and pause_resolved
    ):
        return BUTTON_DISPATCH_S3_R5_REGISTER_WIDGET_VALUE_LOST, "register_false_after_wire_trigger"

    if not reg_id or not wire_widget_id:
        return BUTTON_DISPATCH_S3_R0_INCOMPLETE_EVIDENCE, "missing_ids_for_comparison"

    return BUTTON_DISPATCH_S3_R0_INCOMPLETE_EVIDENCE, "pattern_unresolved"
