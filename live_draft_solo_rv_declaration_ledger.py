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


def _row_ts_seconds(row: dict[str, Any]) -> float:
    ts = row.get("ts")
    if ts is None:
        return 0.0
    try:
        val = float(ts)
    except (TypeError, ValueError):
        return 0.0
    if val > 1e12:
        return val / 1000.0
    return val


def infer_browser_send_ts_seconds(
    ledger_rows: list[dict[str, Any]] | None = None,
    *,
    expiration: dict[str, Any] | None = None,
) -> float | None:
    """Best-effort browser expiration send time (seconds) from runner observations."""
    exp = expiration or {}
    transport = dict(exp.get("transport_send_evidence") or {})
    matched = list(transport.get("matched") or [])
    if matched:
        try:
            ts_ms = float(matched[0].get("ts") or 0)
            if ts_ms > 0:
                return ts_ms / 1000.0 if ts_ms > 1e12 else ts_ms
        except (TypeError, ValueError):
            pass
    deduped = list(exp.get("deduped_logical_sends") or [])
    if deduped:
        try:
            ts_ms = float(deduped[0].get("ts") or 0)
            if ts_ms > 0:
                return ts_ms / 1000.0 if ts_ms > 1e12 else ts_ms
        except (TypeError, ValueError):
            pass
    for row in ledger_rows or []:
        if str(row.get("event") or "") == "post_delivery_redeclaration":
            t = _row_ts_seconds(row)
            if t:
                return t
    return None


def ledger_post_delivery_proof_satisfied(
    rows: list[dict[str, Any]],
    *,
    expected_token: str = "",
    browser_send_ts: float | None = None,
) -> tuple[bool, str]:
    """Runner grading: post-send declaration proof (explicit row or declaration_returned after browser send)."""
    exp = str(expected_token or "").strip()
    send_ts = browser_send_ts
    if send_ts is None:
        send_ts = infer_browser_send_ts_seconds(rows)

    for row in reversed(rows):
        ev = str(row.get("event") or "")
        if ev == "post_delivery_redeclaration":
            tok = str(row.get("expected_token") or "")
            extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
            proof = str(extra.get("proof_source") or row.get("proof_source") or "")
            if exp and tok and tok != exp and exp not in tok:
                continue
            if send_ts is not None and _row_ts_seconds(row) < send_ts - 0.05:
                continue
            if proof or not exp or tok == exp or exp in str(row.get("coalesced_value") or ""):
                return True, proof or "explicit_ledger_row"
        if ev != "declaration_returned":
            continue
        row_ts = _row_ts_seconds(row)
        if send_ts is not None and row_ts > 0 and row_ts < send_ts - 0.05:
            continue
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        if extra.get("post_delivery_redeclaration_proven"):
            return True, str(extra.get("proof_source") or "component_return_exact")
        occ = int(extra.get("declaration_occurrence_number") or row.get("declaration_occurrence_number") or 0)
        browser_seen = bool(
            row.get("browser_send_seen")
            or extra.get("browser_send_seen")
            or extra.get("post_delivery_redeclaration_proven")
        )
        micro_cr = str(extra.get("micro_cycle_component_return") or "").strip()
        if not micro_cr:
            from live_draft_solo_rv3_room_continuity import extract_micro_cycle_binding_token

            micro_cr = extract_micro_cycle_binding_token(row.get("component_return")) or extract_micro_cycle_binding_token(
                extra.get("component_return_repr")
            )
        coalesced = str(extra.get("coalesced_value_exact") or row.get("coalesced_value") or "").strip().strip("'\"")
        ss_tok = _session_state_token(str(extra.get("session_state_after") or row.get("session_state_after") or ""))
        if exp and micro_cr == exp:
            if send_ts is None or row_ts >= send_ts - 0.05:
                return True, "component_return_exact"
            if occ >= 2 and browser_seen:
                return True, "component_return_exact"
        if exp and send_ts is not None and row_ts >= send_ts - 0.05:
            if coalesced == exp or ss_tok == exp:
                return True, "coalesced_value_exact" if coalesced == exp else "session_state_exact"
        if exp:
            if micro_cr == exp and extra.get("proof_source") == "component_return_exact":
                if send_ts is None or row_ts >= send_ts - 0.05:
                    return True, "component_return_exact"
    return False, ""


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
