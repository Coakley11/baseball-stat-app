"""S3 R3 observability gate and sibling causal subclasses."""

from __future__ import annotations

from typing import Any

BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT = "BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT"
BUTTON_DISPATCH_S3_R3A_DROPPED_IN_APPSESSION_BACKMSG_PATH = "BUTTON_DISPATCH_S3_R3A_DROPPED_IN_APPSESSION_BACKMSG_PATH"
BUTTON_DISPATCH_S3_R3B_DROPPED_AFTER_RERUN_REQUEST = "BUTTON_DISPATCH_S3_R3B_DROPPED_AFTER_RERUN_REQUEST"
BUTTON_DISPATCH_S3_R4_TRIGGER_LOST_DURING_STATE_APPLY = "BUTTON_DISPATCH_S3_R4_TRIGGER_LOST_DURING_STATE_APPLY"
BUTTON_DISPATCH_S3_R5_REGISTER_WIDGET_VALUE_LOST = "BUTTON_DISPATCH_S3_R5_REGISTER_WIDGET_VALUE_LOST"
BUTTON_DISPATCH_S3_R6_BUTTON_RESULT_PROPAGATION = "BUTTON_DISPATCH_S3_R6_BUTTON_RESULT_PROPAGATION"
BUTTON_DISPATCH_S3_R7_NONDETERMINISTIC_RECOVERY = "BUTTON_DISPATCH_S3_R7_NONDETERMINISTIC_RECOVERY"
BUTTON_DISPATCH_S3_R0_INCOMPLETE_EVIDENCE = "BUTTON_DISPATCH_S3_R0_INCOMPLETE_EVIDENCE"


def _by_phase(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if isinstance(r, dict):
            out.setdefault(str(r.get("phase") or ""), []).append(dict(r))
    return out


def _any(rows: list[dict[str, Any]], pred) -> bool:
    return any(pred(r) for r in rows)


def pause_observability_chain(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by = _by_phase(rows)
    back = by.get("APPSESSION_BACKMSG_ENTRY") or []
    req = by.get("APPSESSION_REQUEST_RERUN_ENTRY") or []
    recv = by.get("SERVER_RECEIVE_ENTRY") or []
    applied = by.get("SERVER_STATE_APPLIED") or []
    ev = {
        "backmsg_pause": _any(back, lambda r: bool(r.get("pause_present"))),
        "request_rerun_pause": _any(req, lambda r: bool(r.get("pause_present"))),
        "server_receive_pause": _any(recv, lambda r: bool(r.get("pause_present"))),
        "server_applied_pause": _any(
            applied,
            lambda r: bool(r.get("pause_present")) or bool(r.get("pause_trigger_from_deserialized")),
        ),
    }
    ev["ok"] = all(ev[k] for k in ("backmsg_pause", "request_rerun_pause", "server_receive_pause", "server_applied_pause"))
    return ev


def sibling_rows(rows: list[dict[str, Any]], *, wire_widget_id: str = "") -> dict[str, Any]:
    by = _by_phase(rows)
    wid = str(wire_widget_id or "")

    def sib_hit(r: dict[str, Any]) -> bool:
        if bool(r.get("pause_sibling_present")):
            return True
        if wid and wid in str(r.get("activated_triggers") or ""):
            return True
        proto = r.get("pause_sibling_proto") or r.get("sibling_proto") or {}
        if wid and str(proto.get("id") or "") == wid:
            return True
        return bool(r.get("sibling_present"))

    return {
        "backmsg": _any(by.get("APPSESSION_BACKMSG_ENTRY") or [], sib_hit),
        "request_rerun": _any(by.get("APPSESSION_REQUEST_RERUN_ENTRY") or [], sib_hit),
        "server_receive": _any(by.get("SERVER_RECEIVE_ENTRY") or [], sib_hit),
        "server_applied": _any(
            by.get("SERVER_STATE_APPLIED") or [],
            lambda r: sib_hit(r) and bool(r.get("trigger_from_deserialized")),
        ),
    }


def classify_s3_with_observability(
    *,
    module_rows: list[dict[str, Any]],
    pause_resolved: bool,
    strict_backmsg: dict[str, Any],
    wire_widget_id: str,
    sibling_python_effect: bool,
    register_widget_result: bool | None,
    st_button_returned: bool | None,
    binding_ok: bool | None,
) -> tuple[str, str, dict[str, Any]]:
    evidence: dict[str, Any] = {
        "classification_history": {
            "prior_d89e94f": "BUTTON_DISPATCH_S3_R2_FRAGMENT_OWNER_MISMATCH",
            "prior_26effa0_r2": "BUTTON_DISPATCH_S3_R2C_OWNER_MATCH_AFTER_RECHECK",
        },
        "binding_ok": binding_ok,
    }
    pause_obs = pause_observability_chain(module_rows)
    evidence["pause_observability"] = pause_obs

    if sibling_python_effect and st_button_returned:
        return BUTTON_DISPATCH_S3_R7_NONDETERMINISTIC_RECOVERY, "sibling_delivered", evidence

    if binding_ok is False:
        evidence["binding_failure"] = True

    if pause_resolved and not pause_obs.get("ok"):
        return BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT, "pause_functional_but_server_chain_missing", evidence

    if not pause_obs.get("ok"):
        return BUTTON_DISPATCH_S3_R0_INCOMPLETE_EVIDENCE, "pause_observability_incomplete", evidence

    strict_trigger = bool(strict_backmsg.get("activated_widget_state_present"))
    sib = sibling_rows(module_rows, wire_widget_id=wire_widget_id)
    evidence["sibling_chain"] = sib

    if register_widget_result is True and st_button_returned is False:
        return BUTTON_DISPATCH_S3_R6_BUTTON_RESULT_PROPAGATION, "register_true_button_false", evidence

    if not strict_trigger:
        return BUTTON_DISPATCH_S3_R0_INCOMPLETE_EVIDENCE, "no_strict_sibling_trigger", evidence

    if sib["backmsg"] and not sib["request_rerun"]:
        return BUTTON_DISPATCH_S3_R3A_DROPPED_IN_APPSESSION_BACKMSG_PATH, "backmsg_without_request_rerun", evidence

    if sib["request_rerun"] and not sib["server_receive"]:
        return BUTTON_DISPATCH_S3_R3B_DROPPED_AFTER_RERUN_REQUEST, "request_rerun_without_sessionstate_receive", evidence

    if sib["server_receive"] and not sib["server_applied"]:
        return BUTTON_DISPATCH_S3_R4_TRIGGER_LOST_DURING_STATE_APPLY, "receive_without_post_apply", evidence

    if sib["server_applied"] and register_widget_result is False and not sibling_python_effect:
        return BUTTON_DISPATCH_S3_R5_REGISTER_WIDGET_VALUE_LOST, "apply_true_register_false", evidence

    if strict_trigger and not any(sib.values()):
        return BUTTON_DISPATCH_S3_R0_INCOMPLETE_EVIDENCE, "strict_trigger_no_sibling_server_rows", evidence

    return BUTTON_DISPATCH_S3_R0_INCOMPLETE_EVIDENCE, "pattern_unresolved", evidence
