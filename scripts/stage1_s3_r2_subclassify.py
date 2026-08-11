"""R2 sub-classifications R2A / R2B / R2C."""

from __future__ import annotations

from typing import Any

BUTTON_DISPATCH_S3_R2_FRAGMENT_OWNER_MISMATCH = "BUTTON_DISPATCH_S3_R2_FRAGMENT_OWNER_MISMATCH"
BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED = "BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED"
BUTTON_DISPATCH_S3_R2B_WRONG_LIVE_FRAGMENT_TARGET = "BUTTON_DISPATCH_S3_R2B_WRONG_LIVE_FRAGMENT_TARGET"
BUTTON_DISPATCH_S3_R2C_OWNER_MATCH_AFTER_RECHECK = "BUTTON_DISPATCH_S3_R2C_OWNER_MATCH_AFTER_RECHECK"


def resolve_sibling_owner_fragment_id(
    post_registration: dict[str, Any],
    s3_ledger_rows: list[dict[str, Any]],
) -> str:
    for r in s3_ledger_rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("phase") or "") == "REGISTER_ENTRY":
            fid = str(r.get("fragment_id") or "").strip()
            if fid:
                return fid
    return str(post_registration.get("thread_state_fragment_id") or "").strip()


def preclick_fragment_storage_ids(post_registration: dict[str, Any]) -> list[str]:
    fs = post_registration.get("fragment_storage") if isinstance(post_registration.get("fragment_storage"), dict) else {}
    return [str(x) for x in list(fs.get("stored_fragment_ids") or [])]


def wire_target_in_preclick_storage(wire_target: str, post_registration: dict[str, Any]) -> bool | None:
    if not wire_target:
        return None
    stored = preclick_fragment_storage_ids(post_registration)
    if not stored:
        return None
    return wire_target in stored


