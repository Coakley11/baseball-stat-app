"""Classify first internal callback-metadata boundary CM1–CM10."""

from __future__ import annotations

from typing import Any

INTERNAL_META = "production_stage1_internal_widget_metadata_registered"
BACKEND_STATE = "production_stage1_backend_widget_state_after_backmsg"
DISPATCH = "production_stage1_callback_dispatch_evaluated"
CALLBACK_DISPATCH_EVALUATED = DISPATCH
REGISTRATION = "production_stage1_callback_registration"
PROD_ENTERED = "production_stage1_prod_on_change_entered"
CONTROL_ENTERED = "production_stage1_control_on_change_entered"


def _rows(rows: list[dict[str, Any]], event: str) -> list[dict[str, Any]]:
    return [r for r in rows if isinstance(r, dict) and str(r.get("event") or "") == event]


def _surface(rows: list[dict[str, Any]], surface: str) -> list[dict[str, Any]]:
    return [r for r in rows if str(r.get("diagnostic_surface") or "") == surface]


def _last_token_row(rows: list[dict[str, Any]], token: str) -> dict[str, Any]:
    if not token:
        return rows[-1] if rows else {}
    for r in reversed(rows):
        rep = str(r.get("deserialized_value_repr") or r.get("new_value_repr") or "")
        if token in rep:
            return r
    return rows[-1] if rows else {}


def build_internal_comparison(
    *,
    filtered_rows: list[dict[str, Any]],
    exact_token: str,
    production_widget_key: str,
) -> dict[str, Any]:
    case_meta = _surface(_rows(filtered_rows, INTERNAL_META), "case_a")
    prod_meta = [r for r in _rows(filtered_rows, INTERNAL_META) if r.get("diagnostic_surface") != "case_a"]
    if production_widget_key:
        prod_meta = [r for r in prod_meta if r.get("widget_key") == production_widget_key] or prod_meta
    case_dispatch = _surface(_rows(filtered_rows, DISPATCH), "case_a") or _rows(filtered_rows, DISPATCH)[:4]
    prod_dispatch = _rows(filtered_rows, DISPATCH)
    if production_widget_key:
        prod_dispatch = [r for r in prod_dispatch if r.get("widget_key") == production_widget_key] or prod_dispatch

    def _lane(meta_rows: list[dict], dispatch_rows: list[dict], label: str) -> dict[str, Any]:
        m = meta_rows[-1] if meta_rows else {}
        d = _last_token_row(dispatch_rows, exact_token) if exact_token else (dispatch_rows[-1] if dispatch_rows else {})
        return {
            "label": label,
            "application_callback_argument_present": m.get("application_on_change_argument_present"),
            "application_callback_identity": m.get("application_on_change_identity"),
            "internal_metadata_callback_present": m.get("metadata_callback_present"),
            "internal_metadata_callbacks_present": m.get("metadata_callbacks_present"),
            "callback_registered_in_metadata": m.get("callback_registered_in_metadata"),
            "authoritative_widget_id": m.get("authoritative_widget_id"),
            "new_frontend_widget_state_repr": d.get("new_value_repr") or d.get("deserialized_value_repr"),
            "prior_widget_state_repr": d.get("old_value_repr") or d.get("old_deserialized_value_repr"),
            "changed_value_result": d.get("widget_changed_result"),
            "callback_dispatch_selected": d.get("callback_selected"),
            "callback_dispatch_skip_reason": d.get("skip_reason"),
            "callback_dispatch_identity": d.get("callback_identity"),
        }

    case_lane = _lane(case_meta, case_dispatch, "case_a")
    prod_lane = _lane(prod_meta, prod_dispatch, "production")
    earliest = ""
    for field in (
        "application_callback_argument_present",
        "callback_registered_in_metadata",
        "internal_metadata_callback_present",
        "changed_value_result",
        "callback_dispatch_selected",
    ):
        if case_lane.get(field) != prod_lane.get(field):
            earliest = field
            break
    return {
        "case_a": case_lane,
        "production": prod_lane,
        "earliest_internal_difference_field": earliest,
    }


