"""Classify first callback binding boundary CB1–CB10 from Stage 1 ledger rows."""

from __future__ import annotations

from typing import Any

PROD_ENTERED = "production_stage1_prod_on_change_entered"
PROD_EXITED = "production_stage1_prod_on_change_exited"
CONTROL_ENTERED = "production_stage1_control_on_change_entered"
REGISTRATION = "production_stage1_callback_registration"


def _rows_of(rows: list[dict[str, Any]], event: str) -> list[dict[str, Any]]:
    return [r for r in rows if isinstance(r, dict) and str(r.get("event") or "") == event]


def _norm_token(val: Any) -> str:
    s = str(val or "").strip()
    if s in ("None", "missing", ""):
        return ""
    return s


def classify_callback_boundary(
    *,
    filtered_rows: list[dict[str, Any]],
    exact_token: str,
    outbound_widget_id: str = "",
) -> dict[str, Any]:
    exact = _norm_token(exact_token)
    regs = _rows_of(filtered_rows, REGISTRATION)
    prod_entered = _rows_of(filtered_rows, PROD_ENTERED)
    prod_exited = _rows_of(filtered_rows, PROD_EXITED)
    reg_with_on_change = [r for r in regs if r.get("on_change_registered") is True]
    post_send_entered = prod_entered  # harness should filter to diagnostic run

    report: dict[str, Any] = {
        "exact_token": exact,
        "registration_count": len(regs),
        "on_change_registered_count": len(reg_with_on_change),
        "prod_on_change_entered_count": len(prod_entered),
        "prod_on_change_exited_count": len(prod_exited),
        "outbound_widget_id": outbound_widget_id,
        "classification": "",
        "rationale": "",
    }

    if reg_with_on_change and not prod_entered:
        report["classification"] = "CB1 — PRODUCTION_ON_CHANGE_NEVER_INVOKED"
        report["rationale"] = "Callback registered on declaration but no production_stage1_prod_on_change_entered."
        return report

    if outbound_widget_id and reg_with_on_change:
        last_reg = reg_with_on_change[-1]
        reg_id = str(
            last_reg.get("actual_registered_internal_widget_id")
            or last_reg.get("actual_registered_widget_id")
            or ""
        )
        if reg_id and outbound_widget_id and reg_id != outbound_widget_id:
            report["classification"] = "CB2 — CALLBACK_REGISTERED_ON_WRONG_DECLARATION"
            report["rationale"] = f"Registration widget id {reg_id[:80]} != outbound {outbound_widget_id[:80]}"
            return report

    if prod_entered:
        entry = post_send_entered[-1]
        key_exists = bool(entry.get("session_state_key_exists"))
        ss_repr = _norm_token(entry.get("session_state_value_repr"))
        if not key_exists:
            report["classification"] = "CB3 — CALLBACK_INVOKED_BUT_SESSION_STATE_KEY_ABSENT"
            report["rationale"] = "prod_on_change_entered with session_state_key_exists=false."
            return report
        if key_exists and not ss_repr:
            report["classification"] = "CB4 — CALLBACK_INVOKED_BUT_SESSION_STATE_VALUE_NONE"
            report["rationale"] = "Key exists at callback entry but value repr empty/None."
            return report
        if exact and exact not in ss_repr and exact.replace("|", "") not in ss_repr.replace("|", ""):
            inv = entry.get("session_state_inventory") or {}
            related = inv.get("related_keys") if isinstance(inv, dict) else []
            found_elsewhere = False
            for item in related if isinstance(related, list) else []:
                if not isinstance(item, dict):
                    continue
                rep = str(item.get("repr") or "")
                if exact in rep:
                    found_elsewhere = True
                    report["session_state_key_with_token"] = item.get("key")
                    break
            if found_elsewhere:
                report["classification"] = "CB5 — CALLBACK_READS_WRONG_SESSION_STATE_KEY"
                report["rationale"] = "Exact token visible under a related key, not the user widget key."
                return report

        exited = prod_exited[-1] if prod_exited else {}
        exit_repr = _norm_token(exited.get("session_state_value_at_exit_repr"))
        if exact and exact in ss_repr and exact not in exit_repr:
            report["classification"] = "CB6 — VALUE_PRESENT_IN_CALLBACK_BUT_CLEARED_OR_DISPLACED_AFTERWARD"
            report["rationale"] = "Token at entry, absent or displaced at exit."
            return report
        if exact and exact not in ss_repr and exit_repr and exact in exit_repr:
            report["classification"] = "CB7 — VALUE_BINDS_AFTER_CALLBACK_RETURNS"
            report["rationale"] = "Token absent at entry, present at exit."
            return report

        dup_skip = [r for r in regs if str(r.get("mount_guard_result") or "").startswith("duplicate")]
        if dup_skip and prod_entered:
            active_reg = reg_with_on_change[-1] if reg_with_on_change else {}
            if str(active_reg.get("mount_guard_result") or "") == "duplicate_skipped_same_run":
                report["classification"] = "CB8 — SINGLE-MOUNT_GUARD_SUPPRESSES_ACTIVE_CALLBACK_DECLARATION"
                report["rationale"] = "Mount guard skipped declaration while callback activity expected."
                return report

        exc = str((prod_exited[-1] if prod_exited else {}).get("exception_status") or "").strip()
        if exc and exc not in ("none", ""):
            report["classification"] = "CB9 — CALLBACK_EXCEPTION_BEFORE_VALUE_CAPTURE"
            report["rationale"] = exc[:200]
            return report

        if exact and exact not in ss_repr:
            report["classification"] = "CB4 — CALLBACK_INVOKED_BUT_SESSION_STATE_VALUE_NONE"
            report["rationale"] = "Callback ran; user key never held exact expiration token."
            return report

    if not report["classification"]:
        report["classification"] = "CB10 — OTHER"
        report["rationale"] = "No CB1–CB9 rule matched; inspect ledger timelines manually."
    return report