def _events_by_phase(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.setdefault(str(r.get("phase") or ""), []).append(dict(r))
    return out


def classify_s3_r2_subclass(
    *,
    wire_widget_id: str,
    wire_rerun_target_fragment_id: str,
    post_registration: dict[str, Any],
    strict_backmsg: dict[str, Any],
    s3_ledger_rows: list[dict[str, Any]],
    appsession_ingress_rows: list[dict[str, Any]],
    sibling_click_ts: float | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Return (classification, note, evidence). May fall back to generic R2."""
    evidence: dict[str, Any] = {}
    wire_target = str(
        wire_rerun_target_fragment_id
        or strict_backmsg.get("wire_rerun_target_fragment_id")
        or ""
    ).strip()
    reg_id = str(post_registration.get("registered_widget_id") or "").strip()
    owner = resolve_sibling_owner_fragment_id(post_registration, s3_ledger_rows)
    evidence["sibling_owner_fragment_id"] = owner
    evidence["wire_rerun_target_fragment_id"] = wire_target
    stored = preclick_fragment_storage_ids(post_registration)
    evidence["preclick_fragment_storage_ids"] = stored
    wit = wire_target_in_preclick_storage(wire_target, post_registration)
    evidence["wire_target_in_preclick_fragment_storage"] = wit

    strict_trigger = bool(strict_backmsg.get("activated_widget_state_present"))
    ids_match = bool(wire_widget_id and reg_id and wire_widget_id == reg_id)

    if wire_target and owner and wire_target == owner:
        return BUTTON_DISPATCH_S3_R2C_OWNER_MATCH_AFTER_RECHECK, "wire_target_equals_register_owner", evidence

    if not (strict_trigger and ids_match and wire_target and owner and wire_target != owner):
        return BUTTON_DISPATCH_S3_R2_FRAGMENT_OWNER_MISMATCH, "generic_r2_fragment_mismatch", evidence

    by_phase = _events_by_phase(s3_ledger_rows)
    receive = by_phase.get("SERVER_RECEIVE_ENTRY") or []
    applied = by_phase.get("SERVER_STATE_APPLIED") or []
    recv_hit = any(bool(r.get("sibling_present")) for r in receive)

    ingress = list(appsession_ingress_rows or [])
    if sibling_click_ts:
        ingress = [r for r in ingress if float(r.get("ts") or 0) >= float(sibling_click_ts) - 2.0]
    sibling_ingress = [
        r
        for r in ingress
        if bool(r.get("sibling_present"))
        or (
            wire_target
            and str(r.get("client_state_fragment_id") or "") == wire_target
            and bool((r.get("sibling_proto") or {}).get("trigger_value"))
        )
    ]
    evidence["appsession_sibling_ingress_count"] = len(sibling_ingress)

    guard_fail = any(bool(r.get("would_fail_streamlit_fragment_storage_guard")) for r in sibling_ingress)
    target_absent = any(r.get("target_fragment_exists") is False for r in sibling_ingress)
    evidence["appsession_guard_fail_seen"] = guard_fail
    evidence["appsession_target_absent_seen"] = target_absent

    in_storage = wit is True
    absent_preclick = wit is False

    if absent_preclick and not recv_hit:
        note = "wire_target_absent_preclick_no_sessionstate"
        if guard_fail or target_absent:
            note += "_ingress_guard_confirmed"
        elif sibling_ingress:
            note += "_ingress_sibling_row"
        return (
            BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED,
            note,
            evidence,
        )

    if in_storage and wire_target != owner and not recv_hit:
        return BUTTON_DISPATCH_S3_R2B_WRONG_LIVE_FRAGMENT_TARGET, "wire_target_in_storage_no_sessionstate", evidence

    return BUTTON_DISPATCH_S3_R2_FRAGMENT_OWNER_MISMATCH, "r2_unresolved_subclass", evidence


def classify_sibling_oob_r2_from_snapshot(
    *,
    oob_snapshot: dict[str, Any],
    wire_rerun_target_fragment_id: str,
    owner_fragment_id: str,
    wire_target_in_preclick_fragment_storage: bool | None,
    strict_backmsg: dict[str, Any],
    wire_widget_id: str,
    post_registration: dict[str, Any],
) -> tuple[str, str, dict[str, Any]] | None:
    """Return R2 subclass when fresh OOB sibling evidence matches fragment-target/owner pattern."""
    rows = list(oob_snapshot.get("module_ledger_rows") or []) + list(oob_snapshot.get("critical_ledger_rows") or [])
    by_phase = _events_by_phase(rows)
    runtime_present = bool(by_phase.get("RUNTIME_BACKMSG_ENTRY"))
    backmsg_present = bool(by_phase.get("APPSESSION_BACKMSG_ENTRY"))
    rerun_present = bool(by_phase.get("APPSESSION_REQUEST_RERUN_ENTRY"))
    receive_present = bool(by_phase.get("SERVER_RECEIVE_ENTRY"))
    evidence: dict[str, Any] = {
        "runtime_backmsg_present": runtime_present,
        "appsession_backmsg_present": backmsg_present,
        "appsession_request_rerun_present": rerun_present,
        "server_receive_present": receive_present,
        "wire_rerun_target_fragment_id": wire_rerun_target_fragment_id,
        "owner_fragment_id": owner_fragment_id,
        "wire_target_in_preclick_fragment_storage": wire_target_in_preclick_fragment_storage,
        "oob_snapshot_generation": oob_snapshot.get("snapshot_generation"),
    }
    if not (runtime_present and backmsg_present and rerun_present):
        return None
    strict_trigger = bool(strict_backmsg.get("activated_widget_state_present"))
    reg_id = str(post_registration.get("registered_widget_id") or "").strip()
    ids_match = bool(wire_widget_id and reg_id and wire_widget_id == reg_id)
    if not (strict_trigger and ids_match and wire_rerun_target_fragment_id and owner_fragment_id):
        return None
    if wire_rerun_target_fragment_id == owner_fragment_id:
        return None
    if wire_target_in_preclick_fragment_storage is False and not receive_present:
        note = "oob_wire_target_absent_preclick_no_sessionstate"
        ingress = [r for r in rows if str(r.get("phase") or "").startswith("APPSESSION_")]
        guard_fail = any(bool(r.get("would_fail_streamlit_fragment_storage_guard")) for r in ingress)
        target_absent = any(r.get("target_fragment_exists") is False for r in ingress)
        if guard_fail or target_absent:
            note += "_ingress_guard_confirmed"
        return BUTTON_DISPATCH_S3_R2A_STALE_RERUN_TARGET_DROPPED, note, evidence
    if wire_target_in_preclick_fragment_storage is True and not receive_present:
        return (
            BUTTON_DISPATCH_S3_R2B_WRONG_LIVE_FRAGMENT_TARGET,
            "oob_wire_target_in_storage_no_sessionstate",
            evidence,
        )
    return None
