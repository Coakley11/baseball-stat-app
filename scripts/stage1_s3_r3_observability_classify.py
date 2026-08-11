"""S3 R3 observability gate and sibling causal subclasses."""

from __future__ import annotations

from typing import Any

BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT = "BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT"
BUTTON_DISPATCH_S3_R3O0_SERVER_EXPORT_NOT_REFRESHED_AFTER_PAUSE = (
    "BUTTON_DISPATCH_S3_R3O0_SERVER_EXPORT_NOT_REFRESHED_AFTER_PAUSE"
)
BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_UNAVAILABLE = "BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_UNAVAILABLE"
BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_NOT_REFRESHED_AFTER_SIBLING = (
    "BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_NOT_REFRESHED_AFTER_SIBLING"
)
BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_NOT_REFRESHED_AFTER_PAUSE = (
    "BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_NOT_REFRESHED_AFTER_PAUSE"
)
BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_INSTRUMENTATION_FAILURE = (
    "BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_INSTRUMENTATION_FAILURE"
)
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


def pause_observability_chain(rows: list[dict[str, Any]], *, unrouted_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    by = _by_phase(rows)
    un = list(unrouted_rows or [])
    runtime = by.get("RUNTIME_BACKMSG_ENTRY") or []
    back = by.get("APPSESSION_BACKMSG_ENTRY") or []
    req = by.get("APPSESSION_REQUEST_RERUN_ENTRY") or []
    safe_recv = by.get("SAFE_SESSIONSTATE_RECEIVE_ENTRY") or []
    recv = by.get("SERVER_RECEIVE_ENTRY") or []
    applied = by.get("SERVER_STATE_APPLIED") or []
    ev = {
        "runtime_backmsg_pause": _any(runtime, lambda r: bool(r.get("pause_present"))),
        "backmsg_pause": _any(back, lambda r: bool(r.get("pause_present"))),
        "request_rerun_pause": _any(req, lambda r: bool(r.get("pause_present"))),
        "safe_sessionstate_pause": _any(safe_recv, lambda r: bool(r.get("pause_present"))),
        "server_receive_pause": _any(recv, lambda r: bool(r.get("pause_present"))),
        "server_applied_pause": _any(
            applied,
            lambda r: bool(r.get("pause_present")) or bool(r.get("pause_trigger_from_deserialized")),
        ),
        "unrouted_server_receive": _any(un, lambda r: str(r.get("phase") or "") == "SERVER_RECEIVE_ENTRY"),
        "unrouted_server_applied": _any(un, lambda r: str(r.get("phase") or "") == "SERVER_STATE_APPLIED"),
        "unrouted_safe_receive": _any(un, lambda r: str(r.get("phase") or "") == "SAFE_SESSIONSTATE_RECEIVE_ENTRY"),
    }
    ev["ok"] = all(
        ev[k]
        for k in (
            "runtime_backmsg_pause",
            "backmsg_pause",
            "request_rerun_pause",
            "safe_sessionstate_pause",
            "server_receive_pause",
            "server_applied_pause",
        )
    )
    return ev


def observability_failure_boundary(pause_obs: dict[str, Any]) -> str:
    if pause_obs.get("ok"):
        return ""
    chain: list[tuple[str, str]] = [
        ("runtime_backmsg_pause", "browser_to_runtime"),
        ("backmsg_pause", "runtime_to_appsession"),
        ("request_rerun_pause", "appsession_to_request_rerun"),
        ("safe_sessionstate_pause", "request_to_safe_sessionstate"),
        ("server_receive_pause", "safe_to_underlying_receive"),
        ("server_applied_pause", "underlying_receive_to_apply"),
    ]
    for key, boundary in chain:
        if pause_obs.get(key):
            continue
        if key == "server_receive_pause" and pause_obs.get("unrouted_server_receive"):
            return "sessionstate_sid_routing"
        if key == "server_applied_pause" and pause_obs.get("unrouted_server_applied"):
            return "sessionstate_sid_routing"
        return boundary
    return "unknown"


def sibling_rows(rows: list[dict[str, Any]], *, wire_widget_id: str = "") -> dict[str, Any]:
    by = _by_phase(rows)
    wid = str(wire_widget_id or "")

    def sib_hit(r: dict[str, Any]) -> bool:
        if bool(r.get("pause_sibling_present")) or bool(r.get("sibling_present")):
            return True
        if wid and wid in str(r.get("activated_triggers") or ""):
            return True
        proto = r.get("pause_sibling_proto") or r.get("sibling_proto") or {}
        if wid and str(proto.get("id") or "") == wid:
            return True
        return False

    return {
        "backmsg": _any(by.get("APPSESSION_BACKMSG_ENTRY") or [], sib_hit),
        "request_rerun": _any(by.get("APPSESSION_REQUEST_RERUN_ENTRY") or [], sib_hit),
        "server_receive": _any(by.get("SERVER_RECEIVE_ENTRY") or [], sib_hit),
        "server_applied": _any(
            by.get("SERVER_STATE_APPLIED") or [],
            lambda r: sib_hit(r) and bool(r.get("trigger_from_deserialized")),
        ),
    }


def classify_export_freshness_after_pause(
    *,
    pause_resolved: bool,
    pre_pause_export_generation: int | None,
    post_pause_freshness: dict[str, Any] | None,
) -> tuple[str, str, dict[str, Any]] | None:
    """Return stale-export classification when Pause resolved but DOM export did not refresh."""
    if not pause_resolved:
        return None
    pre_gen = int(pre_pause_export_generation or 0)
    fresh = dict(post_pause_freshness or {})
    post_gen = int(fresh.get("export_generation") or 0)
    evidence = {
        "pre_pause_export_generation": pre_gen,
        "post_pause_export_generation": post_gen,
        "export_generation_advanced": post_gen > pre_gen,
        "freshness_wait_ok": fresh.get("freshness_wait_ok"),
    }
    if post_gen <= pre_gen:
        return (
            BUTTON_DISPATCH_S3_R3O0_SERVER_EXPORT_NOT_REFRESHED_AFTER_PAUSE,
            f"export_generation_stale:pre={pre_gen}:post={post_gen}",
            evidence,
        )
    return None


def classify_oob_channel_unavailable(
    *,
    channel: dict[str, Any],
    initial_fetch: dict[str, Any] | None,
    note: str = "oob_channel_missing_or_unreadable",
) -> tuple[str, str, dict[str, Any]] | None:
    if channel.get("registered") and initial_fetch and initial_fetch.get("ok"):
        return None
    return (
        BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_UNAVAILABLE,
        str(note or "oob_channel_missing_or_unreadable"),
        {"channel": channel, "initial_fetch": dict(initial_fetch or {})},
    )


def classify_oob_freshness_after_sibling(
    *,
    pre_sibling_generation: int | None,
    post_sibling_freshness: dict[str, Any] | None,
) -> tuple[str, str, dict[str, Any]] | None:
    pre_gen = int(pre_sibling_generation or 0)
    fresh = dict(post_sibling_freshness or {})
    post_gen = int(fresh.get("snapshot_generation") or 0)
    evidence = {
        "pre_sibling_snapshot_generation": pre_gen,
        "post_sibling_snapshot_generation": post_gen,
        "generation_advanced": post_gen > pre_gen,
    }
    if post_gen <= pre_gen:
        return (
            BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_NOT_REFRESHED_AFTER_SIBLING,
            f"oob_snapshot_stale:pre={pre_gen}:post={post_gen}",
            evidence,
        )
    return None


def classify_oob_freshness_after_pause(
    *,
    pause_resolved: bool,
    pre_pause_generation: int | None,
    post_pause_freshness: dict[str, Any] | None,
) -> tuple[str, str, dict[str, Any]] | None:
    if not pause_resolved:
        return None
    pre_gen = int(pre_pause_generation or 0)
    fresh = dict(post_pause_freshness or {})
    post_gen = int(fresh.get("snapshot_generation") or 0)
    evidence = {
        "pre_pause_snapshot_generation": pre_gen,
        "post_pause_snapshot_generation": post_gen,
        "generation_advanced": post_gen > pre_gen,
    }
    if post_gen <= pre_gen:
        return (
            BUTTON_DISPATCH_S3_R3O0_SERVER_OOB_CHANNEL_NOT_REFRESHED_AFTER_PAUSE,
            f"oob_snapshot_stale:pre={pre_gen}:post={post_gen}",
            evidence,
        )
    return None


def classify_pause_instrumentation_failure(
    *,
    pause_resolved: bool,
    authoritative_rows: list[dict[str, Any]],
) -> tuple[str, str, dict[str, Any]] | None:
    if not pause_resolved:
        return None
    by = _by_phase(authoritative_rows)
    runtime = bool(by.get("RUNTIME_BACKMSG_ENTRY"))
    back = bool(by.get("APPSESSION_BACKMSG_ENTRY"))
    req = bool(by.get("APPSESSION_REQUEST_RERUN_ENTRY"))
    if runtime or back or req:
        return None
    return (
        BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_INSTRUMENTATION_FAILURE,
        "pause_functional_but_runtime_appsession_absent_from_fresh_oob",
        {
            "runtime_backmsg_present": runtime,
            "appsession_backmsg_present": back,
            "appsession_request_rerun_present": req,
            "authoritative_row_count": len(authoritative_rows),
        },
    )


def classify_s3_with_observability(
    *,
    module_rows: list[dict[str, Any]],
    authoritative_rows: list[dict[str, Any]] | None = None,
    pause_resolved: bool,
    strict_backmsg: dict[str, Any],
    wire_widget_id: str,
    sibling_python_effect: bool,
    register_widget_result: bool | None,
    st_button_returned: bool | None,
    binding_ok: bool | None,
    unrouted_rows: list[dict[str, Any]] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    rows = list(authoritative_rows if authoritative_rows is not None else module_rows)
    evidence: dict[str, Any] = {
        "classification_history": {
            "prior_d89e94f": "BUTTON_DISPATCH_S3_R2_FRAGMENT_OWNER_MISMATCH",
            "prior_26effa0_r2": "BUTTON_DISPATCH_S3_R2C_OWNER_MATCH_AFTER_RECHECK",
            "accepted_374ecc0_r3o0": {
                "classification": BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT,
                "note": "pause_functional_but_server_chain_missing:multiple",
                "retrospective_diagnostic_concern": (
                    "server-boundary rows may have been lost by destructive local-vs-module export "
                    "and generic-tail truncation"
                ),
                "not_proven_as_sole_cause": True,
            },
        },
        "binding_ok": binding_ok,
        "authoritative_row_count": len(rows),
    }
    pause_obs = pause_observability_chain(rows, unrouted_rows=unrouted_rows)
    evidence["pause_observability"] = pause_obs
    evidence["observability_failure_boundary"] = observability_failure_boundary(pause_obs)
    evidence["unrouted_event_count"] = len(list(unrouted_rows or []))

    if sibling_python_effect and st_button_returned:
        return BUTTON_DISPATCH_S3_R7_NONDETERMINISTIC_RECOVERY, "sibling_delivered", evidence

    if binding_ok is False:
        evidence["binding_failure"] = True

    if pause_resolved and not pause_obs.get("ok"):
        boundary = evidence["observability_failure_boundary"] or "unknown"
        return (
            BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT,
            f"pause_functional_but_server_chain_missing:{boundary}",
            evidence,
        )

    if not pause_obs.get("ok"):
        return BUTTON_DISPATCH_S3_R0_INCOMPLETE_EVIDENCE, "pause_observability_incomplete", evidence

    strict_trigger = bool(strict_backmsg.get("activated_widget_state_present"))
    sib = sibling_rows(rows, wire_widget_id=wire_widget_id)
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
