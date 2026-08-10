"""S3 production gate setup localization (harness-only)."""

from __future__ import annotations

from typing import Any

ABORTED_S3_CONTROL_CENTER_NOT_READY = "ABORTED_S3_CONTROL_CENTER_NOT_READY"
ABORTED_S3_SIBLING_PROBE_NOT_RENDERED = "ABORTED_S3_SIBLING_PROBE_NOT_RENDERED"
ABORTED_S3_SIBLING_CALLSITE_NOT_REACHED = "ABORTED_S3_SIBLING_CALLSITE_NOT_REACHED"
ABORTED_S3_SIBLING_IMPORT_FAILED = "ABORTED_S3_SIBLING_IMPORT_FAILED"
ABORTED_S3_SETUP_EVIDENCE_CONTRADICTION = "ABORTED_S3_SETUP_EVIDENCE_CONTRADICTION"
ABORTED_S3_SIBLING_FUNCTION_NOT_ENTERED = "ABORTED_S3_SIBLING_FUNCTION_NOT_ENTERED"
ABORTED_S3_SIBLING_DIAG_DISABLED = "ABORTED_S3_SIBLING_DIAG_DISABLED"
ABORTED_S3_SIBLING_BUTTON_NOT_MOUNTED = "ABORTED_S3_SIBLING_BUTTON_NOT_MOUNTED"
ABORTED_S3_SIBLING_BUTTON_CALL_EXCEPTION = "ABORTED_S3_SIBLING_BUTTON_CALL_EXCEPTION"
ABORTED_S3_SIBLING_BUTTON_CALL_NOT_RETURNED = "ABORTED_S3_SIBLING_BUTTON_CALL_NOT_RETURNED"
ABORTED_S3_SIBLING_POST_REGISTRATION_NOT_REACHED = "ABORTED_S3_SIBLING_POST_REGISTRATION_NOT_REACHED"
ABORTED_S3_SIBLING_BUTTON_DOM_MISMATCH = "ABORTED_S3_SIBLING_BUTTON_DOM_MISMATCH"
ABORTED_S3_SIBLING_LEDGER_EMIT_MISSING = "ABORTED_S3_SIBLING_LEDGER_EMIT_MISSING"
ABORTED_S3_LEDGER_EMIT_MISSING = "ABORTED_S3_LEDGER_EMIT_MISSING"
ABORTED_S3_LEDGER_PAYLOAD_INVALID = "ABORTED_S3_LEDGER_PAYLOAD_INVALID"
ABORTED_S3_POST_REGISTRATION_NOT_READY = "ABORTED_S3_POST_REGISTRATION_NOT_READY"
ABORTED_S3_DIAG_BINDING_NOT_READY = "ABORTED_S3_DIAG_BINDING_NOT_READY"
ABORTED_S3_SERVER_WRAPPER_INTEGRITY = "ABORTED_S3_SERVER_WRAPPER_INTEGRITY"


def build_setup_readiness_table(
    *,
    runtime_sha: str,
    auth_restored: bool | None,
    start_latch_pass: bool | None,
    room_id: str,
    streamlit_session_id: str,
    pause_control_ready: bool | None,
    sibling_layers: dict[str, Any] | None = None,
    s3_ledger_found: bool | None,
    post_registration_ready: bool | None,
    binding_ok: bool | None,
    server_wrapper_integrity_ok: bool | None = None,
) -> dict[str, Any]:
    layers = dict(sibling_layers or {})
    import_ok = layers.get("import_effective_ok")
    if import_ok is None:
        import_ok = layers.get("sibling_import_ok")
    return {
        "Runtime SHA": runtime_sha or "",
        "Auth restored": auth_restored,
        "Canonical Start/latch": start_latch_pass,
        "Room ID": room_id or "",
        "Streamlit session": streamlit_session_id or "",
        "Control Center / Pause": pause_control_ready,
        "Sibling callsite DOM": layers.get("sibling_callsite_found"),
        "Sibling import OK": import_ok,
        "Sibling entry DOM": layers.get("sibling_entry_found"),
        "Sibling diag enabled": layers.get("sibling_diag_enabled"),
        "Sibling button DOM": layers.get("sibling_button_found"),
        "Sibling PRE declaration": layers.get("sibling_pre_button_reached"),
        "Sibling POST declaration": layers.get("sibling_post_button_return_reached"),
        "Sibling button call returned": layers.get("sibling_button_call_returned_reached"),
        "Sibling post-registration checkpoint": layers.get("sibling_post_registration_returned_reached"),
        "Sibling setup export complete": layers.get("sibling_setup_export_complete_reached"),
        "Sibling ledger DOM": layers.get("sibling_ledger_found"),
        "S3 ledger DOM": s3_ledger_found,
        "POST_REGISTRATION": post_registration_ready,
        "S3_DIAG_BINDING": binding_ok,
        "Server wrapper integrity": server_wrapper_integrity_ok,
    }


