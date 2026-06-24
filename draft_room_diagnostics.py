"""Shared draft room diagnostics for acceptance testing."""

from __future__ import annotations

from typing import Any


def get_shared_room_diagnostics(session: dict[str, Any]) -> dict[str, Any]:
    """Structured diagnostics snapshot for multiplayer draft rooms."""
    try:
        from draft_room_context import get_global_draft_context, is_multiplayer_draft_active
    except ImportError:
        return {"active": False}

    if not is_multiplayer_draft_active(session):
        return {"active": False}

    ctx = get_global_draft_context(session)
    meta = dict(session.get("draft_room_shared_meta") or {})
    room = session.get("live_draft_room")
    pick_index = None
    pool_count = None
    drafted_count = None
    if isinstance(room, dict):
        pick_index = room.get("current_pick_index")
        drafted_count = len(room.get("drafted_player_ids") or [])
        pool = room.get("pool")
        if pool is not None and hasattr(pool, "__len__"):
            try:
                pool_count = len(pool)
            except Exception:
                pool_count = None

    return {
        "active": True,
        "room_code": ctx.get("room_code"),
        "assigned_team": ctx.get("participant_team"),
        "participant_id": ctx.get("participant_id"),
        "backend": ctx.get("shared_storage_backend") or "unknown",
        "revision": ctx.get("shared_revision"),
        "last_sync_time": meta.get("last_sync_at") or ctx.get("shared_updated_at"),
        "last_sync_reason": meta.get("last_sync_reason") or meta.get("reason"),
        "is_room_host": bool(ctx.get("is_room_host")),
        "room_status": ctx.get("room_status"),
        "current_pick_index": pick_index,
        "drafted_count": drafted_count,
        "pool_count": pool_count,
        "conflict_notice": session.get("_draft_room_conflict_notice"),
    }


def render_shared_room_diagnostics(st: Any, session: dict[str, Any]) -> None:
    """Compact dev/acceptance diagnostics panel."""
    diag = get_shared_room_diagnostics(session)
    if not diag.get("active"):
        return

    with st.expander("Room diagnostics", expanded=False):
        st.caption("Acceptance / dev snapshot — use to verify multiplayer sync.")
        rows = [
            ("Room code", diag.get("room_code") or "—"),
            ("Assigned team", diag.get("assigned_team") or "—"),
            ("Participant id", diag.get("participant_id") or "—"),
            ("Backend", diag.get("backend") or "—"),
            ("Revision", str(diag.get("revision") if diag.get("revision") is not None else "—")),
            ("Last sync", diag.get("last_sync_time") or "—"),
            ("Sync reason", diag.get("last_sync_reason") or "—"),
            ("Host", "yes" if diag.get("is_room_host") else "no"),
            (
                "Pick index",
                str(diag.get("current_pick_index") if diag.get("current_pick_index") is not None else "—"),
            ),
            ("Drafted", str(diag.get("drafted_count") if diag.get("drafted_count") is not None else "—")),
            ("Pool count", str(diag.get("pool_count") if diag.get("pool_count") is not None else "—")),
        ]
        for label, value in rows:
            st.text(f"{label}: {value}")
        if diag.get("conflict_notice"):
            st.warning(str(diag["conflict_notice"]))


def render_shared_room_create_diagnostics(st: Any, session: dict[str, Any]) -> None:
    """Show post-create verification snapshot (dev / acceptance)."""
    raw = session.get("_draft_room_create_diag")
    if not isinstance(raw, dict):
        return
    with st.expander("Create verification (dev)", expanded=True):
        save = raw.get("save_result") if isinstance(raw.get("save_result"), dict) else {}
        loaded = raw.get("immediate_load") if isinstance(raw.get("immediate_load"), dict) else {}
        load_meta = raw.get("load_result") if isinstance(raw.get("load_result"), dict) else {}
        rows = [
            ("Generated room code", raw.get("room_code") or save.get("room_code") or "—"),
            ("Backend", save.get("backend") or loaded.get("backend") or load_meta.get("backend") or "—"),
            ("Save revision", str(save.get("revision") if save.get("revision") is not None else "—")),
            ("Save status", save.get("status") or "—"),
            ("Save pool count", str(save.get("pool_count") if save.get("pool_count") is not None else "—")),
            ("Save picks count", str(save.get("picks_count") if save.get("picks_count") is not None else "—")),
            ("Save team count", str(save.get("team_count") if save.get("team_count") is not None else "—")),
            ("Immediate load found", str(load_meta.get("found"))),
            ("Immediate load revision", str(loaded.get("revision") if loaded.get("revision") is not None else "—")),
            ("Immediate load status", loaded.get("status") or "—"),
            ("Immediate load pool count", str(loaded.get("pool_count") if loaded.get("pool_count") is not None else "—")),
            ("Immediate load picks count", str(loaded.get("picks_count") if loaded.get("picks_count") is not None else "—")),
            ("Valid runtime", str(loaded.get("valid_runtime"))),
        ]
        for label, value in rows:
            st.text(f"{label}: {value}")
        if load_meta.get("query_error"):
            st.code(str(load_meta.get("query_error"))[:2000])


def render_shared_room_join_load_diagnostics(st: Any, session: dict[str, Any]) -> None:
    raw = session.get("_draft_room_join_load_diag")
    if not isinstance(raw, dict):
        return
    with st.expander("Join lookup (dev)", expanded=True):
        rows = [
            ("Room code queried", raw.get("room_code_queried") or "—"),
            ("Backend", raw.get("backend") or "—"),
            ("Found", str(raw.get("found"))),
            ("Reason", raw.get("reason") or "—"),
        ]
        for label, value in rows:
            st.text(f"{label}: {value}")
        if raw.get("query_error"):
            st.code(str(raw.get("query_error"))[:2000])
