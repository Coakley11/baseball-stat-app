"""Same-run sibling SERVER_STATE_APPLIED → REGISTER_RESULT → st.button correlation (harness)."""

from __future__ import annotations

from typing import Any

S3_REGISTER_RESULT_SAME_RUN_NOT_OBSERVED = "S3_REGISTER_RESULT_SAME_RUN_NOT_OBSERVED"

_SIBLING_KEY_PREFIX = "stage1_pause_sibling_return_"
_SIBLING_KEY_SUFFIX = "_diag"


def _sid(r: dict[str, Any]) -> str:
    return str(r.get("streamlit_session_id") or "")[:64]


def _seq(r: dict[str, Any]) -> int | None:
    for key in ("script_run_seq", "full_app_run_seq"):
        raw = r.get(key)
        if raw is None or raw == "":
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def _ts(r: dict[str, Any]) -> float:
    try:
        return float(r.get("ts") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _is_sibling_row(r: dict[str, Any], *, wire_widget_id: str = "", user_key: str = "") -> bool:
    wid = str(wire_widget_id or "").strip()
    uk = str(user_key or "").strip()
    if uk and (
        str(r.get("user_key") or "") == uk
        or str(r.get("widget_key") or "") == uk
        or str(r.get("widget_user_key") or "") == uk
    ):
        return True
    if wid and wid in (
        str(r.get("metadata_id") or ""),
        str(r.get("authoritative_widget_id") or ""),
        str(r.get("registered_widget_id") or ""),
        str(r.get("exact_widget_id") or ""),
    ):
        return True
    blob_keys = ("activated_triggers", "pause_sibling_proto", "sibling_proto")
    if wid and any(wid in str(r.get(k) or "") for k in blob_keys):
        return True
    if bool(r.get("pause_sibling_present")) or bool(r.get("sibling_present")):
        return True
    uk_row = str(r.get("user_key") or r.get("widget_key") or r.get("widget_user_key") or "")
    return uk_row.startswith(_SIBLING_KEY_PREFIX) and uk_row.endswith(_SIBLING_KEY_SUFFIX)


def _sibling_applied(r: dict[str, Any], *, wire_widget_id: str = "") -> bool:
    if r.get("phase") != "SERVER_STATE_APPLIED":
        return False
    if not _is_sibling_row(r, wire_widget_id=wire_widget_id):
        return False
    if r.get("trigger_from_deserialized") is True:
        return True
    if str(r.get("deserialized_value_repr") or "").strip().lower() in {"true", "1"}:
        return True
    wid = str(wire_widget_id or "").strip()
    if wid and wid == str(r.get("exact_widget_id") or "") and r.get("present_in_new_widget_state"):
        return True
    return bool(r.get("sibling_present")) and bool(r.get("pause_present") or r.get("trigger_from_deserialized"))


def _fragment_executed(r: dict[str, Any], *, target_fragment_id: str) -> bool:
    want = str(target_fragment_id or "").strip()
    if not want:
        return False
    if want == str(r.get("fragment_id") or r.get("thread_state_fragment_id") or r.get("current_fragment_id_ctx") or ""):
        return True
    ids = r.get("fragment_ids_this_run") or r.get("fragment_id_queue") or []
    if isinstance(ids, (list, tuple, set)) and want in {str(x) for x in ids}:
        return True
    return want in str(r.get("fragment_ids_this_run") or "")


def _same_run_window(
    rows: list[dict[str, Any]],
    *,
    applied: dict[str, Any],
) -> tuple[dict[str, Any] | None, float, float, int | None]:
    """Return (run_script_row, window_start_ts, window_end_ts, script_run_seq)."""
    ap_ts = _ts(applied)
    run_scripts = sorted(
        [r for r in rows if r.get("phase") == "SCRIPTRUNNER_RUN_SCRIPT_ENTRY"],
        key=_ts,
    )
    run_row = None
    for r in run_scripts:
        if _ts(r) <= ap_ts + 1e-9:
            run_row = r
        else:
            break
    if run_row is None and run_scripts:
        # Coalesced apply immediately after run_script; allow nearest prior within 2s.
        prior = [r for r in run_scripts if _ts(r) <= ap_ts]
        run_row = prior[-1] if prior else None
    window_start = _ts(run_row) if run_row else ap_ts
    window_end = 1e18
    for r in run_scripts:
        if _ts(r) > window_start + 1e-9:
            window_end = _ts(r)
            break
    return run_row, window_start, window_end, _seq(run_row) if run_row else _seq(applied)


def _in_window(r: dict[str, Any], *, start: float, end: float, seq: int | None) -> bool:
    rseq = _seq(r)
    if seq is not None and rseq is not None:
        return rseq == seq
    t = _ts(r)
    return start - 1e-6 <= t < end


def _same_run_control_flow_boundary(out: dict[str, Any]) -> str:
    """Supplemental Pause/sibling control-flow label. Does not affect R5/R6/R7."""
    if out.get("sibling_render_entered"):
        return "sibling_render_entered"
    if out.get("sibling_callsite_import_attempt"):
        return "sibling_import_attempted"
    if out.get("sibling_callsite_initial"):
        return "sibling_callsite_entered"
    if out.get("st_rerun_about_to_call") and str(out.get("st_rerun_about_to_call_source") or "") in (
        "",
        "pause_draft",
    ):
        return "st_rerun_about_to_call_before_sibling_callsite"
    if out.get("pause_rerun_request_entry"):
        return "pause_rerun_requested"
    if out.get("pause_branch_entered"):
        return "pause_branch_entered"
    if out.get("pause_button_call_returned") is False:
        return "pause_branch_not_entered"
    if out.get("pause_button_call_returned") is True:
        return "pause_branch_not_entered"
    return "pause_button_return_not_observed"


def correlate_sibling_same_run_registration(
    rows: list[dict[str, Any]] | None,
    *,
    wire_widget_id: str = "",
    user_key: str = "",
    target_fragment_id: str = "",
) -> dict[str, Any]:
    """Correlate sibling SERVER_STATE_APPLIED with same-run register/button evidence."""
    src = [r for r in list(rows or []) if isinstance(r, dict)]
    wid = str(wire_widget_id or "").strip()
    uk = str(user_key or "").strip()
    target_fid = str(target_fragment_id or "").strip()

    out: dict[str, Any] = {
        "applied_event_id": "",
        "applied_ts": None,
        "script_run_seq": None,
        "full_app_run_seq": None,
        "diagnostic_run_id": "",
        "run_script_event_id": "",
        "target_fragment_id": target_fid,
        "target_fragment_executed": False,
        "sibling_render_entered": False,
        "sibling_declaration_entered": False,
        "register_entry_event_id": "",
        "register_result_event_id": "",
        "register_widget_result_value": None,
        "register_widget_value_changed": None,
        "button_call_returned_event_id": "",
        "st_button_returned": None,
        "declaration_invocation_id": "",
        "correlation_complete": False,
        "first_missing_boundary": "server_state_applied_sibling_absent",
        "server_applied_sibling": False,
        "window_start_ts": None,
        "window_end_ts": None,
        "pause_button_call_returned": None,
        "pause_button_call_returned_event_id": "",
        "pause_branch_entered": False,
        "pause_branch_entered_event_id": "",
        "pause_rerun_request_entry": False,
        "pause_rerun_request_entry_event_id": "",
        "st_rerun_about_to_call": False,
        "st_rerun_about_to_call_event_id": "",
        "st_rerun_about_to_call_source": "",
        "live_draft_rerun_blocked": False,
        "live_draft_rerun_blocked_event_id": "",
        "sibling_callsite_initial": False,
        "sibling_callsite_import_attempt": False,
        "sibling_callsite_import_ok": None,
        "same_run_control_flow_boundary": "pause_button_return_not_observed",
    }

    applied_rows = [r for r in src if _sibling_applied(r, wire_widget_id=wid)]
    if not applied_rows:
        return out
    applied = sorted(applied_rows, key=_ts)[-1]
    out["applied_event_id"] = str(applied.get("event_id") or "")
    out["applied_ts"] = _ts(applied)
    out["server_applied_sibling"] = True
    out["diagnostic_run_id"] = str(applied.get("diagnostic_run_id") or "")[:64]

    run_row, start, end, seq = _same_run_window(src, applied=applied)
    out["run_script_event_id"] = str((run_row or {}).get("event_id") or "")
    out["script_run_seq"] = seq
    out["full_app_run_seq"] = seq
    out["window_start_ts"] = start
    out["window_end_ts"] = end if end < 1e18 else None

    window = [r for r in src if _in_window(r, start=start, end=end, seq=seq)]

    frag_rows = [
        r
        for r in window
        if r.get("phase") in ("CONTROL_CENTER_FRAGMENT_ENTRY", "FRAGMENT_OWNER_NOTE", "SIBLING_RENDER_ENTRY")
    ]
    if target_fid:
        out["target_fragment_executed"] = any(_fragment_executed(r, target_fragment_id=target_fid) for r in frag_rows) or any(
            _fragment_executed(r, target_fragment_id=target_fid) for r in window if r.get("phase") == "SCRIPTRUNNER_RUN_SCRIPT_ENTRY"
        )
        # Sibling render on the target fragment also proves execution of that fragment body path.
        if not out["target_fragment_executed"]:
            out["target_fragment_executed"] = any(
                r.get("phase") == "SIBLING_RENDER_ENTRY" and _fragment_executed(r, target_fragment_id=target_fid) for r in window
            )
    else:
        out["target_fragment_executed"] = any(r.get("phase") == "CONTROL_CENTER_FRAGMENT_ENTRY" for r in window) or any(
            r.get("phase") == "SIBLING_RENDER_ENTRY" for r in window
        )

    render_rows = [
        r
        for r in window
        if r.get("phase") == "SIBLING_RENDER_ENTRY" and _is_sibling_row(r, wire_widget_id=wid, user_key=uk)
    ]
    out["sibling_render_entered"] = bool(render_rows)

    decl_rows = [
        r
        for r in window
        if r.get("phase") == "SIBLING_BUTTON_DECLARATION_ENTRY" and _is_sibling_row(r, wire_widget_id=wid, user_key=uk)
    ]
    out["sibling_declaration_entered"] = bool(decl_rows)
    if decl_rows:
        out["declaration_invocation_id"] = str(decl_rows[-1].get("declaration_invocation_id") or "")[:64]

    reg_entries = [
        r
        for r in window
        if r.get("phase") == "REGISTER_ENTRY" and _is_sibling_row(r, wire_widget_id=wid, user_key=uk)
    ]
    if reg_entries:
        # Prefer invocation match, else first in window.
        inv = out["declaration_invocation_id"]
        chosen_e = next((r for r in reg_entries if inv and str(r.get("declaration_invocation_id") or "") == inv), reg_entries[0])
        out["register_entry_event_id"] = str(chosen_e.get("event_id") or "")

    reg_results = [
        r
        for r in window
        if r.get("phase") == "REGISTER_RESULT" and _is_sibling_row(r, wire_widget_id=wid, user_key=uk)
    ]
    if reg_results:
        inv = out["declaration_invocation_id"]
        chosen = next((r for r in reg_results if inv and str(r.get("declaration_invocation_id") or "") == inv), None)
        if chosen is None:
            # Same-run: earliest REGISTER_RESULT after applied (or first in window if all before apply within run).
            after_apply = [r for r in reg_results if _ts(r) >= float(out["applied_ts"] or 0) - 1e-6]
            chosen = after_apply[0] if after_apply else reg_results[0]
        out["register_result_event_id"] = str(chosen.get("event_id") or "")
        v = chosen.get("register_widget_result_value")
        out["register_widget_result_value"] = bool(v) if isinstance(v, bool) else None
        vc = chosen.get("register_widget_value_changed")
        out["register_widget_value_changed"] = bool(vc) if isinstance(vc, bool) else vc
        if not out["declaration_invocation_id"]:
            out["declaration_invocation_id"] = str(chosen.get("declaration_invocation_id") or "")[:64]
        if out["diagnostic_run_id"] == "":
            out["diagnostic_run_id"] = str(chosen.get("diagnostic_run_id") or "")[:64]

    btn_rows = [
        r
        for r in window
        if r.get("phase") == "SIBLING_BUTTON_CALL_RETURNED" and _is_sibling_row(r, wire_widget_id=wid, user_key=uk)
    ]
    if btn_rows:
        inv = out["declaration_invocation_id"]
        chosen_b = next((r for r in btn_rows if inv and str(r.get("declaration_invocation_id") or "") == inv), btn_rows[-1])
        out["button_call_returned_event_id"] = str(chosen_b.get("event_id") or "")
        if chosen_b.get("st_button_returned") is not None:
            out["st_button_returned"] = bool(chosen_b.get("st_button_returned"))
        elif chosen_b.get("returned_value") is not None:
            out["st_button_returned"] = bool(chosen_b.get("returned_value"))

    pause_btn_rows = sorted(
        [r for r in window if r.get("phase") == "PAUSE_BUTTON_CALL_RETURNED"],
        key=_ts,
    )
    if pause_btn_rows:
        chosen_p = pause_btn_rows[-1]
        out["pause_button_call_returned_event_id"] = str(chosen_p.get("event_id") or "")
        if chosen_p.get("st_button_returned") is not None:
            out["pause_button_call_returned"] = bool(chosen_p.get("st_button_returned"))

    pause_branch_rows = sorted(
        [r for r in window if r.get("phase") == "PAUSE_BRANCH_ENTERED"],
        key=_ts,
    )
    if pause_branch_rows:
        out["pause_branch_entered"] = True
        out["pause_branch_entered_event_id"] = str(pause_branch_rows[-1].get("event_id") or "")

    pause_rerun_rows = sorted(
        [r for r in window if r.get("phase") == "PAUSE_RERUN_REQUEST_ENTRY"],
        key=_ts,
    )
    if pause_rerun_rows:
        out["pause_rerun_request_entry"] = True
        out["pause_rerun_request_entry_event_id"] = str(pause_rerun_rows[-1].get("event_id") or "")

    about_rows = sorted(
        [
            r
            for r in window
            if r.get("phase") == "LIVE_DRAFT_ST_RERUN_ABOUT_TO_CALL"
            and str(r.get("source") or "") in ("", "pause_draft")
        ],
        key=_ts,
    )
    pause_about_rows = [r for r in about_rows if str(r.get("source") or "") == "pause_draft"] or about_rows
    if pause_about_rows:
        chosen_a = pause_about_rows[-1]
        out["st_rerun_about_to_call"] = True
        out["st_rerun_about_to_call_event_id"] = str(chosen_a.get("event_id") or "")
        out["st_rerun_about_to_call_source"] = str(chosen_a.get("source") or "")[:64]

    blocked_rows = sorted(
        [r for r in window if r.get("phase") == "LIVE_DRAFT_RERUN_BLOCKED"],
        key=_ts,
    )
    if blocked_rows:
        out["live_draft_rerun_blocked"] = True
        out["live_draft_rerun_blocked_event_id"] = str(blocked_rows[-1].get("event_id") or "")

    callsite_rows = sorted(
        [r for r in window if r.get("phase") == "SIBLING_CALLSITE_ENTRY"],
        key=_ts,
    )
    initial_callsite = [r for r in callsite_rows if not bool(r.get("import_attempted"))]
    import_callsite = [r for r in callsite_rows if bool(r.get("import_attempted"))]
    out["sibling_callsite_initial"] = bool(initial_callsite)
    out["sibling_callsite_import_attempt"] = bool(import_callsite)
    if import_callsite:
        ok_v = import_callsite[-1].get("import_ok")
        out["sibling_callsite_import_ok"] = bool(ok_v) if ok_v is not None else None

    out["same_run_control_flow_boundary"] = _same_run_control_flow_boundary(out)

    # Boundary resolution (first missing).
    if not out["target_fragment_executed"] and target_fid:
        out["first_missing_boundary"] = "target_fragment_not_executed"
    elif not out["sibling_render_entered"]:
        out["first_missing_boundary"] = "sibling_render_not_entered"
    elif not out["sibling_declaration_entered"]:
        out["first_missing_boundary"] = "sibling_declaration_not_entered"
    elif not out["register_entry_event_id"]:
        out["first_missing_boundary"] = "register_entry_absent"
    elif out["register_widget_result_value"] is None:
        out["first_missing_boundary"] = "register_result_absent"
    elif out["st_button_returned"] is None:
        out["first_missing_boundary"] = "button_return_absent"
    else:
        out["first_missing_boundary"] = ""
        out["correlation_complete"] = True

    return out


def register_result_for_classifier(correlation: dict[str, Any] | None) -> bool | None:
    """Authoritative RegisterWidgetResult for R5/R6 — None when same-run B unknown."""
    c = dict(correlation or {})
    if not c.get("server_applied_sibling"):
        return None
    if c.get("register_widget_result_value") is None:
        return None
    return bool(c.get("register_widget_result_value"))


def st_button_for_classifier(correlation: dict[str, Any] | None) -> bool | None:
    c = dict(correlation or {})
    if c.get("st_button_returned") is None:
        return None
    return bool(c.get("st_button_returned"))
