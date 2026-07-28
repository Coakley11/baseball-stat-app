"""Runner-only RV1 page/ledger state classification (no production delivery logic)."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

from live_draft_solo_rv_control_probe import RV_LEDGER_B64_PREFIX

READY_EVENTS = frozenset({"script_begin", "rv_entrypoint_entered"})

RV1_PRODUCTION_EVENTS = frozenset(
    {
        "production_room_creation_attempted",
        "production_room_created",
        "production_draft_started",
        "real_room_hydrated",
        "room_state_source",
    }
)


def ledger_rows_for_run(probe: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    return [r for r in list(probe.get("rows") or []) if str(r.get("run_id") or "") == run_id]


def ledger_has_prefix(page_text: str) -> bool:
    return RV_LEDGER_B64_PREFIX in str(page_text or "")


def page_text_has_streamlit_traceback(page_text: str) -> bool:
    """True when visible text includes a Streamlit-style traceback (not a bare 'Error' word)."""
    text = str(page_text or "")
    if "Traceback:" not in text:
        return False
    return ('File "' in text) or ('File "/mount' in text) or ("stException" in text)


def ledger_ready(rows: list[dict[str, Any]], *, page_text: str = "") -> bool:
    if not ledger_has_prefix(page_text) and not rows:
        return False
    events = {str(r.get("event") or "") for r in rows}
    if not ledger_has_prefix(page_text):
        return False
    return READY_EVENTS.issubset(events)


def _production_invalid_reason(events: set[str], rows: list[dict[str, Any]]) -> str:
    if "production_room_creation_failed" in events:
        row = next(r for r in rows if r.get("event") == "production_room_creation_failed")
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        reason = str(extra.get("reason") or row.get("reason") or "unknown")
        return f"INVALID_RV_PRODUCTION_ROOM_CREATION_{reason}"
    if "production_draft_start_failed" in events:
        row = next(r for r in rows if r.get("event") == "production_draft_start_failed")
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        reason = str(extra.get("reason") or row.get("reason") or "unknown")
        return f"INVALID_RV_PRODUCTION_DRAFT_START_{reason}"
    for req in (
        "production_room_creation_attempted",
        "production_room_created",
        "production_draft_started",
    ):
        if req not in events:
            return f"INVALID_RV_PRODUCTION_ROOM_CREATION_missing_{req}"
    if "real_room_hydrated" not in events:
        return "INVALID_RV_REAL_ROOM_HYDRATION_not_hydrated"
    if "room_state_source" not in events:
        return "INVALID_RV_REAL_ROOM_HYDRATION_missing_room_state_source"
    return ""


def classify_page_shell(
    *,
    page_text: str,
    dom: dict[str, Any],
    rows: list[dict[str, Any]],
    probe: dict[str, Any] | None = None,
) -> str:
    """READY_LEDGER | PAGE_NOT_READY | APP_ERROR | AUTH_LOST | ROUTE_NOT_ENTERED | READY_PENDING | READY."""
    text = str(page_text or "")
    lower = text.lower()
    parse = dict((probe or {}).get("_probe_parse") or {})
    probe_rows = list((probe or {}).get("rows") or [])
    if parse.get("decode_ok") and probe_rows:
        return "READY_LEDGER"
    events = {str(r.get("event") or "") for r in rows}
    if dom.get("has_st_exception") or page_text_has_streamlit_traceback(text):
        if not parse.get("decode_ok"):
            return "APP_ERROR"
    if "not signed in" in lower and "signed in as" not in lower and "welcome back" not in lower:
        return "AUTH_LOST"
    loading = bool(dom.get("has_streamlit_app")) and (
        dom.get("app_loading") or ("running" in lower[:500] and "live draft" not in lower)
    )
    if loading and not rows and not ledger_has_prefix(text) and len(text.strip()) < 80:
        return "PAGE_NOT_READY"
    events = {str(r.get("event") or "") for r in rows}
    if ledger_ready(rows, page_text=text):
        return "READY"
    if ledger_has_prefix(text) and not parse.get("decode_ok"):
        return "PAGE_NOT_READY"
    if dom.get("has_streamlit_app") and "rv_entrypoint_entered" not in events:
        if ledger_has_prefix(text) or "script_begin" in events:
            return "READY_PENDING"
        if any(k in lower for k in ("live draft", "pause draft", "start new live draft", "draft board")):
            return "ROUTE_NOT_ENTERED"
        if len(text.strip()) > 200:
            return "ROUTE_NOT_ENTERED"
    if not dom.get("has_streamlit_app"):
        return "PAGE_NOT_READY"
    return "READY_PENDING"


def page_state_to_invalid_reason(state: str, *, probe_parse: dict[str, Any] | None = None) -> str:
    parse = dict(probe_parse or {})
    if state == "PAGE_NOT_READY" and parse.get("prefix_found") and not parse.get("decode_ok"):
        err = str(parse.get("decode_error") or "")
        if err.startswith("PROBE_DECODE_FAILED") or err == "no_b64_after_prefix":
            return "INVALID_RV_CONTROL_PAGE_NOT_READY_OR_PROBE_PARSE_FAILED"
    mapping = {
        "APP_ERROR": "INVALID_RV_CONTROL_APP_ERROR",
        "AUTH_LOST": "INVALID_RV_CONTROL_AUTH_LOST",
        "ROUTE_NOT_ENTERED": "INVALID_RV_CONTROL_ROUTE_NOT_ENTERED",
        "PAGE_NOT_READY": "INVALID_RV_CONTROL_PAGE_NOT_READY",
        "READY_PENDING": "INVALID_RV_CONTROL_PAGE_NOT_OBSERVED",
    }
    return mapping.get(state, "INVALID_RV_CONTROL_PAGE_NOT_OBSERVED")


def _room_id_from_production_created(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("event") == "production_room_created":
            extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
            return str(row.get("room_id") or extra.get("room_id") or "").strip().upper()
    return ""


def classify_rv_real_room_ledger_after_ready(
    rows: list[dict[str, Any]], *, harness_room_id: str = "", step: str = "RV1"
) -> tuple[str, str, str]:
    return classify_rv1_ledger_after_ready(rows, harness_room_id=harness_room_id)


def classify_rv1_ledger_after_ready(
    rows: list[dict[str, Any]],
    *,
    harness_room_id: str = "",
) -> tuple[str, str, str]:
    """Return (phase, verdict, reason) where phase is READY_HYDRATED | invalid setup."""
    events = {str(r.get("event") or "") for r in rows}
    if "rv_real_room_hydration_failed" in events:
        row = next(r for r in rows if r.get("event") == "rv_real_room_hydration_failed")
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        reason = str(
            extra.get("hydration_reason") or extra.get("reason") or row.get("hydration_reason") or "unknown"
        )
        return "invalid", "INVALID", f"INVALID_RV_REAL_ROOM_HYDRATION_{reason}"
    prod_invalid = _production_invalid_reason(events, rows)
    if prod_invalid:
        return "invalid", "INVALID", prod_invalid
    if "real_room_hydrated" not in events:
        if "rv_mount_failed" in events:
            row = next(r for r in rows if r.get("event") == "rv_mount_failed")
            extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
            inv = str(extra.get("invalid") or "").strip()
            if inv.startswith("INVALID_RV_"):
                return "invalid", "INVALID", inv
            reason = str(extra.get("reason") or row.get("reason") or "mount_failed")
            if reason in ("real_room_missing", "room_not_in_session", "token_build_empty"):
                return "invalid", "INVALID", f"INVALID_RV_REAL_ROOM_HYDRATION_{reason}"
            return "invalid", "INVALID", f"INVALID_RV_COMPONENT_NOT_DECLARED_{reason}"
        return "invalid", "INVALID", "INVALID_RV_REAL_ROOM_HYDRATION_not_hydrated"
    hydrated = next(r for r in rows if r.get("event") == "real_room_hydrated")
    created_id = _room_id_from_production_created(rows)
    got = str(hydrated.get("room_id") or "").strip().upper()
    hid = str(harness_room_id or "").strip().upper()
    if created_id and got and created_id != got:
        return "invalid", "INVALID", "INVALID_RV_REAL_ROOM_HYDRATION_room_id_mismatch"
    if hid and got and hid != got:
        return "invalid", "INVALID", "INVALID_RV_REAL_ROOM_HYDRATION_room_id_mismatch"
    pick_ok = hydrated.get("pick_index") is not None
    deadline_ok = hydrated.get("deadline") is not None
    token_ok = bool(str(hydrated.get("expected_token") or "").strip())
    if not (pick_ok and deadline_ok and token_ok):
        return "invalid", "INVALID", "INVALID_RV_REAL_ROOM_HYDRATION_incomplete_room_fields"
    if "declaration_attempt" not in events:
        if "rv_mount_failed" in events:
            row = next(r for r in rows if r.get("event") == "rv_mount_failed")
            extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
            reason = str(extra.get("reason") or row.get("reason") or "declaration_missing")
            return "invalid", "INVALID", f"INVALID_RV_COMPONENT_NOT_DECLARED_{reason}"
        return "invalid", "INVALID", "INVALID_RV_COMPONENT_NOT_DECLARED_missing_declaration_attempt"
    if "declaration_returned" not in events:
        return "invalid", "INVALID", "INVALID_RV_COMPONENT_NOT_DECLARED_missing_declaration_returned"
    setup_invalid = rv1_logical_setup_invalid_reason(rows)
    if setup_invalid:
        return "invalid", "INVALID", setup_invalid
    step_name = str(next((r.get("control_name") for r in rows if r.get("control_name")), ""))
    if step_name == "RV3":
        rv3_inv = rv3_ledger_invalid_reason(rows)
        if rv3_inv:
            return "invalid", "INVALID", rv3_inv
    if step_name == "RV3":
        placement_invalid = rv3_production_placement_invalid_reason(rows)
        if placement_invalid:
            return "invalid", "INVALID", placement_invalid
    return "READY_HYDRATED", "", ""


def should_begin_instrumentation_epoch(
    *,
    page_state: str,
    rows: list[dict[str, Any]],
    harness_room_id: str = "",
) -> tuple[bool, str, str]:
    """True only when declaration_attempt and declaration_returned are present."""
    if page_state != "READY":
        return False, "INVALID", page_state_to_invalid_reason(page_state)
    phase, verdict, reason = classify_rv1_ledger_after_ready(rows, harness_room_id=harness_room_id)
    if phase != "READY_HYDRATED":
        return False, verdict, reason
    return True, "", ""


def verify_rv_control_url(url: str, *, step: str, run_id: str, harness_room_id: str = "") -> dict[str, Any]:
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    required = {
        "active_page": "Live Draft Room",
        "solo_rv_ladder": step,
        "solo_rv_run_id": run_id,
        "solo_delivery_diag": "1",
        "solo_component_diag": "1",
        "solo_diag_timer": "10",
    }
    missing: list[str] = []
    mismatched: dict[str, str] = {}
    for key, want in required.items():
        got = (q.get(key) or [""])[0]
        if not got:
            missing.append(key)
        elif got != want:
            mismatched[key] = got
    hid = str(harness_room_id or "").strip().upper()
    if hid and step == "RV1":
        got_h = (q.get("solo_rv_harness_room_id") or [""])[0].strip().upper()
        if got_h != hid:
            if not got_h:
                missing.append("solo_rv_harness_room_id")
            else:
                mismatched["solo_rv_harness_room_id"] = got_h
    has_suite = "suite_sid" in q and bool((q.get("suite_sid") or [""])[0])
    return {
        "ok": not missing and not mismatched and has_suite,
        "missing": missing,
        "mismatched": mismatched,
        "has_suite_sid": has_suite,
        "query": {k: (v[0] if v else "") for k, v in q.items()},
    }


def verify_rv1_control_url(url: str, *, run_id: str, harness_room_id: str = "") -> dict[str, Any]:
    return verify_rv_control_url(url, step="RV1", run_id=run_id, harness_room_id=harness_room_id)


def filter_timeline_after_epoch(timeline: list[dict[str, Any]], epoch_ms: float) -> list[dict[str, Any]]:
    return [t for t in timeline if float(t.get("ts") or 0) >= epoch_ms]


def _row_extra(row: dict[str, Any]) -> dict[str, Any]:
    extra = row.get("extra")
    return extra if isinstance(extra, dict) else {}


def build_rv1_room_reuse_report(rows: list[dict[str, Any]], *, run_id: str) -> dict[str, Any]:
    """Runner-only logical setup + reuse timeline for RV1."""
    track_events = frozenset(
        {
            "production_room_creation_attempted",
            "production_room_created",
            "production_draft_start_attempted",
            "production_draft_started",
            "production_setup_owner_established",
            "production_room_reused",
            "real_room_hydrated",
            "room_state_source",
            "declaration_attempt",
            "declaration_returned",
        }
    )
    timeline: list[dict[str, Any]] = []
    for r in rows:
        ev = str(r.get("event") or "")
        if ev not in track_events:
            continue
        extra = _row_extra(r)
        timeline.append(
            {
                "event": ev,
                "event_sequence": r.get("event_sequence"),
                "script_run_seq": r.get("script_run_seq"),
                "streamlit_session_id": str(r.get("streamlit_session_id") or ""),
                "room_id": str(r.get("room_id") or extra.get("room_id") or "").strip().upper(),
                "pick_index": r.get("pick_index"),
                "deadline": r.get("deadline"),
                "expected_token": str(r.get("expected_token") or "")[:400],
                "widget_key": str(r.get("widget_key") or ""),
                "creation_event_id": _extra_field(r, "creation_event_id"),
                "draft_start_event_id": _extra_field(r, "draft_start_event_id"),
                "room_fingerprint": _extra_field(r, "room_fingerprint"),
            }
        )
    logical = analyze_rv1_logical_setup(rows)
    return {
        "solo_rv_run_id": run_id,
        **logical,
        "timeline": timeline,
    }


def _extra_field(row: dict[str, Any], key: str) -> str:
    return str(row.get(key) or _row_extra(row).get(key) or "")


def analyze_rv1_logical_setup(rows: list[dict[str, Any]]) -> dict[str, Any]:
    created = [r for r in rows if r.get("event") == "production_room_created"]
    started = [r for r in rows if r.get("event") == "production_draft_started"]
    reused = [r for r in rows if r.get("event") == "production_room_reused"]
    owners = [r for r in rows if r.get("event") == "production_setup_owner_established"]
    creation_ids = {_extra_field(r, "creation_event_id") for r in created if _extra_field(r, "creation_event_id")}
    start_ids = {_extra_field(r, "draft_start_event_id") for r in started if _extra_field(r, "draft_start_event_id")}
    room_ids = {
        str(r.get("room_id") or _extra_field(r, "room_id") or "").strip().upper()
        for r in created + reused + owners
        if str(r.get("room_id") or _extra_field(r, "room_id") or "").strip()
    }
    fingerprints = {_extra_field(r, "room_fingerprint") for r in created + owners if _extra_field(r, "room_fingerprint")}
    tokens = {
        str(r.get("expected_token") or "").strip()
        for r in rows
        if r.get("event")
        in (
            "real_room_hydrated",
            "declaration_attempt",
            "declaration_returned",
            "production_draft_started",
            "production_setup_owner_established",
        )
        and str(r.get("expected_token") or "").strip()
    }
    script_runs = {int(r.get("script_run_seq") or 0) for r in rows if r.get("script_run_seq") is not None}
    return {
        "logical_room_creation_count": len(creation_ids) if creation_ids else len(created),
        "logical_draft_start_count": len(start_ids) if start_ids else len(started),
        "production_room_reused_count": len(reused),
        "production_setup_owner_established_count": len(owners),
        "raw_production_room_created_rows": len(created),
        "raw_production_draft_started_rows": len(started),
        "distinct_creation_event_ids": sorted(creation_ids),
        "distinct_draft_start_event_ids": sorted(start_ids),
        "distinct_production_room_ids": sorted(room_ids),
        "distinct_room_fingerprints": sorted(fingerprints),
        "distinct_expected_tokens": sorted(tokens),
        "max_script_run_seq": max(script_runs) if script_runs else 0,
        "room_reuse_observed": len(reused) > 0,
    }


def rv1_logical_setup_invalid_reason(rows: list[dict[str, Any]]) -> str:
    """Invalid setup reasons based on logical events, not raw row name counts alone."""
    info = analyze_rv1_logical_setup(rows)
    room_ids = list(info.get("distinct_production_room_ids") or [])
    if len(room_ids) > 1:
        return "INVALID_RV_DUPLICATE_ROOM_CREATION_room_id_mismatch"
    creation_ids = list(info.get("distinct_creation_event_ids") or [])
    if len(creation_ids) > 1:
        return "INVALID_RV_DUPLICATE_ROOM_CREATION_multiple_creation_event_ids"
    fingerprints = list(info.get("distinct_room_fingerprints") or [])
    if len(fingerprints) > 1:
        return "INVALID_RV_DUPLICATE_ROOM_CREATION_fingerprint_mismatch"
    tokens = list(info.get("distinct_expected_tokens") or [])
    if len(tokens) > 1:
        return "INVALID_RV_DUPLICATE_ROOM_CREATION_token_mismatch"
    start_ids = list(info.get("distinct_draft_start_event_ids") or [])
    if len(start_ids) > 1:
        return "INVALID_RV_DUPLICATE_DRAFT_START_multiple_start_event_ids"
    logical_starts = int(info.get("logical_draft_start_count") or 0)
    raw_created = int(info.get("raw_production_room_created_rows") or 0)
    raw_started = int(info.get("raw_production_draft_started_rows") or 0)
    if len(room_ids) == 1 and not creation_ids and raw_created > 1:
        return "INVALID_RV_ROOM_REUSE_PROVENANCE_UNCLEAR"
    if len(room_ids) == 1 and not start_ids and raw_started > 1:
        return "INVALID_RV_ROOM_REUSE_PROVENANCE_UNCLEAR"
    if logical_starts > 1:
        return "INVALID_RV_DUPLICATE_DRAFT_START"
    logical_creates = int(info.get("logical_room_creation_count") or 0)
    if logical_creates > 1:
        return "INVALID_RV_DUPLICATE_ROOM_CREATION"
    if logical_creates == 0:
        return "INVALID_RV_PRODUCTION_ROOM_CREATION_missing_logical_create"
    if logical_starts == 0:
        return "INVALID_RV_PRODUCTION_DRAFT_START_missing_logical_start"
    max_run = int(info.get("max_script_run_seq") or 0)
    reused_count = int(info.get("production_room_reused_count") or 0)
    if max_run > 1 and reused_count < 1:
        return "INVALID_RV_ROOM_REUSE_missing_production_room_reused"
    if int(info.get("production_setup_owner_established_count") or 0) != 1:
        return "INVALID_RV_ROOM_REUSE_missing_setup_owner"
    return ""


def rv1_duplicate_room_invalid_reason(report: dict[str, Any]) -> str:
    """Backward-compatible wrapper — prefer rv1_logical_setup_invalid_reason on raw rows."""
    rows = report.get("_ledger_rows") or []
    if rows:
        return rv1_logical_setup_invalid_reason(rows)
    return rv1_logical_setup_invalid_reason_from_report(report)


def rv1_logical_setup_invalid_reason_from_report(report: dict[str, Any]) -> str:
    room_ids = list(report.get("distinct_production_room_ids") or [])
    if len(room_ids) > 1:
        return "INVALID_RV_DUPLICATE_ROOM_CREATION_room_id_mismatch"
    creation_ids = list(report.get("distinct_creation_event_ids") or [])
    if len(creation_ids) > 1:
        return "INVALID_RV_DUPLICATE_ROOM_CREATION_multiple_creation_event_ids"
    if int(report.get("logical_draft_start_count") or 0) > 1:
        return "INVALID_RV_DUPLICATE_DRAFT_START"
    return ""


RV3_PRODUCTION_LOCATION_MARKERS = (
    "ldr_page_entry",
    "early_persistent",
    "persistent_wake",
)


def _row_extra_dict(row: dict[str, Any]) -> dict[str, Any]:
    extra = row.get("extra")
    return extra if isinstance(extra, dict) else {}


def _rv3_hydrated_index(rows: list[dict[str, Any]]) -> int | None:
    for i, row in enumerate(rows):
        if str(row.get("event") or "") == "real_room_hydrated":
            return i
    return None


def _rv3_declaration_tokens(rows: list[dict[str, Any]]) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    for i, row in enumerate(rows):
        if str(row.get("event") or "") != "declaration_attempt":
            continue
        tok = str(row.get("expected_token") or "")
        loc = str(_row_extra_dict(row).get("location") or row.get("location") or "")
        out.append((i, tok, loc))
    return out


def build_rv3_production_placement_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Runner-only: where RV3 production persistent-wake declared on the full LDR page."""
    from live_draft_solo_rv3_phase import is_rv3_rejected_token

    hydrated_idx = _rv3_hydrated_index(rows)
    prod_attempts = []
    for i, row in enumerate(rows):
        if str(row.get("event") or "") != "declaration_attempt":
            continue
        if hydrated_idx is not None and i < hydrated_idx:
            continue
        tok = str(row.get("expected_token") or "")
        if is_rv3_rejected_token(tok):
            continue
        loc = str(_row_extra_dict(row).get("location") or row.get("location") or "")
        if not any(m in loc for m in RV3_PRODUCTION_LOCATION_MARKERS):
            continue
        prod_attempts.append(
            {
                "event_sequence": row.get("event_sequence"),
                "script_run_seq": row.get("script_run_seq"),
                "location": loc,
                "widget_key": row.get("widget_key"),
                "expected_token": row.get("expected_token"),
            }
        )
    first = prod_attempts[0] if prod_attempts else {}
    return {
        "source_module": "live_draft_solo_persistent_wake",
        "source_function": "try_solo_persistent_wake_ldr_entry",
        "mount_function": "_mount_persistent_wake_micro_controlled",
        "streamlit_call_site": "streamlit_app.py:early_persistent_wake_ldr_entry",
        "active_page": "Live Draft Room",
        "branch": "early_persistent_wake_before_full_ldr_body",
        "persistent_wake_eligible": True,
        "on_change": None,
        "return_value_delivery": True,
        "pick_processing_disabled": True,
        "widget_key": str(first.get("widget_key") or "solo_countdown_wake_solo_persistent"),
        "declaration_occurrence_order": len(prod_attempts),
        "production_declaration_attempts": prod_attempts,
        "first_production_location": str(first.get("location") or ""),
    }