def classify_callback_metadata_boundary(
    *,
    filtered_rows: list[dict[str, Any]],
    exact_token: str,
    production_widget_key: str = "solo_countdown_wake_solo_persistent",
) -> dict[str, Any]:
    comparison = build_internal_comparison(
        filtered_rows=filtered_rows,
        exact_token=exact_token,
        production_widget_key=production_widget_key,
    )
    prod_meta_rows = [
        r
        for r in _rows(filtered_rows, INTERNAL_META)
        if r.get("diagnostic_surface") != "case_a"
        and (not production_widget_key or r.get("widget_key") == production_widget_key)
    ]
    prod_regs = [
        r
        for r in _rows(filtered_rows, REGISTRATION)
        if not production_widget_key or r.get("widget_key") == production_widget_key
    ]
    prod_dispatch = [
        r
        for r in _rows(filtered_rows, DISPATCH)
        if not production_widget_key or r.get("widget_key") == production_widget_key
    ]
    prod_backend = [
        r
        for r in _rows(filtered_rows, BACKEND_STATE)
        if not production_widget_key or r.get("widget_key") == production_widget_key
    ]
    prod_entered = _rows(filtered_rows, PROD_ENTERED)
    control_entered = _rows(filtered_rows, CONTROL_ENTERED)

    last_meta = prod_meta_rows[-1] if prod_meta_rows else {}
    last_dispatch = _last_token_row(prod_dispatch, exact_token)
    last_backend = _last_token_row(prod_backend, exact_token)
    app_passed = bool(last_meta.get("application_on_change_argument_present"))
    meta_has = bool(last_meta.get("callback_registered_in_metadata"))
    hist: list[dict[str, Any]] = []
    wid = str(last_meta.get("authoritative_widget_id") or "")
    for r in prod_meta_rows:
        if wid and str(r.get("authoritative_widget_id") or "") == wid:
            hist.append(
                {
                    "script_run_seq": r.get("registration_script_run_sequence"),
                    "callback_registered_in_metadata": r.get("callback_registered_in_metadata"),
                    "mount_guard_result": r.get("mount_guard_result"),
                }
            )

    report: dict[str, Any] = {
        "exact_token": exact_token,
        "comparison": comparison,
        "production_metadata_timeline_count": len(prod_meta_rows),
        "production_dispatch_timeline_count": len(prod_dispatch),
        "control_on_change_entered_count": len(control_entered),
        "prod_on_change_entered_count": len(prod_entered),
        "classification": "",
        "rationale": "",
        "architectural_options": [],
        "smallest_correction_boundary": "",
    }

    if control_entered and prod_meta_rows:
        case_meta = _surface(_rows(filtered_rows, INTERNAL_META), "case_a")
        if case_meta and not case_meta[-1].get("callback_registered_in_metadata"):
            report["classification"] = "CM10 — OTHER"
            report["rationale"] = "Case A metadata lacks callback despite working control path."
            return report

    if app_passed and not meta_has:
        report["classification"] = "CM1 — CALLBACK_ARGUMENT_NOT_STORED_IN_WIDGET_METADATA"
        report["rationale"] = "Application passed on_change but WidgetMetadata has no callback/callbacks."
        report["architectural_options"] = [
            "Option A: Canonical V1 declaration + direct returned value (no unsupported on_change surface).",
            "Option B: V2 trigger/state component with documented trigger callback.",
        ]
        report["smallest_correction_boundary"] = report["classification"]
        return report

    if len(hist) >= 2 and any(h.get("callback_registered_in_metadata") for h in hist[:-1]):
        if not hist[-1].get("callback_registered_in_metadata"):
            report["classification"] = "CM2 — CALLBACK_METADATA_OVERWRITTEN_BY_LATER_REGISTRATION"
            report["rationale"] = "Earlier registration stored callback; later same-ID registration cleared it."
            report["smallest_correction_boundary"] = report["classification"]
            return report

    if last_backend and not last_backend.get("in_new_widget_state"):
        report["classification"] = "CM3 — PRODUCTION_WIDGET_STATE_NOT_PRESENT_ON_BACKEND"
        report["rationale"] = "BackMsg processed but widget id absent from _new_widget_state at dispatch."
        report["smallest_correction_boundary"] = report["classification"]
        return report

    if last_dispatch.get("skip_reason") == "widget_value_unchanged" or (
        last_backend.get("in_new_widget_state") and not last_backend.get("widget_changed")
    ):
        report["classification"] = "CM4 — BACKEND_RECEIVES_STATE_BUT_TREATS_VALUE_AS_UNCHANGED"
        report["rationale"] = "New and old widget values compare equal; dispatch skipped."
        report["smallest_correction_boundary"] = report["classification"]
        return report

    reg_id = str((prod_regs[-1] if prod_regs else {}).get("actual_registered_internal_widget_id") or "")
    meta_id = str(last_meta.get("authoritative_widget_id") or "")
    if reg_id and meta_id and reg_id != meta_id:
        report["classification"] = "CM5 — BACKEND_WIDGET_ID_OR_KEY_MAPPING_DIFFERS"
        report["rationale"] = f"Registration id {reg_id[:60]} != metadata id {meta_id[:60]}."
        report["smallest_correction_boundary"] = report["classification"]
        return report

    dup_regs = [r for r in prod_regs if str(r.get("mount_guard_result") or "").startswith("duplicate")]
    if app_passed and not meta_has and dup_regs:
        report["classification"] = "CM7 — SINGLE-MOUNT GUARD_PREVENTS_CALLBACK_METADATA_REFRESH"
        report["rationale"] = "Duplicate-skipped run avoided register_widget; metadata never refreshed."
        report["smallest_correction_boundary"] = report["classification"]
        return report

    if app_passed and not meta_has and prod_meta_rows:
        report["classification"] = "CM6 — PRODUCTION V1 COMPONENT PATH DOES NOT RETAIN ON_CHANGE CALLBACK"
        report["rationale"] = "Wrapper passed on_change but component registration path did not store it."
        report["architectural_options"] = [
            "Option A: Canonical V1 declaration + direct returned value (no unsupported on_change surface).",
            "Option B: V2 trigger/state component with documented trigger callback.",
        ]
        report["smallest_correction_boundary"] = report["classification"]
        return report

    if last_dispatch.get("callback_selected") and not prod_entered:
        report["classification"] = "CM9 — CALLBACK_PRESENT_AND_SELECTED_BUT_INVOCATION_LOST"
        report["rationale"] = "Dispatch selected callback but prod_on_change_entered never fired."
        report["smallest_correction_boundary"] = report["classification"]
        return report

    if last_dispatch.get("skip_reason") == "callback_missing_from_metadata":
        report["classification"] = "CM1 — CALLBACK_ARGUMENT_NOT_STORED_IN_WIDGET_METADATA"
        report["rationale"] = "Dispatch evaluation: callback_missing_from_metadata."
        report["architectural_options"] = [
            "Option A: Canonical V1 declaration + direct returned value (no unsupported on_change surface).",
            "Option B: V2 trigger/state component with documented trigger callback.",
        ]
        report["smallest_correction_boundary"] = report["classification"]
        return report

    report["classification"] = "CM10 — OTHER"
    report["rationale"] = (
        f"earliest_field={comparison.get('earliest_internal_difference_field')!s}; "
        f"dispatch={last_dispatch.get('skip_reason')!s}"
    )
    report["smallest_correction_boundary"] = report["classification"]
    return report
