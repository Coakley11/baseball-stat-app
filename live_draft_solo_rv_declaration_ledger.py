"""Run-scoped RV declaration occurrence counter and post-delivery proof (diag-only)."""

from __future__ import annotations

import time
from typing import Any

RV_DECLARATION_OCC_BY_RUN_KEY = "_solo_rv_declaration_occurrence_by_run"
PRODUCTION_PERSISTENT_WIDGET_KEY = "solo_countdown_wake_solo_persistent"

RV3_PRODUCTION_LOCATION_MARKERS = (
    "ldr_page_entry_early_persistent",
    "early_persistent_wake",
    "try_solo_persistent_wake_ldr_entry",
)


def _occ_store(session: dict[str, Any]) -> dict[str, int]:
    store = session.get(RV_DECLARATION_OCC_BY_RUN_KEY)
    if not isinstance(store, dict):
        store = {}
        session[RV_DECLARATION_OCC_BY_RUN_KEY] = store
    return store


def increment_declaration_occurrence(session: dict[str, Any], run_id: str) -> int:
    """Persisted per solo_rv_run_id; not reset by workspace or room restore."""
    rid = str(run_id or "").strip()
    if not rid:
        return 0
    store = _occ_store(session)
    n = int(store.get(rid) or 0) + 1
    store[rid] = n
    return n


def current_declaration_occurrence(session: dict[str, Any], run_id: str) -> int:
    rid = str(run_id or "").strip()
    if not rid:
        return 0
    return int(_occ_store(session).get(rid) or 0)


def is_production_persistent_placement(*, widget_key: str, location: str) -> bool:
    wk = str(widget_key or "").strip()
    loc = str(location or "").lower()
    if wk != PRODUCTION_PERSISTENT_WIDGET_KEY:
        return False
    return any(m in loc for m in RV3_PRODUCTION_LOCATION_MARKERS) or "persistent" in loc


def micro_cycle_to_ledger_fields(raw: Any) -> dict[str, Any]:
    """Structured MicroCycleResult fields for ledger rows (no production behavior change)."""
    try:
        from solo_countdown_wake_micro_core import MicroCycleResult

        if isinstance(raw, MicroCycleResult):
            cr = raw.component_return
            cr_str = "" if cr is None else str(cr).strip().strip("'\"")
            coalesced = cr_str if cr_str and cr_str != "None" else ""
            return {
                "micro_cycle_component_return": cr_str,
                "coalesced_value_exact": coalesced,
                "raw_received": bool(raw.raw_received),
                "delivered": bool(raw.delivered),
                "on_change_fired": bool(raw.on_change_fired),
                "component_return_repr": repr(raw)[:400],
            }
    except ImportError:
        pass
    from live_draft_solo_rv3_room_continuity import extract_micro_cycle_binding_token

    text = repr(raw)[:400] if raw is not None else ""
    tok = extract_micro_cycle_binding_token(raw)
    return {
        "micro_cycle_component_return": tok,
        "coalesced_value_exact": tok,
        "raw_received": "raw_received=True" in text,
        "delivered": "delivered=True" in text,
        "on_change_fired": "on_change_fired=True" in text,
        "component_return_repr": text,
    }


def _session_state_token(ss_after: str) -> str:
    s = str(ss_after or "").strip()
    if not s or s in ("missing", "None"):
        return ""
    return s.strip("'\"")


def evaluate_post_delivery_proof(
    *,
    expected_token: str,
    widget_key: str,
    location: str,
    occurrence: int,
    micro: dict[str, Any],
    ss_after: str,
    coalesced: str,
    browser_send_observed: bool,
) -> tuple[bool, str]:
    """Return (proven, proof_source)."""
    exp = str(expected_token or "").strip()
    if not exp or not is_production_persistent_placement(widget_key=widget_key, location=location):
        return False, ""
    cr = str(micro.get("micro_cycle_component_return") or "").strip()
    co = str(coalesced or micro.get("coalesced_value_exact") or "").strip()
    ss_tok = _session_state_token(ss_after)
    raw_rx = bool(micro.get("raw_received"))
    after_browser = bool(browser_send_observed or raw_rx or occurrence >= 2)

    if cr == exp and after_browser:
        return True, "component_return_exact"
    if occurrence < 2:
        return False, ""
    if not browser_send_observed and not raw_rx:
        return False, ""
    if cr == exp:
        return True, "component_return_exact"
    if not cr or cr == "None":
        if co == exp:
            return True, "coalesced_value_exact"
        if ss_tok == exp:
            return True, "session_state_exact"
    return False, ""


def ledger_post_delivery_proof_satisfied(
    rows: list[dict[str, Any]],
    *,
    expected_token: str = "",
) -> tuple[bool, str]:
    """Runner grading: explicit row or declaration_returned with proof metadata."""
    exp = str(expected_token or "").strip()
    for row in reversed(rows):
        ev = str(row.get("event") or "")
        if ev == "post_delivery_redeclaration":
            tok = str(row.get("expected_token") or "")
            extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
            proof = str(extra.get("proof_source") or row.get("proof_source") or "")
            if exp and tok and tok != exp and exp not in tok:
                continue
            if proof or not exp or tok == exp or exp in str(row.get("coalesced_value") or ""):
                return True, proof or "explicit_ledger_row"
        if ev != "declaration_returned":
            continue
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        if extra.get("post_delivery_redeclaration_proven"):
            return True, str(extra.get("proof_source") or "component_return_exact")
        if exp:
            micro_cr = str(extra.get("micro_cycle_component_return") or "")
            if micro_cr == exp and extra.get("proof_source") == "component_return_exact":
                return True, "component_return_exact"
    return False, ""


def note_browser_send_observed(session: dict[str, Any]) -> None:
    session["_solo_rv_browser_send_observed"] = True


def browser_send_observed_for_declaration(
    session: dict[str, Any],
    *,
    widget_key: str,
    expected_token: str,
    ss_before: str,
) -> bool:
    if session.get("_solo_rv_browser_send_observed"):
        return True
    if session.get("_solo_rv_browser_delivery_recorded"):
        return True
    tok = _session_state_token(ss_before)
    exp = str(expected_token or "").strip()
    return bool(exp and tok == exp)