def rv3_room_continuity_invalid_reason(rows: list[dict[str, Any]]) -> str:
    """Room continuity lane (not binding A–D)."""
    events = [str(r.get("event") or "") for r in rows]
    if "rv_mount_failed" not in events:
        return ""
    fail_idx = max(i for i, ev in enumerate(events) if ev == "rv_mount_failed")
    tail = rows[fail_idx + 1 :]
    hydrated_after = any(str(r.get("event") or "") == "real_room_hydrated" for r in tail)
    decl_after = any(str(r.get("event") or "") == "declaration_attempt" for r in tail)
    if decl_after and not hydrated_after:
        return "INVALID_RV3_POST_DELIVERY_ROOM_STATE_LOST"
    fail_row = rows[fail_idx]
    extra = _row_extra_dict(fail_row)
    inv = str(extra.get("invalid") or "")
    if inv == "INVALID_RV3_POST_DELIVERY_ROOM_STATE_LOST":
        return inv
    reason = str(extra.get("reason") or fail_row.get("reason") or "")
    if "rv3_post_setup_without_live_room" in reason and not hydrated_after:
        return "INVALID_RV3_POST_DELIVERY_ROOM_STATE_LOST"
    return ""


def rv3_production_placement_invalid_reason(rows: list[dict[str, Any]]) -> str:
    inv = rv3_ledger_invalid_reason(rows)
    if inv:
        return inv
    room_inv = rv3_room_continuity_invalid_reason(rows)
    if room_inv:
        return room_inv
    events = {str(r.get("event") or "") for r in rows}
    if "rv_mount_failed" in events:
        row = next(r for r in rows if r.get("event") == "rv_mount_failed")
        inv = str(_row_extra_dict(row).get("invalid") or "")
        if inv.startswith("INVALID_RV3"):
            return inv
        room_inv = rv3_room_continuity_invalid_reason(rows)
        if room_inv:
            return room_inv
        reason = str(_row_extra_dict(row).get("reason") or row.get("reason") or "mount_failed")
        return f"INVALID_RV3_PRODUCTION_DECLARATION_NOT_REACHED"
    report = build_rv3_production_placement_report(rows)
    if not report.get("production_declaration_attempts"):
        if "declaration_attempt" not in events:
            return "INVALID_RV3_PRODUCTION_DECLARATION_NOT_REACHED"
        return "INVALID_RV3_PRODUCTION_PLACEMENT_ORDER"
    if "declaration_returned" not in events:
        return "INVALID_RV3_PRODUCTION_DECLARATION_NOT_REACHED"
    return ""


