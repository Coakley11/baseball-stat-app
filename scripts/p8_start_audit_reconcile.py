"""Recover start-pipeline ledger rows missed by narrow filters (harness only)."""

from __future__ import annotations

from typing import Any

START_AUDIT_EVENTS = frozenset(
    {
        "production_stage1_start_button_value",
        "production_stage1_start_handler_entered",
        "production_stage1_start_handler_exited",
        "production_stage1_room_creation_entered",
        "production_stage1_room_creation_exited",
        "production_stage1_handler_exit_session_state_proof",
        "production_stage1_room_state_write",
        "production_stage1_rerun_transition",
        "production_stage1_room_state_read",
    }
)


def _norm_room(value: Any) -> str:
    return str(value or "").strip().upper()


def _row_room(row: dict[str, Any]) -> str:
    for k in ("created_room_id", "room_id", "session_room_id", "new_room_id"):
        v = _norm_room(row.get(k))
        if v:
            return v
    auth = row.get("authoritative_session_state")
    if isinstance(auth, dict):
        return _norm_room(auth.get("session_room_id"))
    return ""


def infer_created_room_after_click(rows: list[dict[str, Any]], *, click_ts: float) -> str:
    created = ""
    after = [r for r in rows if float(r.get("ts") or 0) >= click_ts - 0.05]
    for ev in (
        "production_stage1_start_handler_exited",
        "production_stage1_room_creation_exited",
        "production_stage1_handler_exit_session_state_proof",
    ):
        for r in reversed(after):
            if str(r.get("event") or "") != ev:
                continue
            rid = _row_room(r)
            if rid:
                return rid
    for r in reversed(after):
        if str(r.get("event") or "") == "production_live_draft_branch_canary":
            rid = _row_room(r)
            if rid:
                created = rid
    return created


def collect_start_audit_rows(
    rows: list[dict[str, Any]],
    *,
    click_ts: float = 0.0,
    diagnostic_run_id: str = "",
    streamlit_session_id: str = "",
    created_room_id: str = "",
    script_run_seq_window: int = 8,
    click_script_run_seq: int | None = None,
) -> dict[str, Any]:
    """Broad ledger search for start events (by session, room, time, run-id hints)."""
    run_id = str(diagnostic_run_id or "").strip()
    sid = str(streamlit_session_id or "").strip()
    created = _norm_room(created_room_id)
    after_click = [r for r in rows if float(r.get("ts") or 0) >= click_ts - 0.05] if click_ts else list(rows)

    matched: list[dict[str, Any]] = []
    for r in after_click:
        if not isinstance(r, dict):
            continue
        ev = str(r.get("event") or "")
        if ev not in START_AUDIT_EVENTS and ev not in (
            "production_live_draft_branch_canary",
            "production_global_script_run_canary",
        ):
            continue
        row_run = str(r.get("run_id") or r.get("diagnostic_run_id") or "")
        row_sid = str(r.get("streamlit_session_id") or "")
        row_room = _row_room(r)
        seq = int(r.get("script_run_seq") or 0)

        by_run = bool(run_id and row_run and row_run == run_id)
        by_session = bool(sid and row_sid and row_sid == sid)
        by_room = bool(created and row_room == created)
        by_seq = False
        if click_script_run_seq is not None and seq:
            by_seq = click_script_run_seq <= seq <= click_script_run_seq + script_run_seq_window

        if by_run or by_session or by_room or by_seq or ev in START_AUDIT_EVENTS:
            if click_ts and float(r.get("ts") or 0) < click_ts - 0.25 and not by_room:
                continue
            matched.append(dict(r))

    matched.sort(key=lambda x: (float(x.get("ts") or 0), int(x.get("script_run_seq") or 0)))
    by_event: dict[str, list[dict[str, Any]]] = {}
    for r in matched:
        ev = str(r.get("event") or "")
        by_event.setdefault(ev, []).append(r)

    narrow_handler_in = sum(1 for r in rows if r.get("event") == "production_stage1_start_handler_entered")
    broad_handler_in = len(by_event.get("production_stage1_start_handler_entered") or [])
    narrow_handler_out = sum(1 for r in rows if r.get("event") == "production_stage1_start_handler_exited")
    broad_handler_out = len(by_event.get("production_stage1_start_handler_exited") or [])

    return {
        "rows": matched,
        "by_event": by_event,
        "audit_filter_mismatch": bool(
            (broad_handler_in > narrow_handler_in or broad_handler_out > narrow_handler_out)
            and created
        ),
        "handler_entered_count": broad_handler_in,
        "handler_exited_count": broad_handler_out,
        "room_creation_exited_count": len(by_event.get("production_stage1_room_creation_exited") or []),
        "session_proof_count": len(by_event.get("production_stage1_handler_exit_session_state_proof") or []),
        "inferred_created_room_id": created or infer_created_room_after_click(rows, click_ts=click_ts),
    }


def authoritative_room_exists_in_session(
    rows: list[dict[str, Any]], *, click_ts: float, created_room_id: str = ""
) -> bool:
    created = _norm_room(created_room_id) or infer_created_room_after_click(rows, click_ts=click_ts)
    if not created:
        return False
    recon = collect_start_audit_rows(rows, click_ts=click_ts, created_room_id=created)
    if recon.get("handler_exited_count") or recon.get("room_creation_exited_count"):
        return True
    for r in rows:
        if float(r.get("ts") or 0) < click_ts - 0.05:
            continue
        if _row_room(r) == created:
            return True
    return False