def setup_ready_for_sibling_click(table: dict[str, Any]) -> bool:
    required_truthy = (
        "Auth restored",
        "Canonical Start/latch",
        "Control Center / Pause",
        "Sibling callsite DOM",
        "Sibling entry DOM",
        "Sibling diag enabled",
        "Sibling button DOM",
        "Sibling ledger DOM",
        "S3 ledger DOM",
        "POST_REGISTRATION",
        "S3_DIAG_BINDING",
        "Server wrapper integrity",
    )
    for key in required_truthy:
        if table.get(key) is not True:
            return False
    if table.get("Sibling import OK") is not True:
        return False
    if not str(table.get("Room ID") or "").strip():
        return False
    if not str(table.get("Streamlit session") or "").strip():
        return False
    return True


def classify_setup_early_exception(sibling_layers: dict[str, Any]) -> tuple[str | None, str]:
    if sibling_layers.get("checkpoint_sibling_render_exception"):
        return ABORTED_S3_SIBLING_BUTTON_CALL_EXCEPTION, "sibling_render_exception"
    if sibling_layers.get("checkpoint_sibling_button_call_exception"):
        return ABORTED_S3_SIBLING_BUTTON_CALL_EXCEPTION, "st_button_call_exception"
    if sibling_layers.get("checkpoint_sibling_post_registration_exception"):
        return ABORTED_S3_SIBLING_BUTTON_CALL_EXCEPTION, "post_registration_snapshot_exception"
    return None, ""


def classify_s3_ledger_scrape_issues(
    *,
    s3_ledger_scrape: dict[str, Any],
    readiness_scrape: dict[str, Any] | None = None,
) -> tuple[str | None, str]:
    if not s3_ledger_scrape.get("found"):
        return None, ""
    if not s3_ledger_scrape.get("parse_ok"):
        err = str(s3_ledger_scrape.get("parse_error") or "parse_failed")[:120]
        return ABORTED_S3_LEDGER_PAYLOAD_INVALID, f"s3_ledger_json_parse_failed:{err}"
    payload = s3_ledger_scrape.get("payload")
    if not payload_has_setup_metadata(payload if isinstance(payload, dict) else None):
        return ABORTED_S3_LEDGER_PAYLOAD_INVALID, "s3_ledger_payload_incomplete"
    readiness_scrape = readiness_scrape or {}
    if readiness_scrape.get("found") and not readiness_scrape.get("parse_ok"):
        err = str(readiness_scrape.get("parse_error") or "parse_failed")[:120]
        return ABORTED_S3_LEDGER_PAYLOAD_INVALID, f"s3_readiness_json_parse_failed:{err}"
    if readiness_scrape.get("found") and readiness_scrape.get("parse_ok"):
        from stage1_s3_server_registry_scrape import reconcile_s3_readiness_vs_ledger

        rec = reconcile_s3_readiness_vs_ledger(ledger_scrape=s3_ledger_scrape, readiness_scrape=readiness_scrape)
        if rec.get("mismatch"):
            return ABORTED_S3_LEDGER_PAYLOAD_INVALID, f"s3_readiness_surface_mismatch:{rec.get('mismatch_reason')}"
    return None, ""


