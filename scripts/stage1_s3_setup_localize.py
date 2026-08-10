"""S3 production gate setup localization (harness-only)."""

from __future__ import annotations

from typing import Any

ABORTED_S3_CONTROL_CENTER_NOT_READY = "ABORTED_S3_CONTROL_CENTER_NOT_READY"
ABORTED_S3_SIBLING_PROBE_NOT_RENDERED = "ABORTED_S3_SIBLING_PROBE_NOT_RENDERED"
ABORTED_S3_SIBLING_CALLSITE_NOT_REACHED = "ABORTED_S3_SIBLING_CALLSITE_NOT_REACHED"
ABORTED_S3_SIBLING_IMPORT_FAILED = "ABORTED_S3_SIBLING_IMPORT_FAILED"
ABORTED_S3_SIBLING_FUNCTION_NOT_ENTERED = "ABORTED_S3_SIBLING_FUNCTION_NOT_ENTERED"
ABORTED_S3_SIBLING_DIAG_DISABLED = "ABORTED_S3_SIBLING_DIAG_DISABLED"
ABORTED_S3_SIBLING_BUTTON_NOT_MOUNTED = "ABORTED_S3_SIBLING_BUTTON_NOT_MOUNTED"
ABORTED_S3_SIBLING_LEDGER_EMIT_MISSING = "ABORTED_S3_SIBLING_LEDGER_EMIT_MISSING"
ABORTED_S3_LEDGER_EMIT_MISSING = "ABORTED_S3_LEDGER_EMIT_MISSING"
ABORTED_S3_POST_REGISTRATION_NOT_READY = "ABORTED_S3_POST_REGISTRATION_NOT_READY"
ABORTED_S3_DIAG_BINDING_NOT_READY = "ABORTED_S3_DIAG_BINDING_NOT_READY"


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
) -> dict[str, Any]:
    layers = dict(sibling_layers or {})
    return {
        "Runtime SHA": runtime_sha or "",
        "Auth restored": auth_restored,
        "Canonical Start/latch": start_latch_pass,
        "Room ID": room_id or "",
        "Streamlit session": streamlit_session_id or "",
        "Control Center / Pause": pause_control_ready,
        "Sibling callsite DOM": layers.get("sibling_callsite_found"),
        "Sibling import OK": layers.get("sibling_import_ok"),
        "Sibling entry DOM": layers.get("sibling_entry_found"),
        "Sibling diag enabled": layers.get("sibling_diag_enabled"),
        "Sibling button DOM": layers.get("sibling_button_found"),
        "Sibling ledger DOM": layers.get("sibling_ledger_found"),
        "S3 ledger DOM": s3_ledger_found,
        "POST_REGISTRATION": post_registration_ready,
        "S3_DIAG_BINDING": binding_ok,
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


def classify_setup_failure(
    *,
    pause_ready: dict[str, Any],
    sibling_layers: dict[str, Any],
    s3_ledger_scrape: dict[str, Any],
    post_registration: dict[str, Any],
    binding: dict[str, Any],
) -> tuple[str | None, str]:
    if not pause_ready.get("ready"):
        return ABORTED_S3_CONTROL_CENTER_NOT_READY, "pause_control_not_ready"
    if not sibling_layers.get("sibling_callsite_found"):
        return ABORTED_S3_SIBLING_CALLSITE_NOT_REACHED, "sibling_callsite_missing"
    if sibling_layers.get("sibling_import_ok") is False:
        return ABORTED_S3_SIBLING_IMPORT_FAILED, "sibling_import_failed"
    if sibling_layers.get("sibling_import_ok") is not True:
        return ABORTED_S3_SIBLING_IMPORT_FAILED, "sibling_import_unknown"
    if not sibling_layers.get("sibling_entry_found"):
        return ABORTED_S3_SIBLING_FUNCTION_NOT_ENTERED, "sibling_render_entry_missing"
    if sibling_layers.get("sibling_diag_enabled") is not True:
        return ABORTED_S3_SIBLING_DIAG_DISABLED, "solo_diag_disabled_at_entry"
    if not sibling_layers.get("sibling_button_found"):
        if sibling_layers.get("sibling_declaration_reached"):
            return ABORTED_S3_SIBLING_BUTTON_NOT_MOUNTED, "sibling_button_missing_after_declaration"
        return ABORTED_S3_SIBLING_BUTTON_NOT_MOUNTED, "sibling_button_missing"
    if not sibling_layers.get("sibling_ledger_found"):
        return ABORTED_S3_SIBLING_LEDGER_EMIT_MISSING, "sibling_hidden_ledger_missing"
    if not s3_ledger_scrape.get("found"):
        return ABORTED_S3_LEDGER_EMIT_MISSING, "s3_ledger_dom_missing"
    reg_id = str(post_registration.get("registered_widget_id") or "")
    if not reg_id.startswith("$$ID-"):
        return ABORTED_S3_POST_REGISTRATION_NOT_READY, "post_registration_id_missing"
    if not binding.get("sessionstate_binding_ok"):
        return ABORTED_S3_DIAG_BINDING_NOT_READY, "sessionstate_binding_not_ok"
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
