"""Filter and export Stage-1 room-latch ledger rows (harness)."""

from __future__ import annotations

from typing import Any

LATCH_EVENT_NAMES = frozenset(
    {
        "production_stage1_room_state_write",
        "production_stage1_room_state_clear",
        "production_stage1_room_state_restore",
        "production_stage1_room_state_read",
        "production_stage1_handler_exit_session_state_proof",
        "production_stage1_rerun_transition",
        "production_stage1_surface_decision",
        "production_stage1_start_handler_entered",
        "production_stage1_start_handler_exited",
        "production_stage1_room_creation_entered",
        "production_stage1_room_creation_exited",
        "production_global_script_run_canary",
        "production_live_draft_branch_canary",
        "production_stage1_script_begin",
        "production_countdown_declaration_pre",
        "production_countdown_declaration_post",
        "production_stage1_queueui_predicate_audit",
    }
)


def _rid(row: dict[str, Any]) -> str:
    for k in ("created_room_id", "room_id", "session_room_id", "restored_room_id", "new_room_id"):
        v = str(row.get(k) or "").strip().upper()
        if v:
            return v
    snap = row.get("post_restore_snapshot") or row.get("post_write_snapshot") or row.get("authoritative_session_state")
    if isinstance(snap, dict):
        return str(snap.get("session_room_id") or snap.get("canonical_blob_room_id") or "").upper()
    return ""


def filter_latch_ledger_rows(
    rows: list[dict[str, Any]],
    *,
    diagnostic_run_id: str = "",
    streamlit_session_id: str = "",
    created_room_id: str = "",
    click_ts: float = 0.0,
    script_run_seq_min: int | None = None,
    script_run_seq_max: int | None = None,
) -> list[dict[str, Any]]:
    """Strict filter: run id, session, room relevance, and latch-related events."""
    run_id = str(diagnostic_run_id or "").strip()
    sid = str(streamlit_session_id or "").strip()
    created = str(created_room_id or "").strip().upper()
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        ev = str(r.get("event") or "")
        if (
            ev not in LATCH_EVENT_NAMES
            and not ev.startswith("production_stage1_")
            and not ev.startswith("production_countdown_declaration")
        ):
            continue
        if click_ts and float(r.get("ts") or 0) < click_ts - 0.25:
            continue
        if run_id:
            row_run = str(r.get("run_id") or r.get("diagnostic_run_id") or "")
            if row_run and row_run != run_id and created not in _rid(r):
                continue
        seq = int(r.get("script_run_seq") or 0)
        if script_run_seq_min is not None and seq and seq < script_run_seq_min:
            continue
        if script_run_seq_max is not None and seq and seq > script_run_seq_max:
            continue
        row_sid = str(r.get("streamlit_session_id") or "")
        if sid and row_sid and row_sid != sid:
            if created not in _rid(r):
                continue
        if created:
            relevant = (
                _rid(r) == created
                or ev in LATCH_EVENT_NAMES
                or created in str(r.get("expected_token") or "").upper()
            )
            if not relevant and ev not in (
                "production_global_script_run_canary",
                "production_live_draft_branch_canary",
                "production_stage1_script_begin",
            ):
                continue
        out.append(dict(r))
    out.sort(key=lambda x: (float(x.get("ts") or 0), int(x.get("script_run_seq") or 0)))
    return out


def resolve_run_and_session(
    rows: list[dict[str, Any]], *, created_room_id: str = ""
) -> tuple[str, str]:
    created = str(created_room_id or "").strip().upper()
    run_id = ""
    sid = ""
    for r in rows:
        if r.get("event") == "production_stage1_start_handler_exited" and r.get("created_room_id"):
            run_id = str(r.get("run_id") or "")
            sid = str(r.get("streamlit_session_id") or sid)
            if not created:
                created = str(r.get("created_room_id") or "").upper()
            break
    if not run_id:
        for r in rows:
            if r.get("event") == "production_stage1_room_creation_exited" and r.get("created_room_id"):
                run_id = str(r.get("run_id") or "")
                sid = str(r.get("streamlit_session_id") or sid)
                break
    for r in rows:
        if str(r.get("streamlit_session_id") or ""):
            sid = str(r.get("streamlit_session_id") or sid)
            if run_id and str(r.get("run_id") or "") == run_id:
                break
    return run_id, sid