def payload_has_setup_metadata(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    if not isinstance(payload.get("post_registration"), dict):
        return False
    if not isinstance(payload.get("s3_diag_binding"), dict):
        return False
    return True


def classify_setup_failure(
    *,
    pause_ready: dict[str, Any],
    sibling_layers: dict[str, Any],
    s3_ledger_scrape: dict[str, Any],
    post_registration: dict[str, Any],
    binding: dict[str, Any],
    after_stabilization: bool = False,
    readiness_scrape: dict[str, Any] | None = None,
) -> tuple[str | None, str]:
    if not pause_ready.get("ready"):
        return ABORTED_S3_CONTROL_CENTER_NOT_READY, "pause_control_not_ready"
    if not sibling_layers.get("sibling_callsite_found"):
        return ABORTED_S3_SIBLING_CALLSITE_NOT_REACHED, "sibling_callsite_missing"

    if sibling_layers.get("import_evidence_consistent") is False:
        return ABORTED_S3_SETUP_EVIDENCE_CONTRADICTION, "import_direct_vs_downstream_contradiction"

    direct_false = sibling_layers.get("sibling_import_ok_direct") is False
    entry = bool(sibling_layers.get("sibling_entry_found"))
    if direct_false and entry:
        return ABORTED_S3_SETUP_EVIDENCE_CONTRADICTION, "import_false_but_function_entered"

    effective = sibling_layers.get("import_effective_ok")
    if effective is None:
        effective = sibling_layers.get("sibling_import_ok")

    if effective is not True:
        if direct_false and not entry:
            return ABORTED_S3_SIBLING_IMPORT_FAILED, "sibling_import_failed"
        if not entry:
            return ABORTED_S3_SIBLING_IMPORT_FAILED, "sibling_import_unproven"
        return ABORTED_S3_SIBLING_FUNCTION_NOT_ENTERED, "sibling_render_entry_missing"

    if not sibling_layers.get("sibling_entry_found"):
        return ABORTED_S3_SIBLING_FUNCTION_NOT_ENTERED, "sibling_render_entry_missing"
    if sibling_layers.get("sibling_diag_enabled") is not True:
        return ABORTED_S3_SIBLING_DIAG_DISABLED, "solo_diag_disabled_at_entry"

    if sibling_layers.get("checkpoint_sibling_render_exception"):
        return ABORTED_S3_SIBLING_BUTTON_CALL_EXCEPTION, "sibling_render_exception"

    if sibling_layers.get("checkpoint_sibling_button_call_exception"):
        return ABORTED_S3_SIBLING_BUTTON_CALL_EXCEPTION, "st_button_call_exception"

    if sibling_layers.get("sibling_pre_button_reached") and not sibling_layers.get(
        "sibling_button_call_returned_reached"
    ):
        if not sibling_layers.get("checkpoint_sibling_button_call_exception"):
            return ABORTED_S3_SIBLING_BUTTON_CALL_NOT_RETURNED, "button_call_did_not_return_checkpoint"

    if sibling_layers.get("sibling_button_call_returned_reached") and not sibling_layers.get(
        "sibling_post_registration_returned_reached"
    ):
        if sibling_layers.get("checkpoint_sibling_post_registration_exception"):
            return ABORTED_S3_SIBLING_BUTTON_CALL_EXCEPTION, "post_registration_snapshot_exception"
        return ABORTED_S3_SIBLING_POST_REGISTRATION_NOT_REACHED, "post_registration_checkpoint_missing"

    if sibling_layers.get("sibling_post_registration_returned_reached") and not sibling_layers.get(
        "sibling_button_found"
    ):
        return ABORTED_S3_SIBLING_BUTTON_DOM_MISMATCH, "exact_button_dom_absent_after_post_registration"

    if not sibling_layers.get("sibling_button_found"):
        if sibling_layers.get("sibling_pre_button_reached") and not sibling_layers.get(
            "sibling_post_button_return_reached"
        ):
            return ABORTED_S3_SIBLING_BUTTON_NOT_MOUNTED, "sibling_button_missing_after_pre_declaration_only"
        if sibling_layers.get("sibling_declaration_reached"):
            return ABORTED_S3_SIBLING_BUTTON_NOT_MOUNTED, "sibling_button_missing_after_declaration"
        return ABORTED_S3_SIBLING_BUTTON_NOT_MOUNTED, "sibling_button_missing"
    if s3_ledger_scrape.get("found"):
        invalid, invalid_note = classify_s3_ledger_scrape_issues(
            s3_ledger_scrape=s3_ledger_scrape,
            readiness_scrape=readiness_scrape,
        )
        if invalid:
            return invalid, invalid_note
    if not sibling_layers.get("sibling_ledger_found"):
        if after_stabilization and sibling_layers.get("sibling_post_button_return_reached"):
            return (
                ABORTED_S3_SIBLING_LEDGER_EMIT_MISSING,
                "sibling_hidden_ledger_persistently_missing_after_setup_stabilization",
            )
        if sibling_layers.get("sibling_post_button_return_reached"):
            return ABORTED_S3_SIBLING_LEDGER_EMIT_MISSING, "sibling_hidden_ledger_missing_after_post_declaration"
        return ABORTED_S3_SIBLING_LEDGER_EMIT_MISSING, "sibling_hidden_ledger_missing"
    if not s3_ledger_scrape.get("found"):
        if after_stabilization:
            return ABORTED_S3_LEDGER_EMIT_MISSING, "s3_ledger_persistently_missing_after_setup_stabilization"
        if sibling_layers.get("sibling_setup_export_complete_reached"):
            return ABORTED_S3_LEDGER_EMIT_MISSING, "s3_ledger_dom_missing_after_export_complete"
        return ABORTED_S3_LEDGER_EMIT_MISSING, "s3_ledger_dom_missing"
    reg_id = str(post_registration.get("registered_widget_id") or "")
    if not reg_id.startswith("$$ID-"):
        return ABORTED_S3_POST_REGISTRATION_NOT_READY, "post_registration_id_missing"
    if not binding.get("sessionstate_binding_ok"):
        return ABORTED_S3_DIAG_BINDING_NOT_READY, "sessionstate_binding_not_ok"
    integrity = binding.get("server_wrapper_integrity_ok")
    if integrity is False:
        return ABORTED_S3_SERVER_WRAPPER_INTEGRITY, "live_wrapper_integrity_failed"
    return None, "setup_pass"


def classify_setup_failure_legacy_probe(
    *,
    pause_ready: dict[str, Any],
    sibling_scrape: dict[str, Any],
    s3_ledger_scrape: dict[str, Any],
    post_registration: dict[str, Any],
    binding: dict[str, Any],
) -> tuple[str | None, str]:
    """Coarse harness 2df9278 path when layered scrape unavailable."""
    if not pause_ready.get("ready"):
        return ABORTED_S3_CONTROL_CENTER_NOT_READY, "pause_control_not_ready"
    if not sibling_scrape.get("probe_found"):
        return ABORTED_S3_SIBLING_PROBE_NOT_RENDERED, "sibling_probe_missing"
    if not s3_ledger_scrape.get("found"):
        return ABORTED_S3_LEDGER_EMIT_MISSING, "s3_ledger_dom_missing"
    reg_id = str(post_registration.get("registered_widget_id") or "")
    if not reg_id.startswith("$$ID-"):
        return ABORTED_S3_POST_REGISTRATION_NOT_READY, "post_registration_id_missing"
    if not binding.get("sessionstate_binding_ok"):
        return ABORTED_S3_DIAG_BINDING_NOT_READY, "sessionstate_binding_not_ok"
    return None, "setup_pass"


def r3_classification_allowed(classification: str) -> bool:
    if classification.startswith("ABORTED"):
        return False
    if classification.startswith("BUTTON_DISPATCH_S3_R3"):
        return True
    if classification in (
        "BUTTON_DISPATCH_S3_R4_TRIGGER_LOST_DURING_STATE_APPLY",
        "BUTTON_DISPATCH_S3_R5_REGISTER_WIDGET_VALUE_LOST",
        "BUTTON_DISPATCH_S3_R6_BUTTON_RESULT_PROPAGATION",
        "BUTTON_DISPATCH_S3_R7_NONDETERMINISTIC_RECOVERY",
    ):
        return True
    return classification.startswith("BUTTON_DISPATCH_S3_R2")