def rv3_ledger_invalid_reason(rows: list[dict[str, Any]]) -> str:
    """RV3 setup/placement invalid reasons (not binding A–D)."""
    from live_draft_solo_rv3_phase import is_rv3_rejected_token

    events = {str(r.get("event") or "") for r in rows}
    if "rv3_premature_component_declaration" in events:
        return "INVALID_RV3_PREMATURE_COMPONENT_DECLARATION"
    hydrated_idx = _rv3_hydrated_index(rows)
    for i, tok, loc in _rv3_declaration_tokens(rows):
        if is_rv3_rejected_token(tok):
            if hydrated_idx is None or i < hydrated_idx:
                return "INVALID_RV3_PREMATURE_COMPONENT_DECLARATION"
            return "INVALID_RV3_PRODUCTION_PLACEMENT_ORDER"
        if hydrated_idx is not None and i < hydrated_idx:
            return "INVALID_RV3_PRODUCTION_PLACEMENT_ORDER"
    for req in (
        "production_room_creation_attempted",
        "production_room_created",
        "production_draft_start_attempted",
        "production_draft_started",
        "production_setup_owner_established",
        "rv3_setup_complete",
        "rv3_setup_rerun_requested",
    ):
        if req not in events:
            return "INVALID_RV3_SETUP_NOT_COMPLETED"
    if "production_room_reused" not in events:
        return "INVALID_RV3_SETUP_NOT_COMPLETED"
    if "real_room_hydrated" not in events or "room_state_source" not in events:
        return "INVALID_RV3_REAL_ROOM_NOT_HYDRATED"
    if "rv3_production_placement_entered" not in events:
        return "INVALID_RV3_PRODUCTION_DECLARATION_NOT_REACHED"
    if "declaration_attempt" not in events or "declaration_returned" not in events:
        return "INVALID_RV3_PRODUCTION_DECLARATION_NOT_REACHED"
    setup_invalid = rv1_logical_setup_invalid_reason(rows)
    if setup_invalid:
        return setup_invalid
    prod_decls = [
        (i, tok)
        for i, tok, _loc in _rv3_declaration_tokens(rows)
        if hydrated_idx is not None and i >= hydrated_idx and not is_rv3_rejected_token(tok)
    ]
    if not prod_decls:
        return "INVALID_RV3_PRODUCTION_PLACEMENT_ORDER"
    owner_tokens = {
        str(r.get("expected_token") or "").strip()
        for r in rows
        if r.get("event") == "production_setup_owner_established"
        and str(r.get("expected_token") or "").strip()
    }
    if owner_tokens:
        want = next(iter(owner_tokens))
        if prod_decls[0][1] != want:
            return "INVALID_RV3_PRODUCTION_PLACEMENT_ORDER"
    return ""


