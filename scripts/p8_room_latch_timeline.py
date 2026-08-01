"""Ordered room-state timeline from latch ledger rows (harness)."""

from __future__ import annotations

from typing import Any


def _snap_room(snap: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snap, dict):
        return {}
    return {
        "room_id": str(snap.get("session_room_id") or snap.get("canonical_blob_room_id") or "").upper(),
        "status": str(snap.get("session_draft_status") or "").lower(),
        "pick_index": snap.get("session_pick_index"),
        "deadline_token": str(snap.get("session_deadline_token") or "")[:120],
        "restore_blocked_reason": str(snap.get("restore_blocked_reason") or ""),
    }


def build_room_state_timeline(rows: list[dict[str, Any]], *, created_room_id: str = "") -> list[dict[str, Any]]:
    created = str(created_room_id or "").strip().upper()
    timeline: list[dict[str, Any]] = []
    last_room = ""
    last_status = ""
    for r in rows:
        ev = str(r.get("event") or "")
        op = "event"
        reason = str(r.get("reason") or r.get("rerun_source") or r.get("read_label") or "")
        before_rid = last_room
        after_rid = last_room
        snap_after: dict[str, Any] = {}

        if ev == "production_stage1_room_state_write":
            op = "write"
            before_rid = str(r.get("prev_room_id") or before_rid).upper()
            after_rid = str(r.get("new_room_id") or "").upper()
            snap_after = _snap_room(r.get("post_write_snapshot"))
        elif ev == "production_stage1_room_state_clear":
            op = "clear"
            before_rid = str(r.get("prev_room_id") or before_rid).upper()
            after_rid = ""
            snap_after = _snap_room(r.get("post_clear_snapshot"))
        elif ev == "production_stage1_room_state_restore":
            op = "restore"
            before_rid = str(r.get("room_id") or before_rid).upper()
            after_rid = str(r.get("restored_room_id") or "").upper()
            snap_after = _snap_room(r.get("post_restore_snapshot"))
            if not after_rid and snap_after.get("room_id"):
                after_rid = str(snap_after.get("room_id") or "").upper()
        elif ev == "production_stage1_room_state_read":
            op = "read"
            snap_after = {
                "room_id": str(r.get("session_room_id") or "").upper(),
                "status": str(r.get("session_draft_status") or "").lower(),
                "pick_index": r.get("session_pick_index"),
                "deadline_token": str(r.get("session_deadline_token") or "")[:120],
                "restore_blocked_reason": str(r.get("restore_blocked_reason") or ""),
            }
            after_rid = str(snap_after.get("room_id") or "")
        elif ev == "production_stage1_surface_decision":
            op = "surface"
            after_rid = str(r.get("session_room_id") or r.get("room_id") or "").upper()
            snap_after = {
                "room_id": after_rid,
                "status": "in_progress" if r.get("draft_in_progress") else "setup",
                "pick_index": r.get("session_pick_index"),
                "deadline_token": str(r.get("session_deadline_token") or r.get("expected_token") or "")[:120],
                "surface": str(r.get("surface") or ""),
            }
        elif ev == "production_stage1_handler_exit_session_state_proof":
            op = "handler_session_proof"
            auth = r.get("authoritative_session_state") or {}
            snap_after = _snap_room(auth)
            after_rid = str(snap_after.get("room_id") or "")
        else:
            after_rid = str(r.get("room_id") or r.get("created_room_id") or before_rid).upper()

        if after_rid:
            last_room = after_rid
        if snap_after.get("status"):
            last_status = str(snap_after.get("status") or "")

        preserve_inference: dict[str, Any] = {}
        if ev == "production_stage1_room_state_restore" and "prepare" in reason:
            post = r.get("post_restore_snapshot") if isinstance(r.get("post_restore_snapshot"), dict) else {}
            blocked = str(post.get("restore_blocked_reason") or "")
            empty_result = not str(r.get("restored_room_id") or "").strip()
            preserve_inference = {
                "restore_result_empty": empty_result,
                "restore_blocked_reason": blocked,
                "room_before": before_rid,
                "room_after_post_restore": str(post.get("session_room_id") or "").upper(),
                "inferred_preserve_success": bool(
                    created
                    and before_rid == created
                    and empty_result
                    and blocked in ("auth_required", "auth_required_for_owned_blob")
                    and str(post.get("session_room_id") or "").upper() == created
                ),
                "inferred_clear_foreign_likely": bool(
                    empty_result and not str(post.get("session_room_id") or "") and before_rid == created
                ),
                "note": "a2e6eb2 preserve helper not ledger-instrumented; inference from post_restore_snapshot",
            }

        timeline.append(
            {
                "ts": r.get("ts"),
                "event": ev,
                "script_run_seq": r.get("script_run_seq"),
                "streamlit_session_id": r.get("streamlit_session_id"),
                "operation": op,
                "reason": reason,
                "room_id_before": before_rid,
                "room_id_after": after_rid or snap_after.get("room_id", ""),
                "draft_status": snap_after.get("status") or last_status,
                "pick_index": snap_after.get("pick_index", r.get("pick_index")),
                "deadline_token": snap_after.get("deadline_token") or str(r.get("deadline") or ""),
                "expected_token": str(r.get("expected_token") or "")[:120],
                "preserve_inference": preserve_inference or None,
                "event_id": r.get("event_id"),
            }
        )
    return timeline
