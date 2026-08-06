"""Ledger scoping and pre-click auth payload export (harness only)."""

from __future__ import annotations

from typing import Any

PRECLICK_AUTH_EVENTS = frozenset(
    {
        "production_stage1_auth_state_before_start_control",
        "production_stage1_auth_prestart_hydration",
        "production_stage1_auth_prestart_mutation",
    }
)


def max_ledger_event_index(rows: list[dict[str, Any]]) -> int:
    try:
        from queueui_audit_protocol import ledger_event_index
    except ImportError:
        return -1
    indices = [ledger_event_index(r) for r in rows if isinstance(r, dict)]
    valid = [i for i in indices if i >= 0]
    return max(valid) if valid else -1


def ledger_max_script_run_seq(rows: list[dict[str, Any]]) -> int:
    seqs = [int(r.get("script_run_seq") or 0) for r in rows if isinstance(r, dict)]
    return max(seqs) if seqs else 0


def filter_ledger_rows(
    rows: list[dict[str, Any]],
    *,
    diagnostic_run_id: str = "",
    streamlit_session_id: str = "",
    max_seq_cap: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Keep rows for the active run/session; prefer latest script_run_seq slice."""
    meta: dict[str, Any] = {
        "input_row_count": len(rows),
        "filtered_row_count": 0,
        "excluded_other_session": 0,
        "excluded_other_run": 0,
        "excluded_future_seq": 0,
        "max_index_in_scope": -1,
        "max_script_run_seq_in_scope": 0,
        "diagnostic_run_id": diagnostic_run_id[:16] if diagnostic_run_id else "",
        "streamlit_session_id": streamlit_session_id[:36] if streamlit_session_id else "",
    }
    rid = str(diagnostic_run_id or "").strip()
    sid = str(streamlit_session_id or "").strip()
    scoped: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        row_sid = str(r.get("streamlit_session_id") or "").strip()
        row_rid = str(r.get("run_id") or r.get("diagnostic_run_id") or "").strip()
        if sid and row_sid and row_sid != sid:
            meta["excluded_other_session"] += 1
            continue
        if rid and row_rid and row_rid != rid:
            meta["excluded_other_run"] += 1
            continue
        scoped.append(r)
    if max_seq_cap is not None and max_seq_cap > 0:
        scoped = [
            r
            for r in scoped
            if int(r.get("script_run_seq") or 0) <= max_seq_cap
            or str(r.get("event") or "") == "production_global_script_run_canary"
        ]
        meta["excluded_future_seq"] = meta["input_row_count"] - len(scoped) - meta["excluded_other_session"] - meta["excluded_other_run"]
    meta["filtered_row_count"] = len(scoped)
    meta["max_index_in_scope"] = max_ledger_event_index(scoped)
    meta["max_script_run_seq_in_scope"] = ledger_max_script_run_seq(scoped)
    return scoped, meta


def export_pre_click_auth_payloads(
    rows: list[dict[str, Any]],
    *,
    diagnostic_run_id: str = "",
    streamlit_session_id: str = "",
) -> dict[str, Any]:
    """Full event payloads for pre-click auth diagnostics (no secrets stripped — ledger has booleans only)."""
    scoped, scope_meta = filter_ledger_rows(
        rows,
        diagnostic_run_id=diagnostic_run_id,
        streamlit_session_id=streamlit_session_id,
    )
    by_event: dict[str, list[dict[str, Any]]] = {ev: [] for ev in PRECLICK_AUTH_EVENTS}
    for r in scoped:
        ev = str(r.get("event") or "")
        if ev in PRECLICK_AUTH_EVENTS:
            by_event[ev].append(dict(r))
    for ev in by_event:
        by_event[ev].sort(
            key=lambda x: (
                int(x.get("script_run_seq") or 0),
                str(x.get("event_id") or ""),
            )
        )
    return {
        "scope": scope_meta,
        "payloads_by_event": by_event,
        "payload_row_counts": {k: len(v) for k, v in by_event.items()},
    }