def rv3_post_delivery_observation_boundary(
    rows: list[dict[str, Any]], *, browser_send_ts: float | None = None
) -> dict[str, Any]:
    """Runner diagnosis: first missing step after production placement / browser send."""
    from live_draft_solo_rv_declaration_ledger import _row_ts_seconds

    placement = next((r for r in rows if str(r.get("event") or "") == "rv3_production_placement_entered"), None)
    out: dict[str, Any] = {
        "classification": "",
        "placement_entered_ts": _row_ts_seconds(placement) if placement else None,
        "browser_send_ts": browser_send_ts,
        "last_event": "",
        "last_event_sequence": 0,
        "max_script_run_seq": 0,
        "has_mount_with_rv_decl_trace": False,
        "has_declaration_attempt": False,
        "has_declaration_returned": False,
        "has_post_delivery_redeclaration": False,
        "post_send_declaration_returned": False,
    }
    if not rows:
        out["classification"] = "E"
        return out
    out["last_event"] = str(rows[-1].get("event") or "")
    out["last_event_sequence"] = int(rows[-1].get("event_sequence") or 0)
    out["max_script_run_seq"] = max(int(r.get("script_run_seq") or 0) for r in rows)
    events = {str(r.get("event") or "") for r in rows}
    out["has_mount_with_rv_decl_trace"] = any(
        str((r.get("extra") or {}).get("step") or r.get("step") or "") == "mount_with_rv_control_declaration"
        for r in rows
        if str(r.get("event") or "") == "rv3_decl_trace"
    )
    out["has_declaration_attempt"] = "declaration_attempt" in events
    out["has_declaration_returned"] = "declaration_returned" in events
    out["has_post_delivery_redeclaration"] = "post_delivery_redeclaration" in events
    send_ts = browser_send_ts
    for row in rows:
        if str(row.get("event") or "") != "declaration_returned":
            continue
        if send_ts is None or _row_ts_seconds(row) >= send_ts - 0.05:
            out["post_send_declaration_returned"] = True
            break
    if not placement:
        out["classification"] = "A"
        return out
    if not out["has_mount_with_rv_decl_trace"] and not out["has_declaration_attempt"]:
        out["classification"] = "A"
        return out
    if out["has_mount_with_rv_decl_trace"] and not out["has_declaration_attempt"]:
        out["classification"] = "B"
        return out
    if out["has_declaration_attempt"] and not out["has_declaration_returned"]:
        out["classification"] = "C"
        return out
    if send_ts and out["has_declaration_returned"] and not out["post_send_declaration_returned"]:
        if not out["has_post_delivery_redeclaration"]:
            out["classification"] = "D"
            return out
    if out["post_send_declaration_returned"] or out["has_post_delivery_redeclaration"]:
        out["classification"] = ""
        return out
    out["classification"] = "E"
    return out

