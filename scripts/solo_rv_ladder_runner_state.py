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
) -> str:
    """Return PAGE_NOT_READY | APP_ERROR | AUTH_LOST | ROUTE_NOT_ENTERED | READY_PENDING | READY."""
    text = str(page_text or "")
    lower = text.lower()
    events = {str(r.get("event") or "") for r in rows}
    if dom.get("has_st_exception"):
        return "APP_ERROR"
    if dom.get("has_streamlit_error") and not dom.get("has_ledger_prefix"):
        if not events.intersection({"production_room_created", "declaration_attempt", "real_room_hydrated"}):
            return "APP_ERROR"
    if dom.get("has_login") or ("not signed in" in lower and "signed in as" not in lower):
        return "AUTH_LOST"
    loading = bool(dom.get("has_streamlit_app")) and (
        dom.get("app_loading") or ("running" in lower[:500] and "live draft" not in lower)
    )
    if loading and not rows and not ledger_has_prefix(text) and len(text.strip()) < 80:
        return "PAGE_NOT_READY"
    events = {str(r.get("event") or "") for r in rows}
    if ledger_ready(rows, page_text=text):
        return "READY"
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


def page_state_to_invalid_reason(state: str) -> str:
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


def verify_rv1_control_url(url: str, *, run_id: str, harness_room_id: str = "") -> dict[str, Any]:
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    required = {
        "active_page": "Live Draft Room",
        "solo_rv_ladder": "RV1",
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
    if hid:
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


def filter_timeline_after_epoch(timeline: list[dict[str, Any]], epoch_ms: float) -> list[dict[str, Any]]:
    return [t for t in timeline if float(t.get("ts") or 0) >= epoch_ms]
