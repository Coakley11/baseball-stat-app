"""Expand predicate audit ledger rows into per-checkpoint timeline entries."""

from __future__ import annotations

from typing import Any


def predicate_timeline_from_ledger(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    audit = [r for r in rows if str(r.get("event") or "") == "production_stage1_queueui_predicate_audit"]
    out: list[dict[str, Any]] = []
    for r in sorted(audit, key=lambda x: (int(x.get("script_run_seq") or 0), float(x.get("ts") or 0))):
        preds = r.get("predicates") if isinstance(r.get("predicates"), dict) else {}
        auth = r.get("auth") if isinstance(r.get("auth"), dict) else {}
        restore = r.get("restore") if isinstance(r.get("restore"), dict) else {}
        access = r.get("room_access") if isinstance(r.get("room_access"), dict) else {}
        out.append(
            {
                "script_run_seq": int(r.get("script_run_seq") or 0),
                "checkpoint": str(r.get("checkpoint") or r.get("widget_key") or ""),
                "streamlit_session_id": str(r.get("streamlit_session_id") or ""),
                "diagnostic_run_id": str(r.get("run_id") or ""),
                "authenticated": auth.get("authenticated"),
                "auth_enabled": auth.get("auth_enabled"),
                "email_present": auth.get("email_present"),
                "user_id_present": auth.get("user_id_present"),
                "room_id": preds.get("room_id") or r.get("room_id"),
                "room_status": preds.get("room_status") or r.get("room_status"),
                "lifecycle": preds.get("lifecycle"),
                "pick_index": preds.get("pick_index") if preds.get("pick_index") is not None else r.get("pick_index"),
                "deadline_token": r.get("deadline") or r.get("expected_token"),
                "live_draft_room_present": preds.get("live_draft_room_present"),
                "start_in_flight": preds.get("start_in_flight"),
                "restore_blocked_reason": restore.get("restore_blocked_reason"),
                "restore_allowed": restore.get("restore_allowed"),
                "restore_gate_reason": restore.get("restore_gate_reason"),
                "membership_gate_would_run": access.get("membership_gate_would_run"),
                "solo_room": access.get("solo_room"),
                "active_page_predicate": preds.get("partial_header_predicate"),
                "full_room_body_predicate": preds.get("full_body_predicate"),
                "timer_controls_predicate": preds.get("timer_ok"),
                "pause_control_predicate": preds.get("pause_control_predicate"),
                "recommendations_predicate": preds.get("recommendation_predicate"),
                "queue_controls_predicate": preds.get("queue_control_predicate"),
                "countdown_declaration_predicate": preds.get("countdown_declaration_predicate"),
                "early_return_reason": str(r.get("early_return_reason") or ""),
                "defer_heavy_first_paint": preds.get("defer_heavy_first_paint"),
            }
        )
    return out
